"""Generates the app icon: a static ASCII-art donut (torus) with depth shading,
built from real 3D torus math + Lambertian lighting (the classic "donut.c"
technique), not a screenshot or copy of any existing image. Transparent
background, legibly spaced characters.
"""
import numpy as np
from PIL import Image, ImageDraw, ImageFont

RAMP = " .:-=+*#%@"  # short, minimalist ramp -- dark/sparse -> bright/dense
FONT_PATH = "C:/Windows/Fonts/consolab.ttf"

GRID = 42               # character grid (square)
R1, R2 = 1.0, 2.0        # tube radius, donut radius
A, B = 0.9, 0.9          # fixed tilt angles chosen for a recognizable 3/4 view
K2 = 5.0                 # viewer distance
THETA_N, PHI_N = 300, 600  # sample density around the two torus angles

GREEN_DIM = np.array([40, 120, 70])
GREEN_BRIGHT = np.array([120, 255, 170])


def render_luminance_grid(grid):
    """Returns (idx, lit_mask, luminance) arrays of shape (grid, grid): torus
    surface samples projected to a character grid with a z-buffer (nearest
    surface wins) and per-pixel Lambertian luminance."""
    theta = np.linspace(0, 2 * np.pi, THETA_N, endpoint=False)
    phi = np.linspace(0, 2 * np.pi, PHI_N, endpoint=False)
    theta, phi = np.meshgrid(theta, phi, indexing="ij")

    cos_t, sin_t = np.cos(theta), np.sin(theta)
    cos_p, sin_p = np.cos(phi), np.sin(phi)
    cos_A, sin_A = np.cos(A), np.sin(A)
    cos_B, sin_B = np.cos(B), np.sin(B)

    circle_x = R2 + R1 * cos_t
    circle_y = R1 * sin_t

    x = circle_x * (cos_B * cos_p + sin_A * sin_B * sin_p) - circle_y * cos_A * sin_B
    y = circle_x * (sin_B * cos_p - sin_A * cos_B * sin_p) + circle_y * cos_A * cos_B
    z = K2 + cos_A * circle_x * sin_p + circle_y * sin_A
    ooz = 1.0 / z

    # Fit the projected donut to the character grid, filling most of it.
    scale = grid * 0.62
    xp = (grid / 2 + scale * ooz * x).astype(np.int32)
    yp = (grid / 2 - scale * ooz * y * 0.5).astype(np.int32)  # *0.5: chars are tall

    luminance = (
        cos_p * cos_t * sin_B
        - cos_A * cos_t * sin_p
        - sin_A * sin_t
        + cos_B * (cos_A * sin_t - cos_t * sin_A * sin_p)
    )

    # Occlusion (is there a surface point here at all) must NOT depend on
    # luminance sign -- a real surface point can legitimately face away from
    # the light (negative luminance) while still being the nearest, visible
    # surface at that pixel. Filtering those out here was the actual bug:
    # it made shadowed-but-present surface indistinguishable from true
    # background, which read as a second "hole" that isn't really there.
    surface_mask = np.full((grid, grid), False)
    lum_grid = np.zeros((grid, grid), dtype=np.float32)

    valid = (xp >= 0) & (xp < grid) & (yp >= 0) & (yp < grid)
    flat_xp, flat_yp = xp[valid], yp[valid]
    flat_ooz, flat_lum = ooz[valid], luminance[valid]

    # Sort by depth ascending (far to near) so the last write per pixel is nearest.
    order = np.argsort(flat_ooz)
    for xi, yi, l in zip(flat_xp[order], flat_yp[order], flat_lum[order]):
        surface_mask[yi, xi] = True
        lum_grid[yi, xi] = l

    return surface_mask, lum_grid


def main():
    surface_mask, lum_grid = render_luminance_grid(GRID)

    lum_norm = np.clip(lum_grid / np.sqrt(2), 0, 1)
    idx = (lum_norm * (len(RAMP) - 1)).round().astype(np.int32)
    # Any real surface point gets at least the dimmest *visible* character
    # (index 1 -- RAMP[0] is a literal space). Only pixels with no surface
    # at all stay blank/transparent.
    idx = np.maximum(idx, 1)

    font = ImageFont.truetype(FONT_PATH, 22)
    ascent, descent = font.getmetrics()
    glyph_h = ascent + descent
    glyph_w = round(font.getlength("M"))
    step_w = round(glyph_w * 1.0)   # spaced, legible pitch (not the tight
    step_h = round(glyph_h * 0.85)  # video-frame overlap trick)

    canvas_size = 900
    out = Image.new("RGBA", (canvas_size, canvas_size), (0, 0, 0, 0))
    odraw = ImageDraw.Draw(out)
    offset_x = (canvas_size - GRID * step_w) // 2
    offset_y = (canvas_size - GRID * step_h) // 2

    for r in range(GRID):
        y = offset_y + r * step_h
        for c in range(GRID):
            if not surface_mask[r, c]:
                continue
            ch = RAMP[idx[r, c]]
            t = lum_norm[r, c]
            color = tuple(int(v) for v in (GREEN_DIM + (GREEN_BRIGHT - GREEN_DIM) * t))
            x = offset_x + c * step_w
            odraw.text((x, y), ch, font=font, fill=color + (255,))

    out.save("assets/icon_preview.png")
    print("wrote assets/icon_preview.png", out.size)


if __name__ == "__main__":
    main()
