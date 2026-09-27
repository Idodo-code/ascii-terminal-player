# ASCII Terminal Video Player

Plays a video file directly in the terminal as live colored ASCII art, with its audio
downsampled to genuine 8-bit PCM playing alongside it.

## Download (Windows, no setup required)

[![Download for Windows](https://img.shields.io/badge/DOWNLOAD-Windows_Installer-2ea44f?style=for-the-badge&logo=windows&logoColor=white)](https://github.com/Idodo-code/ascii-terminal-player/releases/latest/download/AsciiTerminalPlayer-Setup.exe)

Run the downloaded installer. It bundles Python, ffmpeg, and every dependency into a
single `ascii.exe` (via PyInstaller), so nothing else needs installing on a fresh
machine. The installer adds `ascii` to your PATH (per-user, no admin rights required)
so it works from any `cmd`/PowerShell/Windows Terminal prompt, in any directory:

```
ascii
```

Open a **new** terminal window after installing -- already-open ones won't see the
PATH update, which is normal Windows behavior, not a bug in the installer. Pass a path
and options directly if you'd rather skip the file picker:

```
ascii path\to\video.mp4 --cols 120 --loop
```

Run `ascii --help` for the full option list.

Args:
- `--cols` / `--rows` — character grid size (default: auto-fit to the current terminal
  size, accounting for terminal glyphs not being square).
- `--mode` — `color` (default) tints each character by its source pixel color; `mono`
  draws every character in one flat color.
- `--mono-color` — `R,G,B` string for `--mode mono`, e.g. `"0,255,0"` for green.
- `--fps` — override playback fps (default: derived from actual audio duration if
  audio is playing, otherwise the source video's reported fps -- see below).
- `--colors` — optional color quantization cap; fewer distinct colors per frame means
  shorter/faster ANSI output, at the cost of fidelity.
- `--loop` — replay the video (and its audio) when it ends.
- `--no-audio` — don't play the video's audio track.
- `--audio-rate` — 8-bit audio sample rate in Hz (default 11025; lower is more
  lo-fi/crunchy, e.g. 8000).
- `--no-fullscreen` — don't try to maximize the console window before playing.

## How it works

- `video_source.py` reads frames with OpenCV (`VideoSource`), resizes to the character
  grid (`resize_to_grid`), and can optionally quantize colors (`quantize`, posterize
  then merge to the N most frequent) to shorten ANSI output on `--colors`.
- `ascii_terminal.py` is everything else:
  - `RAMP` is the 70-level dark-to-bright density ramp commonly attributed to Paul
    Bourke (based on measured ink coverage per character, not a guess) --
    ` .'`^",:;Il!i><~+_-?][}{1)(|\/tfjrxnuvczXYUJCLQ0OZmwqpdbkhao*#MW&8%B@$`, sparsest
    (blends into the terminal's black background) to densest (stands out).
  - `frame_to_ascii()` maps each pixel's luminance to a `RAMP` index.
  - `frame_to_ansi()` builds one ANSI-colored string per frame (`\x1b[38;2;R;G;Bm`
    color codes). Consecutive same-color characters in a row are grouped into a single
    color code instead of one per character (a space doesn't break a run, since it
    looks the same regardless of color) to keep the string small and fast to render
    even on wide terminals. Each frame is written by moving the cursor back to the
    top-left (`\x1b[H`) rather than clearing the screen, so playback doesn't flicker as
    long as the grid size stays constant. `colorama.init()` makes this work on older
    Windows consoles that don't natively support ANSI escape codes.
  - `fit_grid()` picks the largest character grid that fits the terminal while
    preserving the source video's aspect ratio.
  - `make_console_fullscreen()` maximizes/fullscreens the terminal via `ctypes`.
    Windows Terminal hosts its tabs in a window separate from the hidden conhost
    pseudo-console that `GetConsoleWindow()` returns, so maximizing *that* handle
    (an earlier version of this function) silently did nothing on Windows Terminal.
    It now checks whether the current foreground window -- which, at the moment the
    script starts, should be whatever terminal it was launched from -- is Windows
    Terminal (by window class name `CASCADIA_HOSTING_WINDOW_CLASS`), and if so sends
    it **F11**, its default fullscreen-toggle shortcut. Falls back to classic
    `GetConsoleWindow` + `ShowWindow(SW_MAXIMIZE)` for conhost-based consoles (plain
    cmd.exe/PowerShell windows not running inside Windows Terminal).
  - `prompt_for_video()` opens a native file-picker window (`tkinter.filedialog`)
    filtered to video extensions. Deliberately does *not* set the withdrawn Tk root's
    `-topmost` attribute -- that combination is a known Windows/Tk trap where the
    invisible root can end up as an always-on-top window that silently intercepts
    every click on the whole screen until it's destroyed (a real bug hit during
    development). `lift()`/`focus_force()` bring the actual dialog forward instead,
    and `destroy()` is guaranteed via `try`/`finally`.
  - `play()` is the main loop: read frame -> resize -> (optionally quantize) ->
    ASCII+color -> ANSI string -> write to stdout -> pace to the frame schedule.

### Playback timing and audio sync

An explicit `--fps` always wins. Otherwise, if audio is playing, fps is derived from
`video_frame_count / actual_audio_duration` rather than trusting the video's own
reported fps -- those two can disagree slightly (rounding, variable frame rate,
container metadata), which drifts video and audio out of sync over a long clip even
when every frame renders instantly.

On top of that, each frame is scheduled against elapsed wall time since playback
started, not accumulated per-frame sleeps, and a frame that's already fallen behind
schedule (slow terminal paint, a big/colorful frame, whatever) is skipped rather than
displayed late -- so a rendering hiccup causes one dropped frame, not a permanently
growing lag behind the audio, which plays independently at its own correct real-time
pace regardless of how the video loop is doing.

### Audio

`audio_8bit.py` extracts the video's audio track and downsamples it to genuine 8-bit
unsigned PCM via ffmpeg's own codec conversion (`-acodec pcm_u8 -ar 11025`) -- a real
retro format, not an effect applied afterward -- piped directly into memory as a numpy
array (no temp file). The bundled `imageio-ffmpeg` package provides the ffmpeg binary,
so nothing needs installing system-wide. If the video has no audio track (or
extraction fails for any reason), playback continues without audio rather than
crashing -- but not *silently*: both extraction and playback print a `[audio] ...`
message explaining why on failure (ffmpeg error, no output device, playback exception,
etc.), since a silent failure here was indistinguishable from "no audio track" and
impossible to debug. Pass `verbose=False` to either function to suppress that.

Playback uses `sounddevice` (`sd.play(samples, samplerate, loop=...)`), not the
Windows-only `winsound` module used in an earlier version of this script --
`winsound.PlaySound` turned out to fail silently on repeated/back-to-back runs, which
was the cause of a "played fine once, then no audio at all" bug. `sounddevice.play()`
explicitly stops any previous playback before starting a new one, verified reliable
across repeated play/stop cycles in testing. `--audio-rate` controls how lo-fi/crunchy
it sounds (lower = crunchier), and `--no-audio` disables it entirely.
