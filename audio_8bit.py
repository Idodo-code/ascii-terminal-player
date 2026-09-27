import subprocess

import imageio_ffmpeg
import numpy as np

try:
    import sounddevice as sd
except ImportError:
    sd = None

# Suppress the console window ffmpeg would otherwise briefly flash on Windows.
_NO_WINDOW = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0


def extract_8bit_samples(video_path, sample_rate=11025, verbose=True):
    """Extracts `video_path`'s audio track as a 1-D numpy uint8 array of raw
    8-bit unsigned PCM samples at `sample_rate` Hz, mono -- genuine bit-depth
    /sample-rate reduction via ffmpeg's own codec conversion (piped directly
    to memory, no temp file involved), not just an audio effect. Returns
    None if the video has no audio track (or extraction fails for any
    reason -- audio is a nice-to-have here, not worth crashing playback over).
    With `verbose` (the default), prints *why* on failure instead of just
    silently returning None, since a silent failure here is indistinguishable
    from "no audio track" and impossible to debug.
    """
    cmd = [
        imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-loglevel", "error",
        "-i", video_path,
        "-vn", "-ac", "1", "-ar", str(sample_rate), "-acodec", "pcm_u8", "-f", "u8",
        "-",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, creationflags=_NO_WINDOW)
    except Exception as exc:
        if verbose:
            print(f"[audio] Could not run ffmpeg: {exc}")
        return None

    if result.returncode != 0:
        stderr = result.stderr.decode(errors="replace").strip()
        if "does not contain any stream" in stderr:
            # The common, unremarkable case: the video simply has no audio
            # track, which ffmpeg reports as a mapping failure rather than
            # cleanly producing empty output.
            if verbose:
                print("[audio] No audio track found in this video.")
        elif verbose:
            print(f"[audio] ffmpeg exited with code {result.returncode}"
                  f"{': ' + stderr if stderr else ''}")
        return None

    if len(result.stdout) < 100:
        if verbose:
            print("[audio] No audio track found (or it decoded to almost nothing).")
        return None

    return np.frombuffer(result.stdout, dtype=np.uint8)


def play_async(samples, sample_rate, loop=False, verbose=True):
    """Plays 8-bit PCM samples in the background (non-blocking). No-op if
    sounddevice isn't available or there are no samples. `sd.play()` stops
    any previous playback before starting, so this is safe to call repeatedly
    across runs without leftover state from a prior playback getting stuck.
    With `verbose` (the default), prints *why* on failure instead of silently
    doing nothing.
    """
    if sd is None:
        if verbose:
            print("[audio] sounddevice isn't installed -- run "
                  "'python -m pip install sounddevice'.")
        return
    if samples is None:
        return

    try:
        devices = sd.query_devices()
        default_output = sd.default.device[1]
        if default_output is None or default_output < 0:
            if verbose:
                print("[audio] No default output device found. Available devices:")
                print(devices)
            return
    except Exception as exc:
        if verbose:
            print(f"[audio] Could not query audio devices: {exc}")
        return

    try:
        sd.play(samples, samplerate=sample_rate, loop=loop)
    except Exception as exc:
        if verbose:
            print(f"[audio] Playback failed to start: {exc}")


def stop():
    if sd is None:
        return
    sd.stop()
