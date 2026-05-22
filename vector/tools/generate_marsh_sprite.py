#!/usr/bin/env python3
"""Generate marsh pattern sprite at 1x (36x36) and 2x (72x72).

Marsh visual language (OS / military topographic convention):
  - Open shallow water with emergent herbaceous plants (sedges, rushes, grasses)
  - Rows of short horizontal blue strokes, each with a short vertical tick
    descending from the centre — a row of ⊤ shapes
  - Faint cool-blue background wash so the patch reads as wet
  - Two blues: a medium blue for the horizontal water-surface bar, a slightly
    cooler/lighter blue for the vertical emergent stem
  - Rows are staggered so the eye does not pick out vertical lines of marks

Tileable: every mark is painted at nine wrapped offsets ({-tile, 0, +tile} in
both axes) so any pixel that crosses an edge re-appears on the opposite edge
and the repeat is seamless.

Drawn natively at each scale (1×: 36×36, 2×: 72×72) — geometry is specified in
1× coordinates and scaled up to the target resolution, with stroke widths
expressed in scale-aware pixels so the 2× version is not a blurred upscale of
the 1× version.

Must read distinct from:
  - wetland: plain horizontal dashes, no stems
  - reedbed: green reed fans
  - swamp: green tufts
  - bog: dark tannin pools
"""

from PIL import Image, ImageDraw
from pathlib import Path

SYMBOLS_1X = Path("/home/jonlynch/OpenTopoMap/vector/maplibregljs/otm_symbols")
SYMBOLS_2X = Path("/home/jonlynch/OpenTopoMap/vector/maplibregljs/otm_symbols_2x")

TILE_1X = 36

# Colour palette (RGBA)
# Pale cool-blue wash — communicates "watery ground" beneath the marks
BG_WASH = (100, 155, 210, 55)
# Horizontal tick — medium blue, the water-surface bar
TICK_BLUE = (45, 105, 175, 230)
# Vertical stem — slightly lighter / cooler, the emergent plant
STEM_BLUE = (60, 130, 185, 200)

# Marks in 1× coordinates.
# Four staggered rows, three marks per "wide" row and two per "narrow" offset
# row. Spacing chosen so the 36-px tile wraps seamlessly: x positions on the
# wide rows are 6, 18, 30 (gap 12, tile 36 — wraps cleanly); offset rows are
# 12, 24 (centred between the wide-row marks for visual stagger).
ROWS_1X = [
    ([6, 18, 30], 5),    # wide row, near top
    ([12, 24], 13),      # offset row
    ([6, 18, 30], 21),   # wide row
    ([12, 24], 29),      # offset row, leaves room for stem before wrap
]

# Mark geometry in 1× pixels (will be scaled).
TICK_HALF_WIDTH_1X = 3   # horizontal stroke extends ±3 → 6 px wide at 1×
TICK_THICKNESS_1X = 1.5  # bar thickness (rounded up at render time)
STEM_LENGTH_1X = 4       # vertical stem length below the bar
STEM_THICKNESS_1X = 1    # stem thickness


def paste_wrapped(base, sprite, anchor_x, anchor_y, scale):
    """Paste sprite onto base at nine wrapped offsets for seamless tiling."""
    tile = TILE_1X * scale
    for dy in (-tile, 0, tile):
        for dx in (-tile, 0, tile):
            base.alpha_composite(sprite, (anchor_x + dx, anchor_y + dy))


def make_mark_canvas(scale):
    """Build a transparent canvas containing one ⊤ mark.

    Returns (canvas, ox, oy) where (ox, oy) is the location on the canvas that
    corresponds to the mark's anchor — the centre of the horizontal bar.
    """
    tick_half = TICK_HALF_WIDTH_1X * scale
    tick_thick = max(1, round(TICK_THICKNESS_1X * scale))
    stem_len = STEM_LENGTH_1X * scale
    stem_thick = max(1, round(STEM_THICKNESS_1X * scale))

    pad = 1  # small padding so anti-aliased edges aren't clipped
    w = tick_half * 2 + pad * 2 + 1
    # Height: bar (centred on anchor) + stem extending downward
    h = tick_thick + stem_len + pad * 2 + 1

    ox = tick_half + pad
    oy = pad + tick_thick // 2  # anchor at vertical centre of the bar

    canvas = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)

    # Horizontal bar — drawn as a filled rectangle so thickness is exact
    bar_top = oy - tick_thick // 2
    bar_bot = bar_top + tick_thick - 1
    draw.rectangle(
        [ox - tick_half, bar_top, ox + tick_half, bar_bot],
        fill=TICK_BLUE,
    )

    # Vertical stem — drops from just below the bar
    stem_top = bar_bot + 1
    stem_bot = stem_top + stem_len - 1
    stem_left = ox - stem_thick // 2
    stem_right = stem_left + stem_thick - 1
    draw.rectangle(
        [stem_left, stem_top, stem_right, stem_bot],
        fill=STEM_BLUE,
    )

    return canvas, ox, oy


def render_marsh(scale):
    size = TILE_1X * scale
    img = Image.new("RGBA", (size, size), BG_WASH)

    mark, ox, oy = make_mark_canvas(scale)

    for (xs, cy) in ROWS_1X:
        for cx in xs:
            anchor_x = cx * scale - ox
            anchor_y = cy * scale - oy
            paste_wrapped(img, mark, anchor_x, anchor_y, scale)

    return img


def main():
    for scale, out_dir in ((1, SYMBOLS_1X), (2, SYMBOLS_2X)):
        img = render_marsh(scale)
        out_path = out_dir / "marsh.png"
        img.save(out_path, "PNG")
        print(f"wrote {out_path} ({img.size[0]}x{img.size[1]})")


if __name__ == "__main__":
    main()
