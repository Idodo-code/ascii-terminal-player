import cv2
import numpy as np


class VideoSource:
    def __init__(self, path):
        self.cap = cv2.VideoCapture(path)
        if not self.cap.isOpened():
            raise IOError(f"Cannot open video: {path}")
        self.fps = self.cap.get(cv2.CAP_PROP_FPS) or 24.0

    def frames(self):
        while True:
            ok, frame = self.cap.read()
            if not ok:
                break
            yield frame

    def release(self):
        self.cap.release()


def resize_to_grid(frame, cols, rows):
    return cv2.resize(frame, (cols, rows), interpolation=cv2.INTER_AREA)


def quantize(frame, max_colors=48, levels=6):
    """Reduce a small BGR frame to at most `max_colors` distinct colors.

    Posterizes first (cheap, deterministic), then if that still leaves too
    many distinct colors, remaps every pixel to its nearest surviving color.
    Used optionally to shorten the ANSI output per frame (fewer distinct
    colors -> fewer color-code runs to emit).
    """
    step = max(256 // levels, 1)
    posterized = (frame.astype(np.int32) // step) * step + step // 2
    posterized = np.clip(posterized, 0, 255).astype(np.uint8)

    flat = posterized.reshape(-1, 3)
    colors, counts = np.unique(flat, axis=0, return_counts=True)

    if len(colors) > max_colors:
        order = np.argsort(-counts)
        keep = colors[order[:max_colors]].astype(np.int32)
        diffs = flat[:, None, :].astype(np.int32) - keep[None, :, :]
        dist = np.sum(diffs * diffs, axis=2)
        nearest = np.argmin(dist, axis=1)
        flat = keep[nearest].astype(np.uint8)

    return flat.reshape(frame.shape)
