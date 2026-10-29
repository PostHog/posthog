"""Draw the development and preview app icons: the production icon with a labeled color band.

Run from products/mobile after a change to assets/icon.png or assets/adaptive-icon.png:
uv run --with pillow python scripts/make_variant_icons.py
"""

import argparse
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

MOBILE_ROOT = Path(__file__).resolve().parent.parent
ASSETS = MOBILE_ROOT / "assets"
DEFAULT_FONT = Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf")


@dataclass(frozen=True)
class Badge:
    variant: str
    label: str
    fill: str
    text: str


# Fills match the environment ribbon in src/ui/tokens.ts, so the icon and the in-app band agree.
BADGES = (
    Badge(variant="dev", label="DEV", fill="#F9BD2B", text="#1F1F1C"),
    Badge(variant="preview", label="PREVIEW", fill="#7A4DD6", text="#FFFFFF"),
)


@dataclass(frozen=True)
class Band:
    top: int
    bottom: int
    font_size: int


# The iOS mask rounds the corners only, so the band can run the full width near the bottom edge.
# An Android adaptive icon can be masked to a circle that shows only the central 2/3 of the layer,
# so its band sits just under the logomark, where that circle is still wide enough for the label.
ICON_BAND = Band(top=790, bottom=930, font_size=88)
ADAPTIVE_BAND = Band(top=740, bottom=840, font_size=64)


class VariantIconMaker:
    def __init__(self, font_path: Path) -> None:
        self.font_path = font_path

    def draw(self, source: Path, target: Path, band: Band, badge: Badge) -> None:
        image = Image.open(source).convert("RGB")
        scale = image.width / 1024
        draw = ImageDraw.Draw(image)
        top, bottom = round(band.top * scale), round(band.bottom * scale)
        draw.rectangle((0, top, image.width, bottom), fill=badge.fill)
        font = ImageFont.truetype(str(self.font_path), round(band.font_size * scale))
        draw.text(
            (image.width / 2, (top + bottom) / 2),
            badge.label,
            font=font,
            fill=badge.text,
            anchor="mm",
        )
        image.save(target, optimize=True)

    def run(self) -> None:
        for badge in BADGES:
            self.draw(ASSETS / "icon.png", ASSETS / f"icon-{badge.variant}.png", ICON_BAND, badge)
            self.draw(
                ASSETS / "adaptive-icon.png",
                ASSETS / f"adaptive-icon-{badge.variant}.png",
                ADAPTIVE_BAND,
                badge,
            )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--font", type=Path, default=DEFAULT_FONT, help="A bold TrueType font for the label.")
    args = parser.parse_args()
    VariantIconMaker(args.font).run()


if __name__ == "__main__":
    main()
