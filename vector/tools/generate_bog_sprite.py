#!/usr/bin/env python3
"""Generate bog pattern sprite at 1x (36x36) and 2x (72x72).

Bog visual language:
  - Dark tannin-stained pools — irregular blob shapes (union of two ellipses)
    in a very dark brownish-blue with a softer halo
  - Scattered sphagnum specks in rust and olive between the pools, drawn as
    small filled dots (not crosses)
  - A faint peat wash over the landcover-fill tint underneath

Tileable: every mark is painted at nine wrapped offsets ({-tile, 0, +tile} in
both axes) so any pixel that crosses an edge re-appears on the opposite edge
and the repeat is seamless.

Drawn natively at each scale (1×: 36×36, 2×: 72×72) — the 2× version uses
larger pool ellipses and 3-px speck radii rather than pixel-doubling the 1×.
"""

from PIL import Image, ImageDraw, ImageFilter
from pathlib import Path

SYMBOLS_1X = Path("/home/jonlynch/OpenTopoMap/vector/maplibregljs/otm_symbols")
SYMBOLS_2X = Path("/home/jonlynch/OpenTopoMap/vector/maplibregljs/otm_symbols_2x")

TILE_1X = 36

# Colour palette (RGBA)
# Very faint peat wash to deepen the ochre fill underneath
PEAT_WASH = (80, 110, 135, 40)

# Dark tannin pool — desaturated brownish-blue
POOL_DARK = (50, 68, 90, 108)
# Slightly lighter pool halo for soft edge
POOL_EDGE = (65, 78, 98, 40)

# Sphagnum hummock specks
RUST = (150, 78, 32, 225)
OLIVE = (100, 108, 50, 215)
PALE = (170, 135, 80, 205)

SPECK_COLOURS = {"rust": RUST, "olive": OLIVE, "pale": PALE}

# Pools as a list of "lobes" — each pool is a union of two slightly offset
# ellipses to break the perfectly-round shape.  Coords in 1× space.
# (cx, cy, rx, ry, dx1, dy1, rx1, ry1, dx2, dy2, rx2, ry2)
POOLS = [
    # (anchor_x, anchor_y, [(off_x, off_y, rx, ry), ...])
    (8, 7, [(0, 0, 2, 1), (2, 1, 2, 1)]),        # upper-left
    (26, 11, [(0, 0, 2, 1), (-2, 1, 2, 1)]),    # upper-right
    (16, 20, [(0, 0, 2, 2), (3, -1, 2, 1)]),    # central
    (3, 28, [(0, 0, 2, 1), (2, 1, 2, 1)]),      # lower-left
    (30, 26, [(0, 0, 2, 2), (-1, 2, 2, 1)]),    # lower-right
    (22, 33, [(0, 0, 2, 1), (2, -1, 2, 1)]),    # bottom, wraps to top
]

# Sphagnum specks — placed between pools so they read as moss between water.
# (cx, cy, colour_key)
SPECKS = [
    (2, 3, "rust"),
    (14, 3, "olive"),
    (20, 6, "pale"),
    (32, 4, "olive"),
    (3, 15, "pale"),
    (11, 15, "rust"),
    (25, 16, "rust"),
    (33, 19, "olive"),
    (7, 22, "olive"),
    (21, 25, "pale"),
    (28, 21, "rust"),
    (14, 28, "rust"),
    (6, 33, "pale"),
    (18, 35, "olive"),
    (30, 33, "rust"),
    (12, 10, "pale"),
    (25, 30, "olive"),
    (35, 12, "pale"),
]


def paste_wrapped(base, sprite, anchor_x, anchor_y, scale):
    """Paste sprite onto base at nine wrapped offsets for seamless tiling."""
    tile = TILE_1X * scale
    for dy in (-tile, 0, tile):
        for dx in (-tile, 0, tile):
            base.alpha_composite(sprite, (anchor_x + dx, anchor_y + dy))


def make_pool_canvas(lobes, scale):
    """Build a transparent canvas containing one pool drawn from its lobes."""
    # Compute bounding box of all lobes in 1× space
    xs_min = min(off_x - rx for (off_x, off_y, rx, ry) in lobes)
    xs_max = max(off_x + rx for (off_x, off_y, rx, ry) in lobes)
    ys_min = min(off_y - ry for (off_x, off_y, rx, ry) in lobes)
    ys_max = max(off_y + ry for (off_x, off_y, rx, ry) in lobes)
    pad = 2  # for halo + blur
    w = (xs_max - xs_min + 2 * pad) * scale + 1
    h = (ys_max - ys_min + 2 * pad) * scale + 1
    # Origin offset: where lobe (0,0) sits on this canvas
    ox = (-xs_min + pad) * scale
    oy = (-ys_min + pad) * scale

    canvas = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)

    # First pass: halo (slightly larger)
    for (off_x, off_y, rx, ry) in lobes:
        cx = ox + off_x * scale
        cy = oy + off_y * scale
        rxs = rx * scale + 1 * scale
        rys = ry * scale + 1 * scale
        draw.ellipse([cx - rxs, cy - rys, cx + rxs, cy + rys], fill=POOL_EDGE)

    # Second pass: dark core
    for (off_x, off_y, rx, ry) in lobes:
        cx = ox + off_x * scale
        cy = oy + off_y * scale
        rxs = rx * scale
        rys = ry * scale
        draw.ellipse([cx - rxs, cy - rys, cx + rxs, cy + rys], fill=POOL_DARK)

    # Soft edge — small Gaussian blur to suggest water surface
    canvas = canvas.filter(ImageFilter.GaussianBlur(radius=0.45 * scale))

    return canvas, ox, oy


def make_speck_canvas(colour, scale):
    """Tiny moss speck — 1 px at 1×, 3 px disc at 2×."""
    if scale == 1:
        canvas = Image.new("RGBA", (1, 1), (0, 0, 0, 0))
        canvas.putpixel((0, 0), colour)
        return canvas, 0, 0
    # 2× — draw a 3×3 filled disc (radius 1) anti-aliased via supersampling
    s = 8
    big = Image.new("RGBA", (3 * s, 3 * s), (0, 0, 0, 0))
    bdraw = ImageDraw.Draw(big)
    cx = cy = (3 * s) // 2
    r = 1 * s
    bdraw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=colour)
    canvas = big.resize((3, 3), Image.LANCZOS)
    return canvas, 1, 1


def render_bog(scale):
    size = TILE_1X * scale
    img = Image.new("RGBA", (size, size), PEAT_WASH)

    # Pools first so any overlapping specks appear on top
    for (cx, cy, lobes) in POOLS:
        pool, ox, oy = make_pool_canvas(lobes, scale)
        # Anchor: paste so that (cx, cy) on the tile aligns with the lobe (0,0)
        anchor_x = cx * scale - ox
        anchor_y = cy * scale - oy
        paste_wrapped(img, pool, anchor_x, anchor_y, scale)

    # Specks
    for (cx, cy, key) in SPECKS:
        speck, ox, oy = make_speck_canvas(SPECK_COLOURS[key], scale)
        anchor_x = cx * scale - ox
        anchor_y = cy * scale - oy
        paste_wrapped(img, speck, anchor_x, anchor_y, scale)

    return img


def main():
    for scale, out_dir in ((1, SYMBOLS_1X), (2, SYMBOLS_2X)):
        img = render_bog(scale)
        out_path = out_dir / "bog.png"
        img.save(out_path, "PNG")
        print(f"wrote {out_path} ({img.size[0]}x{img.size[1]})")


if __name__ == "__main__":
    main()
