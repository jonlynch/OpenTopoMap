#!/usr/bin/env python3
"""Generate dune pattern sprite at 1× (36×36) and 2× (72×72).

Dune visual language:
  - Background wash: warm pale sandy cream, semi-transparent, so hillshading
    can still bleed through (dune terrain is interesting topography)
  - Pattern marks: barchan crescents — a curved ridge that is convex on the
    windward side with two horns trailing downwind. Drawn as an arc of warm
    tan/ochre, with a slightly darker shadow arc on the inner (leeward) edge
    representing the steep slip face
  - 5 crescents per tile in a loose, slightly staggered arrangement, with
    minor size and angle variation for naturalism

Tileable: every crescent is painted at nine wrapped offsets ({-tile, 0, +tile}
in both axes) so any arc that crosses an edge re-appears on the opposite edge
and the repeat is seamless.

Drawn natively at each scale (1×: 36×36, 2×: 72×72) using supersampled arcs.
"""

from PIL import Image, ImageDraw
from pathlib import Path

SYMBOLS_1X = Path("/home/jonlynch/OpenTopoMap/vector/maplibregljs/otm_symbols")
SYMBOLS_2X = Path("/home/jonlynch/OpenTopoMap/vector/maplibregljs/otm_symbols_2x")

TILE_1X = 36

# Colour palette (RGBA)
# Background: warm pale sandy cream — kept light so hillshading shows through
BG_WASH = (220, 198, 140, 80)

# Main crescent ridge — warm tan/ochre
RIDGE = (185, 150, 75, 215)

# Slip-face shadow (inner edge of arc) — darker, suggests steep leeward slope
SHADOW = (140, 110, 55, 165)


# Each crescent is (cx, cy, radius, start_deg, end_deg)
# Angles in PIL convention: 0° = east (+x), increasing clockwise (since y is
# down). Open downward / convex upward means the arc sweeps the upper half:
# from roughly 200° (lower-left) round through 270° (top) to 340° (lower-right).
# Slight variation in radius and sweep gives a natural look.
# Coordinates in 1× tile space (36×36).
CRESCENTS = [
    (7,  9,  4, 205, 335),    # upper-left
    (24, 6,  5, 200, 340),    # upper-right (wraps top edge slightly)
    (15, 19, 4, 210, 330),    # central
    (30, 22, 4, 200, 340),    # right-middle (horn wraps right edge)
    (5,  28, 5, 205, 335),    # lower-left
    (22, 31, 4, 200, 340),    # lower (wraps bottom edge)
]


def paste_wrapped(base, sprite, anchor_x, anchor_y, scale):
    """Paste sprite onto base at nine wrapped offsets for seamless tiling."""
    tile = TILE_1X * scale
    for dy in (-tile, 0, tile):
        for dx in (-tile, 0, tile):
            base.alpha_composite(sprite, (anchor_x + dx, anchor_y + dy))


def make_crescent_canvas(radius, start_deg, end_deg, scale):
    """Draw one barchan crescent (ridge arc + inner shadow arc) onto a small
    transparent canvas. Returns the canvas plus the offset to the crescent
    centre so the caller can place it.

    Implementation: supersample at 4× then downscale with LANCZOS for smooth
    anti-aliased arcs at both 1× and 2× sprite scales.
    """
    ss = 4  # supersample factor

    # Ridge stroke widths (1× units)
    ridge_w = 2 if scale == 1 else 3
    shadow_w = 1 if scale == 1 else 2
    # Shadow arc sits just inside the ridge (smaller radius)
    shadow_offset = 1 if scale == 1 else 2

    # Padding so strokes don't clip
    pad = ridge_w + 2

    # Canvas size at final scale
    size_final = (radius + pad) * 2 * scale
    size_big = size_final * ss

    big = Image.new("RGBA", (size_big, size_big), (0, 0, 0, 0))
    bdraw = ImageDraw.Draw(big)

    cx_big = size_big // 2
    cy_big = size_big // 2
    r_ridge_big = radius * scale * ss
    r_shadow_big = (radius - shadow_offset) * scale * ss

    # Ridge arc (outer, main crescent)
    bbox_ridge = [
        cx_big - r_ridge_big, cy_big - r_ridge_big,
        cx_big + r_ridge_big, cy_big + r_ridge_big,
    ]
    bdraw.arc(bbox_ridge, start_deg, end_deg, fill=RIDGE, width=ridge_w * scale * ss)

    # Inner shadow arc (slip face) — slightly shorter sweep so it sits inside
    # the horns rather than running off them
    shadow_start = start_deg + 10
    shadow_end = end_deg - 10
    if r_shadow_big > 0 and shadow_end > shadow_start:
        bbox_shadow = [
            cx_big - r_shadow_big, cy_big - r_shadow_big,
            cx_big + r_shadow_big, cy_big + r_shadow_big,
        ]
        bdraw.arc(bbox_shadow, shadow_start, shadow_end,
                  fill=SHADOW, width=shadow_w * scale * ss)

    canvas = big.resize((size_final, size_final), Image.LANCZOS)

    # Offset from canvas top-left to crescent centre
    return canvas, size_final // 2, size_final // 2


def render_dune(scale):
    size = TILE_1X * scale
    img = Image.new("RGBA", (size, size), BG_WASH)

    for (cx, cy, radius, start_deg, end_deg) in CRESCENTS:
        crescent, ox, oy = make_crescent_canvas(radius, start_deg, end_deg, scale)
        anchor_x = cx * scale - ox
        anchor_y = cy * scale - oy
        paste_wrapped(img, crescent, anchor_x, anchor_y, scale)

    return img


def main():
    for scale, out_dir in ((1, SYMBOLS_1X), (2, SYMBOLS_2X)):
        img = render_dune(scale)
        out_path = out_dir / "dune.png"
        img.save(out_path, "PNG")
        print(f"wrote {out_path} ({img.size[0]}x{img.size[1]})")


if __name__ == "__main__":
    main()
