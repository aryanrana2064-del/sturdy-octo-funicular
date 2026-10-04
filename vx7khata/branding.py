"""SHREEJI BOXES / SJB branding shared by every PDF and Excel export.

* ``SHREEJI BOXES`` is the brand name shown in headers and footers.
* ``SJB`` is the short mark used for the large, light background watermark.
* No website is ever printed unless one was configured (Backup & Settings).
"""
from __future__ import annotations

import io
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

BRAND_NAME = "SHREEJI BOXES"
BRAND_MARK = "SJB"

NAVY = "#14284B"          # brand name, monogram, key totals
TABLE_NAVY = "#1F3A5F"    # table header (same as the original reports)
GOLD = "#B08D3C"          # accent rule and monogram letters
GOLD_TINT = "#F6F0E0"     # light fill for total rows
WATERMARK_TINT = "#EFE8D8"  # PDF watermark: gold at roughly 20% on white

_FONT_BOLD = Path(__file__).resolve().parent / "assets" / "fonts" / "DejaVuSans-Bold.ttf"


def _font(size: int):
    try:
        return ImageFont.truetype(str(_FONT_BOLD), size)
    except OSError:  # bundled font missing: fall back to Pillow's built-in font
        try:
            return ImageFont.load_default(size)
        except TypeError:  # Pillow < 10.1
            return ImageFont.load_default()


@lru_cache(maxsize=8)
def watermark_png(width: int, height: int, font_size: int, tint: tuple[int, int, int], angle: int = 30) -> bytes:
    """A PNG with a large diagonal SJB in a very light tint on white.

    The white background is deliberate: Excel draws header pictures *behind* the cells, so
    nothing is hidden, and it avoids the black-box transparency problem of some printers.
    """
    layer = Image.new("RGBA", (width * 2, height * 2), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    font = _font(font_size)
    left, top, right, bottom = draw.textbbox((0, 0), BRAND_MARK, font=font)
    x = (layer.width - (right - left)) / 2 - left
    y = (layer.height - (bottom - top)) / 2 - top
    draw.text((x, y), BRAND_MARK, font=font, fill=tint + (255,))
    layer = layer.rotate(angle, resample=Image.BICUBIC)
    ox, oy = (layer.width - width) // 2, (layer.height - height) // 2
    layer = layer.crop((ox, oy, ox + width, oy + height))
    image = Image.new("RGB", (width, height), (255, 255, 255))
    image.paste(layer, mask=layer.split()[3])
    out = io.BytesIO()
    image.save(out, format="PNG", dpi=(96, 96), optimize=True)
    return out.getvalue()


def excel_print_watermark() -> bytes:
    """Picture placed in the worksheet page header: prints behind the data on every page."""
    return watermark_png(900, 600, 330, (236, 228, 208))


def excel_screen_background() -> bytes:
    """Tiled sheet background for on-screen viewing (very light, never printed)."""
    return watermark_png(1200, 800, 360, (243, 238, 224))
