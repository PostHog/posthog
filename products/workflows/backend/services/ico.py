from io import BytesIO

from PIL import BmpImagePlugin, IcoImagePlugin, PngImagePlugin

from posthog.dataclasses import frozen
from posthog.models.uploaded_media import MAX_IMAGE_PIXELS, RejectedImage

ICO_SIGNATURE = b"\x00\x00\x01\x00"
ICO_FRAME_COUNT = slice(4, 6)
# Seven sizes in three color depths. Real icons stay well below this, and each frame costs a header parse.
MAX_ICO_FRAMES = 21


@frozen
class _Frame:
    index: int
    width: int
    height: int
    stored_pixels: int


def largest_ico_frame_as_png(content: bytes) -> bytes | None:
    """Convert an ICO to a PNG of its largest frame, or return None when ``content`` is not an ICO.

    Raises ``RejectedImage`` for a malformed ICO, more frames than ``MAX_ICO_FRAMES``, or a frame over the
    media library's pixel limit.
    Every frame is measured with Pillow's lazy parsers, which read headers only, before any frame decodes.
    """
    if not content.startswith(ICO_SIGNATURE):
        return None
    if int.from_bytes(content[ICO_FRAME_COUNT], "little") > MAX_ICO_FRAMES:
        raise RejectedImage.invalid()
    try:
        icon = IcoImagePlugin.IcoFile(BytesIO(content))
        first_index_of_offset = {entry.offset: index for index, entry in reversed(list(enumerate(icon.entry)))}
        frames = [_measure(icon, index) for index in first_index_of_offset.values()]
    except Exception as error:
        raise RejectedImage.invalid() from error
    if not frames or any(frame.stored_pixels > MAX_IMAGE_PIXELS for frame in frames):
        raise RejectedImage.invalid()
    largest = max(frames, key=lambda frame: (frame.width * frame.height, -frame.index))
    try:
        png = BytesIO()
        icon.frame(largest.index).save(png, format="PNG")
    except Exception as error:
        raise RejectedImage.invalid() from error
    return png.getvalue()


def _measure(icon: IcoImagePlugin.IcoFile, index: int) -> _Frame:
    icon.buf.seek(icon.entry[index].offset)
    if icon.buf.read(len(PngImagePlugin._MAGIC)) == PngImagePlugin._MAGIC:
        icon.buf.seek(icon.entry[index].offset)
        width, height = PngImagePlugin.PngImageFile(icon.buf).size
        return _Frame(index=index, width=width, height=height, stored_pixels=width * height)
    icon.buf.seek(icon.entry[index].offset)
    width, stored_height = BmpImagePlugin.DibImageFile(icon.buf).size
    # A BMP frame stores its image and its transparency mask, so it shows half its stored height.
    return _Frame(index=index, width=width, height=stored_height // 2, stored_pixels=width * stored_height)
