"""Contact sheets: many generated images in one labelled grid, for choosing and reviewing.

  python -m pipeline.contact refs        -> outputs/refs/contact_sheet.jpg
  python -m pipeline.contact keyframes   -> outputs/keyframes/contact_sheet.jpg
"""
from __future__ import annotations

import sys

from PIL import Image, ImageDraw, ImageFont

from .cache import Manifest
from .config import get_paths

CELL = 360
LABEL_H = 34


def _font(size: int) -> ImageFont.ImageFont:
    for name in ("arial.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def sheet(stage: str, columns: int = 4) -> str:
    paths = get_paths()
    manifest = Manifest(paths)
    entries = sorted(manifest.data["stages"].get(stage, {}).items())
    items = [(key, paths.abs(e["path"])) for key, e in entries if paths.abs(e["path"]).exists()]
    if not items:
        raise SystemExit(f"nothing generated yet for stage {stage!r}")
    rows = (len(items) + columns - 1) // columns
    grid = Image.new("RGB", (columns * CELL, rows * (CELL + LABEL_H)), (24, 22, 20))
    draw, font = ImageDraw.Draw(grid), _font(22)
    for n, (key, path) in enumerate(items):
        img = Image.open(path).convert("RGB")
        img.thumbnail((CELL, CELL))
        x, y = (n % columns) * CELL, (n // columns) * (CELL + LABEL_H)
        grid.paste(img, (x + (CELL - img.width) // 2, y + LABEL_H + (CELL - img.height) // 2))
        draw.text((x + 10, y + 6), key, fill=(240, 220, 180), font=font)
    out = paths.outputs / stage / "contact_sheet.jpg"
    grid.save(out, quality=88)
    return paths.rel(out)


if __name__ == "__main__":
    print(sheet(sys.argv[1] if len(sys.argv) > 1 else "refs"))
