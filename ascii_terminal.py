import argparse
import ctypes
import os
import shutil
import sys
import time

import colorama
import cv2
import numpy as np

import audio_8bit
from video_source import VideoSource, quantize, resize_to_grid

VIDEO_EXTENSIONS = (".mp4", ".mov", ".avi", ".mkv", ".webm")

HIDE_CURSOR = "\x1b[?25l"
SHOW_CURSOR = "\x1b[?25h"
CLEAR_SCREEN = "\x1b[2J"
HOME = "\x1b[H"
RESET = "\x1b[0m"

CHAR_ASPECT = 2.0  # typical terminal monospace glyphs are ~2x taller than wide

# Dark -> bright (sparse -> dense ink), index by quantized luminance. The
# 70-level ramp commonly attributed to Paul Bourke, based on measured ink
# coverage per character rather than a guess -- much smoother density
# gradation than a hand-picked handful of characters.
RAMP = " .'`^\",:;Il!i><~+_-?][}{1)(|\\/tfjrxnuvczXYUJCLQ0OZmwqpdbkhao*#MW&8%B@$"


def frame_to_ascii(frame_bgr, color_mode):
    gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
    idx = (gray.astype(np.float32) / 255 * (len(RAMP) - 1)).round().astype(np.int32)
    color_grid = frame_bgr if color_mode else None  # already BGR, matches ANSI code convention below
    return idx, color_grid


def parse_color(s):
    return tuple(int(x) for x in s.split(","))


def color_code(rgb):
    r, g, b = rgb
    return f"\x1b[38;2;{r};{g};{b}m"


def frame_to_ansi(idx_grid, color_grid=None, mono_color=(255, 255, 255)):
    """Builds one ANSI-colored string (rows joined by \\n) for a terminal frame.

    Groups consecutive same-color characters into one color-code + run instead
    of emitting a code per character -- keeps the string (and terminal
    render work) small. Space characters are treated as color-transparent
    (they look the same regardless of color) so they don't break a run.
    """
    rows, cols = idx_grid.shape
    lines = []
    for r in range(rows):
        row_idx = idx_grid[r]
        parts = []

        if color_grid is None:
            parts.append(color_code(mono_color))
            parts.append("".join(RAMP[i] for i in row_idx))
        else:
            row_colors = color_grid[r]
            c = 0
            while c < cols:
                color = tuple(int(v) for v in row_colors[c])
                start = c
                c += 1
                while c < cols and (row_idx[c] == 0 or tuple(int(v) for v in row_colors[c]) == color):
                    c += 1
                parts.append(color_code(color))
                parts.append("".join(RAMP[i] for i in row_idx[start:c]))

        lines.append("".join(parts))
    return "\n".join(lines)


_WT_CLASS = "CASCADIA_HOSTING_WINDOW_CLASS"  # Windows Terminal's real top-level window
VK_F11 = 0x7A
KEYEVENTF_KEYUP = 0x0002


def make_console_fullscreen():
    """Best-effort fullscreen/maximize of the terminal window (Windows only).

    Windows Terminal hosts its tabs in a window separate from the hidden
    conhost pseudo-console that GetConsoleWindow() returns, so maximizing
    *that* handle (an earlier version of this function) silently does
    nothing on Windows Terminal. Instead: check whether the current
    foreground window -- which, at the moment our script starts, should be
    whatever terminal the user launched it from -- is actually Windows
    Terminal (by window class name), and if so send it F11, its default
    fullscreen-toggle shortcut. Falls back to classic GetConsoleWindow +
    ShowWindow(SW_MAXIMIZE) for conhost-based consoles (plain cmd.exe/
    PowerShell windows, not running inside Windows Terminal).
    """
    try:
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        buf = ctypes.create_unicode_buffer(256)
        ctypes.windll.user32.GetClassNameW(hwnd, buf, 256)
        if buf.value == _WT_CLASS:
            ctypes.windll.user32.keybd_event(VK_F11, 0, 0, 0)
            time.sleep(0.05)
            ctypes.windll.user32.keybd_event(VK_F11, 0, KEYEVENTF_KEYUP, 0)
        else:
            console_hwnd = ctypes.windll.kernel32.GetConsoleWindow()
            if console_hwnd:
                ctypes.windll.user32.ShowWindow(console_hwnd, 3)  # SW_MAXIMIZE
        time.sleep(0.2)  # let the resize actually take effect before we measure it
    except Exception:
        pass


def prompt_for_video(initial_dir):
    """Opens a native file-picker window for choosing a video file, instead
    of requiring a typed path. Returns the chosen path, or None if the user
    cancels.

    Deliberately does NOT set the withdrawn root's "-topmost" attribute --
    that combination is a known Windows/Tk trap where the invisible root can
    end up as an always-on-top window that silently intercepts every click
    on the whole screen until it's destroyed. `lift()`/`focus_force()` bring
    the actual dialog forward instead, and destroy() is guaranteed via
    try/finally so a hidden root can never linger if something goes wrong.
    """
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()
    try:
        root.lift()
        root.focus_force()
        path = filedialog.askopenfilename(
            parent=root,
            title="Choose a video file",
            initialdir=initial_dir,
            filetypes=[("Video files", " ".join(f"*{ext}" for ext in VIDEO_EXTENSIONS)),
                       ("All files", "*.*")],
        )
    finally:
        root.destroy()
    return path or None


def get_terminal_size_chars():
    size = shutil.get_terminal_size(fallback=(80, 24))
    return size.columns, max(1, size.lines - 1)  # leave a line so it doesn't scroll


def fit_grid(src_w, src_h, max_cols, max_rows, char_aspect=CHAR_ASPECT):
    """Largest cols x rows that fits within max_cols x max_rows while keeping
    the source's aspect ratio, accounting for terminal glyphs not being square."""
    src_aspect = src_w / src_h
    cols = max_cols
    rows = round(cols / src_aspect / char_aspect)
    if rows > max_rows:
        rows = max_rows
        cols = round(rows * src_aspect * char_aspect)
    return max(1, cols), max(1, rows)


def play(video_path, cols=None, rows=None, mode="color", mono_color=(255, 255, 255),
         fps=None, colors=None, loop=False, audio=True, audio_rate=11025,
         fullscreen=True):
    colorama.init()

    if fullscreen:
        make_console_fullscreen()

    video = VideoSource(video_path)
    frame_count = video.cap.get(cv2.CAP_PROP_FRAME_COUNT)

    if cols is None or rows is None:
        ok, first_frame = video.cap.read()
        if not ok:
            raise IOError("Video has no frames")
        video.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
        src_h, src_w = first_frame.shape[:2]
        term_cols, term_rows = get_terminal_size_chars()
        fit_cols, fit_rows = fit_grid(src_w, src_h, term_cols, term_rows)
        cols = cols or fit_cols
        rows = rows or fit_rows

    samples = audio_8bit.extract_8bit_samples(video_path, sample_rate=audio_rate) if audio else None

    # An explicit --fps always wins. Otherwise, if there's audio, pace the
    # video against the *actual* extracted audio duration rather than the
    # video's own reported fps -- those can disagree (rounding, variable
    # frame rate, container metadata quirks), which drifts video and audio
    # out of sync over a long clip even if every frame renders instantly.
    target_fps = fps
    if target_fps is None and samples is not None and frame_count > 0:
        duration = len(samples) / audio_rate
        if duration > 0:
            target_fps = frame_count / duration
    if target_fps is None:
        target_fps = video.fps
    frame_interval = 1.0 / target_fps if target_fps > 0 else 0

    sys.stdout.write(CLEAR_SCREEN + HIDE_CURSOR)
    sys.stdout.flush()
    try:
        if samples is not None:
            audio_8bit.play_async(samples, audio_rate, loop=loop)

        while True:
            start = time.perf_counter()
            frame_idx = 0
            for frame in video.frames():
                # Scheduled against elapsed wall time since this pass started,
                # not accumulated per-frame sleeps -- if rendering has fallen
                # behind (slow terminal, big/colorful frames, etc.), skip
                # displaying stale frames instead of drifting the whole
                # video out of sync with audio, which plays independently at
                # its own correct real-time pace regardless of our loop.
                scheduled = frame_idx * frame_interval
                now = time.perf_counter() - start
                frame_idx += 1
                if frame_interval > 0 and now > scheduled + frame_interval:
                    continue

                small = resize_to_grid(frame, cols, rows)
                if colors:
                    small = quantize(small, max_colors=colors)
                idx_grid, color_grid = frame_to_ascii(small, mode == "color")
                if color_grid is not None:
                    color_grid = color_grid[:, :, ::-1]  # BGR -> RGB for ANSI codes

                text = frame_to_ansi(idx_grid, color_grid, mono_color)
                sys.stdout.write(HOME + text + RESET)
                sys.stdout.flush()

                next_scheduled = frame_idx * frame_interval
                sleep_time = next_scheduled - (time.perf_counter() - start)
                if sleep_time > 0:
                    time.sleep(sleep_time)

            if not loop:
                break
            video.release()
            video = VideoSource(video_path)
    except KeyboardInterrupt:
        pass
    finally:
        video.release()
        audio_8bit.stop()
        sys.stdout.write(RESET + SHOW_CURSOR + "\n")
        sys.stdout.flush()


def parse_args():
    p = argparse.ArgumentParser(description="Play a video as live ASCII art in the terminal.")
    p.add_argument("video", nargs="?", default=None,
                    help="Path to the video file (omit to pick from a list instead)")
    p.add_argument("--cols", type=int, default=None, help="Character columns (default: fit terminal)")
    p.add_argument("--rows", type=int, default=None, help="Character rows (default: fit terminal)")
    p.add_argument("--mode", choices=["mono", "color"], default="color")
    p.add_argument("--mono-color", default="255,255,255", help="R,G,B for --mode mono")
    p.add_argument("--fps", type=float, default=None, help="Override playback fps (default: source fps)")
    p.add_argument("--colors", type=int, default=None,
                    help="Optional color quantization cap (fewer distinct colors per "
                         "frame = shorter/faster terminal output, at the cost of fidelity)")
    p.add_argument("--loop", action="store_true", help="Replay the video when it ends")
    p.add_argument("--no-audio", action="store_true",
                    help="Don't play the video's audio track (played by default, "
                         "downsampled to real 8-bit PCM via ffmpeg, if present)")
    p.add_argument("--audio-rate", type=int, default=11025,
                    help="8-bit audio sample rate in Hz (default 11025; lower is "
                         "more lo-fi/crunchy, e.g. 8000)")
    p.add_argument("--no-fullscreen", action="store_true",
                    help="Don't try to maximize the console window before playing")
    return p.parse_args()


def main():
    args = parse_args()

    video_path = args.video
    if video_path is None:
        video_path = prompt_for_video(os.getcwd())
        if video_path is None:
            return

    play(video_path, cols=args.cols, rows=args.rows, mode=args.mode,
         mono_color=parse_color(args.mono_color), fps=args.fps,
         colors=args.colors, loop=args.loop, audio=not args.no_audio,
         audio_rate=args.audio_rate, fullscreen=not args.no_fullscreen)


if __name__ == "__main__":
    main()
