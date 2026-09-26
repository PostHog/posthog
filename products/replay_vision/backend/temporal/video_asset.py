"""Read the rendered session video an ExportedAsset points at."""

from asgiref.sync import sync_to_async

from posthog.storage import object_storage

from products.exports.backend.models.exported_asset import ExportedAsset
from products.replay_vision.backend.temporal.errors import FailureKind, ScannerFailureError

# The AI gateway caps a request body at 16 MiB. Base64 grows the video by a third, and the preamble and the tool
# turns share the body. The upload activity sends a larger video through the Files API.
MAX_INLINE_VIDEO_BYTES = 9 * 1024 * 1024


async def read_asset_video_bytes(asset: ExportedAsset) -> bytes:
    video_bytes: bytes | None
    if asset.content:
        video_bytes = bytes(asset.content)
    elif asset.content_location:
        video_bytes = await sync_to_async(object_storage.read_bytes, thread_sensitive=False)(asset.content_location)
    else:
        raise ScannerFailureError(
            f"ExportedAsset {asset.id} has neither content nor content_location",
            kind=FailureKind.INTERNAL_ERROR,
        )
    if not video_bytes:
        raise ScannerFailureError(
            f"ExportedAsset {asset.id} produced empty video bytes", kind=FailureKind.INTERNAL_ERROR
        )
    return video_bytes
