"""Cut the default-skin hedgehog frames out of the @posthog/hedgehog-mode atlas for the home-screen widget.

Usage: python3 -I scripts/extract_hedgehog_sprites.py --source <path to @posthog/hedgehog-mode/assets>
"""

import json
import logging
import argparse
from pathlib import Path

from PIL import Image, ImageDraw

POSES: tuple[str, ...] = ("idle", "walk", "jump", "wave", "action", "fall")
SKIN = "default"
SCALE = 2
CELL = 80

MOBILE_ROOT = Path(__file__).resolve().parent.parent
ANDROID_DIR = MOBILE_ROOT / "modules/hedgehog-widget/android/src/main/res/drawable-nodpi"
IOS_CATALOG = MOBILE_ROOT / "targets/HedgehogWidget/Assets.xcassets"
XCODE_INFO: dict[str, object] = {"author": "xcode", "version": 1}

logger = logging.getLogger(__name__)


class SpriteExtractor:
    def __init__(self, source: Path) -> None:
        atlas_json = source / "sprites.json"
        atlas_png = source / "sprites.png"
        for path in (atlas_json, atlas_png):
            if not path.is_file():
                raise SystemExit(f"Missing atlas file: {path}")
        self.atlas: dict = json.loads(atlas_json.read_text())
        self.sheet = Image.open(atlas_png).convert("RGBA")

    def frames_for(self, pose: str) -> list[Image.Image]:
        key = f"skins/{SKIN}/{pose}/tile"
        names = self.atlas["animations"].get(key)
        if not names:
            raise SystemExit(f'Pose "{pose}" is missing from the atlas (no animation "{key}")')
        frames: list[Image.Image] = []
        for name in names:
            entry = self.atlas["frames"][name]
            # Rotated or trimmed frames need extra un-packing that this script does not do,
            # so stop instead of writing a wrong crop.
            if entry["rotated"] or entry["trimmed"]:
                raise SystemExit(f"Frame {name} is rotated or trimmed; this script handles only plain frames")
            rect = entry["frame"]
            frames.append(self.sheet.crop((rect["x"], rect["y"], rect["x"] + rect["w"], rect["y"] + rect["h"])))
        return frames


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, indent=4) + "\n")


def write_frame(pose: str, index: int, frame: Image.Image) -> None:
    name = f"hog_{pose}_{index:02d}"
    # Nearest-neighbour keeps the pixel art crisp; any smoothing filter blurs the outlines.
    big = frame.resize((frame.width * SCALE, frame.height * SCALE), Image.Resampling.NEAREST)

    big.save(ANDROID_DIR / f"{name}.png", optimize=True)
    # RemoteViews cannot flip an ImageView, so Android needs a pre-mirrored copy for facing left.
    big.transpose(Image.Transpose.FLIP_LEFT_RIGHT).save(ANDROID_DIR / f"{name}_l.png", optimize=True)

    imageset = IOS_CATALOG / f"{name}.imageset"
    imageset.mkdir(parents=True, exist_ok=True)
    big.save(imageset / f"{name}.png", optimize=True)
    write_json(
        imageset / "Contents.json",
        {"images": [{"filename": f"{name}.png", "idiom": "universal", "scale": "1x"}], "info": XCODE_INFO},
    )


def write_contact_sheet(frames_by_pose: dict[str, list[Image.Image]], path: Path) -> None:
    label_width = 70
    columns = max(len(frames) for frames in frames_by_pose.values())
    sheet = Image.new("RGBA", (label_width + columns * CELL, len(frames_by_pose) * CELL), (235, 235, 235, 255))
    draw = ImageDraw.Draw(sheet)
    for row, (pose, frames) in enumerate(frames_by_pose.items()):
        top = row * CELL
        draw.text((6, top + CELL // 2 - 6), pose, fill=(0, 0, 0, 255))
        for column, frame in enumerate(frames):
            left = label_width + column * CELL
            draw.rectangle((left, top, left + CELL - 1, top + CELL - 1), outline=(200, 200, 200, 255))
            sheet.alpha_composite(frame, (left, top))
            draw.text((left + 2, top + 2), f"{column:02d}", fill=(150, 150, 150, 255))
    path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True, help="Directory with sprites.json and sprites.png")
    parser.add_argument("--contact-sheet", type=Path, help="Optional PNG path for a sheet of every frame")
    args = parser.parse_args()

    extractor = SpriteExtractor(args.source)
    frames_by_pose = {pose: extractor.frames_for(pose) for pose in POSES}

    ANDROID_DIR.mkdir(parents=True, exist_ok=True)
    IOS_CATALOG.mkdir(parents=True, exist_ok=True)
    catalog_contents = IOS_CATALOG / "Contents.json"
    if not catalog_contents.exists():
        write_json(catalog_contents, {"info": XCODE_INFO})

    for pose, frames in frames_by_pose.items():
        for index, frame in enumerate(frames):
            write_frame(pose, index, frame)
        logger.info("%s: %d frames", pose, len(frames))

    if args.contact_sheet:
        write_contact_sheet(frames_by_pose, args.contact_sheet)
        logger.info("contact sheet: %s", args.contact_sheet)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    main()
