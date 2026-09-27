"""Generates the app icon: a static ASCII-art donut (torus) with depth shading,
built from real 3D torus math + Lambertian lighting (the classic "donut.c"
technique), not a screenshot or copy of any existing image. Transparent
background, legibly spaced characters.
"""
import numpy as np
from PIL import Image, ImageDraw, ImageFont

RAMP = " .:-=+*#%@"  # short, minimalist ramp -- dark/sparse -> bright/dense
FONT_PATH = "C:/Windows/Fonts/consolab.ttf"

GRID_COLS = 42           # character columns (resolution along the wider axis)
R1, R2 = 1.0, 2.0        # tube radius, donut radius
A, B = 0.9, 0.9          # fixed tilt angles chosen for a recognizable 3/4 view
K2 = 5.0                 # viewer distance
THETA_N, PHI_N = 300, 600  # sample density around the two torus angles
FILL_FRACTION = 0.75     # leaves visible padding between the donut and the background
FONT_SIZE = 34           # sized so the rendered footprint fills most of the
                         # black background's interior (900px canvas, ~846px
                         # usable after its margin) -- font_size=22 (the
                         # original arbitrary choice) only ever produced a
                         # ~504px footprint, wasting most of that space
                         # regardless of how the fill/grid math was tuned

GREEN_DIM = np.array([40, 120, 70])
GREEN_BRIGHT = np.array([120, 255, 170])


def render_luminance_grid(grid_cols, grid_rows, aspect):
    """Returns (surface_mask, luminance) arrays of shape (grid_rows, grid_cols):
    torus surface samples projected to a character grid with a z-buffer
    (nearest surface wins) and per-pixel Lambertian luminance.

    `aspect` (step_w / step_h) is baked into the projection itself so the
    donut renders round regardless of the grid's row/col counts -- it must
    match whatever aspect grid_rows was chosen with (see main()), otherwise
    this and the grid-squaring cancel incorrectly and the shape distorts.
    """
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

    # Project (unscaled) first, measure its *actual* bounding box, then derive
    # scale and center from that -- a fixed scale/grid-center assumption was
    # an earlier bug: at this tilt the projection is asymmetric, so no amount
    # of re-centering after the fact could get the whole donut to fit; part
    # of it was mathematically guaranteed to be clipped off. Deriving
    # scale/center from the measured extent instead makes this correct for
    # any tilt (A, B), not just one this happened to be tuned against.
    proj_x = ooz * x
    proj_y = ooz * y * aspect  # bakes in the row/col aspect compensation

    span_x = proj_x.max() - proj_x.min()
    span_y = proj_y.max() - proj_y.min()
    scale = grid_cols * FILL_FRACTION / max(span_x, span_y)
    center_x = (proj_x.max() + proj_x.min()) / 2
    center_y = (proj_y.max() + proj_y.min()) / 2

    xp = (grid_cols / 2 + scale * (proj_x - center_x)).astype(np.int32)
    yp = (grid_rows / 2 - scale * (proj_y - center_y)).astype(np.int32)

    luminance = (
        cos_p * cos_t * sin_B
        - cos_A * cos_t * sin_p
        - sin_A * sin_t
        + cos_B * (cos_A * sin_t - cos_t * sin_A * sin_p)
    )

    # Occlusion (is there a surface point here at all) must NOT depend on
    # luminance sign -- a real surface point can legitimately face away from
    # the light (negative luminance) while still being the nearest, visible
    # surface at that pixel. Filtering those out here was an earlier bug: it
    # made shadowed-but-present surface indistinguishable from true
    # background, which read as a second "hole" that isn't really there.
    surface_mask = np.full((grid_rows, grid_cols), False)
    lum_grid = np.zeros((grid_rows, grid_cols), dtype=np.float32)

    valid = (xp >= 0) & (xp < grid_cols) & (yp >= 0) & (yp < grid_rows)
    flat_xp, flat_yp = xp[valid], yp[valid]
    flat_ooz, flat_lum = ooz[valid], luminance[valid]

    # Sort by depth ascending (far to near) so the last write per pixel is nearest.
    order = np.argsort(flat_ooz)
    for xi, yi, l in zip(flat_xp[order], flat_yp[order], flat_lum[order]):
        surface_mask[yi, xi] = True
        lum_grid[yi, xi] = l

    return surface_mask, lum_grid


def main():
    font = ImageFont.truetype(FONT_PATH, FONT_SIZE)
    ascent, descent = font.getmetrics()
    glyph_h = ascent + descent
    glyph_w = round(font.getlength("M"))
    step_w = round(glyph_w * 1.0)   # spaced, legible pitch (not the tight
    step_h = round(glyph_h * 0.85)  # video-frame overlap trick)

    # A square character grid (equal rows/cols) with non-square cells forces
    # a non-square footprint (rows*step_h != cols*step_w), which wastes
    # canvas space in whichever axis has slack and caps the achievable size
    # on the other -- exactly what capped this icon's size before. Choosing
    # grid_rows so the footprint comes out square fixes that; the aspect
    # ratio (step_w/step_h) baked into render_luminance_grid's projection
    # must match this choice, or the donut distorts instead of just resizing.
    aspect = step_w / step_h
    grid_cols = GRID_COLS
    grid_rows = round(grid_cols * aspect)

    surface_mask, lum_grid = render_luminance_grid(grid_cols, grid_rows, aspect)

    lum_norm = np.clip(lum_grid / np.sqrt(2), 0, 1)
    idx = (lum_norm * (len(RAMP) - 1)).round().astype(np.int32)
    # Any real surface point gets at least the dimmest *visible* character
    # (index 1 -- RAMP[0] is a literal space). Only pixels with no surface
    # at all stay blank/transparent.
    idx = np.maximum(idx, 1)

    canvas_size = 900
    out = Image.new("RGBA", (canvas_size, canvas_size), (0, 0, 0, 0))
    odraw = ImageDraw.Draw(out)

    # Rounded-square black background, baked into the image (not relying on
    # the OS to mask it) so it looks the same everywhere.
    bg_margin = round(canvas_size * 0.03)
    corner_radius = round(canvas_size * 0.20)
    odraw.rounded_rectangle(
        [bg_margin, bg_margin, canvas_size - bg_margin, canvas_size - bg_margin],
        radius=corner_radius, fill=(10, 10, 10, 255),
    )

    # Center on the *actual* rendered content's bounding box, not the
    # theoretical grid center -- at this tilt the donut's visible extent
    # isn't perfectly symmetric within its own grid, so assuming grid/2 is
    # the true center can leave it visibly off-center.
    rows_with_content = np.where(surface_mask.any(axis=1))[0]
    cols_with_content = np.where(surface_mask.any(axis=0))[0]
    content_row_center = (rows_with_content.min() + rows_with_content.max()) / 2
    content_col_center = (cols_with_content.min() + cols_with_content.max()) / 2

    offset_x = round(canvas_size / 2 - (content_col_center + 0.5) * step_w)
    offset_y = round(canvas_size / 2 - (content_row_center + 0.5) * step_h)

    for r in range(grid_rows):
        y = offset_y + r * step_h
        for c in range(grid_cols):
            if not surface_mask[r, c]:
                continue
            ch = RAMP[idx[r, c]]
            t = lum_norm[r, c]
            color = tuple(int(v) for v in (GREEN_DIM + (GREEN_BRIGHT - GREEN_DIM) * t))
            x = offset_x + c * step_w
            odraw.text((x, y), ch, font=font, fill=color + (255,))

    out.save("assets/icon_preview.png")
    print("wrote assets/icon_preview.png", out.size)
    print(f"grid: {grid_cols}x{grid_rows}, footprint: {grid_cols*step_w}x{grid_rows*step_h}")


if __name__ == "__main__":
    main()
