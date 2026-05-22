#!/usr/bin/env python3
"""Generate wetland pattern sprites (marsh, wetland, reedbed) at 1x and 2x."""

from PIL import Image, ImageDraw
from pathlib import Path

SYMBOLS_1X = Path("/home/jonlynch/OpenTopoMap/vector/maplibregljs/otm_symbols")
SYMBOLS_2X = Path("/home/jonlynch/OpenTopoMap/vector/maplibregljs/otm_symbols_2x")

TILE = 36  # 1x tile size


def new_tile(scale, bg=(0, 0, 0, 0)):
    size = TILE * scale
    return Image.new("RGBA", (size, size), bg)


def in_bounds(scale, *points):
    size = TILE * scale
    for (x, y) in points:
        if x < 0 or y < 0 or x > size or y > size:
            return False
    return True


def draw_line(draw, scale, p1, p2, colour, width=1):
    """Draw a line scaled, clipped to tile bounds."""
    size = TILE * scale
    x1, y1 = p1[0] * scale, p1[1] * scale
    x2, y2 = p2[0] * scale, p2[1] * scale
    # simple bounds check — skip if both endpoints out of bounds
    if (x1 < 0 or x1 > size or y1 < 0 or y1 > size or
            x2 < 0 or x2 > size or y2 < 0 or y2 > size):
        return
    draw.line([(x1, y1), (x2, y2)], fill=colour, width=width * scale)


def render_marsh(scale):
    img = new_tile(scale)
    draw = ImageDraw.Draw(img)
    blue = (60, 120, 195, 255)
    rows = [
        ([8, 20, 32], 7),
        ([14, 26], 16),
        ([8, 20, 32], 25),
        ([14, 26], 34),
    ]
    size = TILE * scale
    for xs, cy in rows:
        for cx in xs:
            # horizontal tick (cx-3, cy) -> (cx+3, cy) width=2
            x1, y1 = (cx - 3) * scale, cy * scale
            x2, y2 = (cx + 3) * scale, cy * scale
            if 0 <= y1 <= size:
                draw.line([(x1, y1), (x2, y2)], fill=blue, width=2 * scale)
            # vertical stem (cx, cy+2) -> (cx, cy+5) width=1
            sx1, sy1 = cx * scale, (cy + 2) * scale
            sx2, sy2 = cx * scale, (cy + 5) * scale
            if 0 <= sx1 <= size and sy2 <= size:
                draw.line([(sx1, sy1), (sx2, sy2)], fill=blue, width=1 * scale)
    return img


def render_wetland(scale):
    img = new_tile(scale, bg=(140, 200, 235, 35))
    draw = ImageDraw.Draw(img)
    dash_colour = (52, 115, 192, 215)
    rows = [
        ([7, 22], 6),
        ([14, 29], 13),
        ([7, 22], 20),
        ([14, 29], 27),
        ([7, 22], 34),
    ]
    size = TILE * scale
    for xs, cy in rows:
        for cx in xs:
            x1 = (cx - 4) * scale
            x2 = (cx + 4) * scale
            y = cy * scale
            if y < 0 or y > size:
                continue
            # clip horizontally
            x1c = max(0, x1)
            x2c = min(size, x2)
            if x2c <= x1c:
                continue
            draw.line([(x1c, y), (x2c, y)], fill=dash_colour, width=1 * scale)
    return img


def render_reedbed(scale):
    img = new_tile(scale, bg=(120, 195, 155, 40))
    draw = ImageDraw.Draw(img)
    green = (37, 160, 52, 255)
    tufts = [(9, 28), (22, 28), (15, 19), (29, 19), (9, 10), (22, 10)]
    for cx, by in tufts:
        # centre: (cx, by) -> (cx, by-6)
        draw_line(draw, scale, (cx, by), (cx, by - 6), green, width=1)
        # left: (cx, by) -> (cx-3, by-5)
        draw_line(draw, scale, (cx, by), (cx - 3, by - 5), green, width=1)
        # right: (cx, by) -> (cx+3, by-5)
        draw_line(draw, scale, (cx, by), (cx + 3, by - 5), green, width=1)
        # cap: (cx-2, by-6) -> (cx+2, by-6)
        draw_line(draw, scale, (cx - 2, by - 6), (cx + 2, by - 6), green, width=1)
    return img


RENDERERS = {
    "marsh": render_marsh,
    "wetland": render_wetland,
    "reedbed": render_reedbed,
}


def main():
    for name, fn in RENDERERS.items():
        for scale, out_dir in ((1, SYMBOLS_1X), (2, SYMBOLS_2X)):
            img = fn(scale)
            out_path = out_dir / f"{name}.png"
            img.save(out_path, "PNG")
            print(f"wrote {out_path} ({img.size[0]}x{img.size[1]})")


if __name__ == "__main__":
    main()
