"""Prepare bundled widget illustrations from https://brand.posthog.com/hoggies.

Download the PNGs into a directory, naming wizard-1.png as wizard.png, then run:
python scripts/prepare_widget_hoggies.py --source <directory>
"""

import json
import argparse
from pathlib import Path

from PIL import Image

MOBILE_ROOT = Path(__file__).resolve().parent.parent
ANDROID_DIR = MOBILE_ROOT / "modules/hedgehog-widget/android/src/main/res/drawable-nodpi"
IOS_CATALOG = MOBILE_ROOT / "targets/HedgehogWidget/Assets.xcassets"
FACES_LEFT: dict[str, bool] = {
    "coffee-cup": True,
    "party": True,
    "wizard": True,
    "explorer": False,
    "superhero": False,
    "reading": True,
    "float": True,
}


class WidgetHoggiePreparer:
    def __init__(self, source: Path) -> None:
        self.source = source

    def prepare(self) -> None:
        for slug, faces_left in FACES_LEFT.items():
            with Image.open(self.source / f"{slug}.png") as source:
                image = source.convert("RGBA")
            bounds = image.getbbox()
            if bounds is None:
                raise ValueError(f"Empty illustration: {slug}")
            image = image.crop(bounds)
            if faces_left:
                image = image.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
            image.thumbnail((240, 272), Image.Resampling.LANCZOS)
            cell = Image.new("RGBA", (320, 320))
            cell.alpha_composite(image, ((320 - image.width) // 2, 312 - image.height))
            name = f"hoggie_{slug.replace('-', '_')}"
            cell.save(ANDROID_DIR / f"{name}.png", optimize=True)
            cell.transpose(Image.Transpose.FLIP_LEFT_RIGHT).save(ANDROID_DIR / f"{name}_l.png", optimize=True)
            imageset = IOS_CATALOG / f"{name}.imageset"
            imageset.mkdir(parents=True, exist_ok=True)
            cell.save(imageset / f"{name}.png", optimize=True)
            (imageset / "Contents.json").write_text(
                json.dumps(
                    {
                        "images": [{"filename": f"{name}.png", "idiom": "universal", "scale": "1x"}],
                        "info": {"author": "xcode", "version": 1},
                    },
                    indent=4,
                )
                + "\n"
            )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    args = parser.parse_args()
    WidgetHoggiePreparer(args.source).prepare()


if __name__ == "__main__":
    main()
