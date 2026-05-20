#!/usr/bin/env python3
"""Generate generic wetland pattern sprite at 1x (36x36) and 2x (72x72).

Generic wetland visual language:
  - Catch-all for "permanently or seasonally wet ground" where the subtype
    (bog, marsh, reedbed, swamp) is unknown or unspecified
  - Open shallow water surface disturbed by scattered emergent vegetation —
    a mix of water and plant matter, neither purely aquatic nor purely
    vegetated
  - Short horizontal dashes arranged in offset rows, with slight length
    variation per mark and two shades of blue to suggest the mixed,
    less-defined character of generic wetland
  - Muted blue-grey background wash — more murky and less crisp than marsh's
    cool clear blue, communicating ambiguous wet ground

Tileable: every mark is painted at nine wrapped offsets ({-tile, 0, +tile} in
both axes) so any pixel that crosses an edge re-appears on the opposite edge
and the repeat is seamless.

Drawn natively at each scale (1×: 36×36, 2×: 72×72) — geometry is specified in
1× coordinates and scaled up to the target resolution, with stroke widths
expressed in scale-aware pixels so the 2× version is not a blurred upscale of
the 1× version.

Must read distinct from:
  - marsh:   precise ⊤ tick marks with vertical stems in clean blue
  - reedbed: green reed fans
  - swamp:   green tufts
  - bog:     dark tannin pools
"""

from PIL import Image, ImageDraw
from pathlib import Path

SYMBOLS_1X = Path("/home/jonlynch/OpenTopoMap/vector/maplibregljs/otm_symbols")
SYMBOLS_2X = Path("/home/jonlynch/OpenTopoMap/vector/maplibregljs/otm_symbols_2x")

TILE_1X = 36

# Colour palette (RGBA)
# Muted blue-grey wash — murkier and more ambiguous than marsh's clean wash
BG_WASH = (105, 148, 185, 60)
# Primary dash — medium-dark blue, the "water" element
DASH_PRIMARY = (55, 110, 168, 210)
# Secondary dash — slightly lighter blue, the "vegetation shadow on water" element
DASH_SECONDARY = (75, 138, 178, 170)

# Marks in 1× coordinates: list of (cx, cy, half_width, colour_key).
# Five staggered rows, alternating 3-mark and 2-mark rows. Spacings chosen so
# the 36-px tile wraps cleanly. Slight per-mark half-width variation breaks
# regularity. Colour key: "P" = primary, "S" = secondary (every third mark or
# so is secondary to break up the rhythm).
MARKS_1X = [
    # Row 1 (wide, near top) — cy=4
    (6,  4, 3, "P"),
    (18, 4, 3, "S"),
    (30, 4, 4, "P"),
    # Row 2 (offset) — cy=11
    (12, 11, 3, "P"),
    (24, 11, 4, "S"),
    # Row 3 (wide) — cy=18
    (6,  18, 4, "S"),
    (18, 18, 3, "P"),
    (30, 18, 3, "P"),
    # Row 4 (offset) — cy=25
    (12, 25, 3, "P"),
    (24, 25, 4, "S"),
    # Row 5 (wide, near bottom) — cy=32
    (6,  32, 3, "P"),
    (18, 32, 4, "P"),
    (30, 32, 3, "S"),
]

# Dash geometry in 1× pixels.
DASH_THICKNESS_1X = 1  # 1 px at 1×, 2 px at 2× — matches the spec ("2 px at 2×")


def paste_wrapped(base, sprite, anchor_x, anchor_y, scale):
    """Paste sprite onto base at nine wrapped offsets for seamless tiling."""
    tile = TILE_1X * scale
    for dy in (-tile, 0, tile):
        for dx in (-tile, 0, tile):
            base.alpha_composite(sprite, (anchor_x + dx, anchor_y + dy))


def make_dash_canvas(half_width_1x, colour, scale):
    """Build a transparent canvas containing one horizontal dash.

    Returns (canvas, ox, oy) where (ox, oy) is the location on the canvas that
    corresponds to the dash's anchor — its geometric centre.
    """
    half = half_width_1x * scale
    thick = max(1, round(DASH_THICKNESS_1X * scale))

    pad = 1  # padding so edges aren't clipped
    w = half * 2 + pad * 2 + 1
    h = thick + pad * 2

    ox = half + pad
    oy = pad + thick // 2

    canvas = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)

    bar_top = oy - thick // 2
    bar_bot = bar_top + thick - 1
    draw.rectangle(
        [ox - half, bar_top, ox + half, bar_bot],
        fill=colour,
    )

    return canvas, ox, oy


def render_wetland(scale):
    size = TILE_1X * scale
    img = Image.new("RGBA", (size, size), BG_WASH)

    for (cx, cy, half_width, colour_key) in MARKS_1X:
        colour = DASH_PRIMARY if colour_key == "P" else DASH_SECONDARY
        mark, ox, oy = make_dash_canvas(half_width, colour, scale)
        anchor_x = cx * scale - ox
        anchor_y = cy * scale - oy
        paste_wrapped(img, mark, anchor_x, anchor_y, scale)

    return img


def main():
    for scale, out_dir in ((1, SYMBOLS_1X), (2, SYMBOLS_2X)):
        img = render_wetland(scale)
        out_path = out_dir / "wetland.png"
        img.save(out_path, "PNG")
        print(f"wrote {out_path} ({img.size[0]}x{img.size[1]})")


if __name__ == "__main__":
    main()
