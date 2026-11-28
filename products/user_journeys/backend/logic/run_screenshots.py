"""Storing step screenshots and comparing them with the baseline run's.

Screenshots go to object storage under their content hash, inside a per-team folder, so a step that
renders the same image as before costs no new object and no comparison.
"""

from __future__ import annotations

from typing import Protocol

from django.conf import settings

from blake3 import blake3
from pixelhog import Comparison

from posthog.dataclasses import frozen
from posthog.storage import object_storage

from ..facade.enums import JourneyVisualChange

# A pixel counts as changed when its color differs by more than this share of the color range,
# which keeps font antialiasing noise out of the count.
PIXEL_DIFF_THRESHOLD = 0.1
# A step counts as visually changed when more than this percentage of its pixels changed.
VISUAL_CHANGE_THRESHOLD_PERCENT = 0.1
SCREENSHOT_URL_EXPIRATION_SECONDS = 60 * 60
_FOLDER = "user_journeys"


class ScreenshotStorageUnavailableError(Exception):
    pass


def screenshot_hash(content: bytes) -> str:
    return blake3(content).hexdigest()


class ScreenshotStore(Protocol):
    def put(self, team_id: int, content: bytes) -> str:
        """Store a PNG and return its content hash."""
        ...

    def get(self, team_id: int, content_hash: str) -> bytes | None: ...

    def url(self, team_id: int, content_hash: str) -> str | None:
        """A short-lived URL the frontend can load the image from, or None when there is none."""
        ...


class ObjectStorageScreenshotStore:
    def _key(self, team_id: int, content_hash: str) -> str:
        # The hash prefix spreads objects across S3 partitions.
        return f"{_FOLDER}/{team_id}/{content_hash[:2]}/{content_hash}.png"

    def put(self, team_id: int, content: bytes) -> str:
        if not settings.OBJECT_STORAGE_ENABLED:
            raise ScreenshotStorageUnavailableError("Object storage isn't set up, so screenshots can't be stored.")
        content_hash = screenshot_hash(content)
        key = self._key(team_id, content_hash)
        if object_storage.head_object(file_key=key) is None:
            object_storage.write(key, content, extras={"ContentType": "image/png"})
        return content_hash

    def get(self, team_id: int, content_hash: str) -> bytes | None:
        if not settings.OBJECT_STORAGE_ENABLED:
            return None
        return object_storage.read_bytes(self._key(team_id, content_hash), missing_ok=True)

    def url(self, team_id: int, content_hash: str) -> str | None:
        if not settings.OBJECT_STORAGE_ENABLED:
            return None
        return object_storage.get_presigned_url(
            file_key=self._key(team_id, content_hash), expiration=SCREENSHOT_URL_EXPIRATION_SECONDS
        )


@frozen
class ScreenshotDiff:
    diff_percentage: float
    diff_image: bytes | None


def diff_screenshots(baseline: bytes, current: bytes) -> ScreenshotDiff:
    """Compare two PNGs. Different sizes are padded to the larger one, so the padding counts as changed."""
    comparison = Comparison(baseline, current)
    total_pixels = comparison.width * comparison.height
    changed_pixels = comparison.diff_count(threshold=PIXEL_DIFF_THRESHOLD)
    if changed_pixels == 0 or total_pixels == 0:
        return ScreenshotDiff(diff_percentage=0.0, diff_image=None)
    return ScreenshotDiff(
        diff_percentage=round(changed_pixels / total_pixels * 100, 4),
        diff_image=comparison.diff_image(threshold=PIXEL_DIFF_THRESHOLD, alpha=0.1),
    )


@frozen
class StoredScreenshot:
    screenshot_hash: str
    # Set only when the screenshot was compared with the baseline's.
    baseline_screenshot_hash: str | None
    diff_screenshot_hash: str | None
    diff_percentage: float | None
    visual_change: JourneyVisualChange


def store_and_compare(
    store: ScreenshotStore, team_id: int, screenshot: bytes, baseline_hash: str | None
) -> StoredScreenshot:
    """Store a step's screenshot and compare it with the baseline step's, when that image still exists."""
    screenshot_hash = store.put(team_id, screenshot)
    if baseline_hash == screenshot_hash:
        return StoredScreenshot(
            screenshot_hash=screenshot_hash,
            baseline_screenshot_hash=baseline_hash,
            diff_screenshot_hash=None,
            diff_percentage=0.0,
            visual_change=JourneyVisualChange.UNCHANGED,
        )
    baseline_image = store.get(team_id, baseline_hash) if baseline_hash is not None else None
    if baseline_image is None:
        return StoredScreenshot(
            screenshot_hash=screenshot_hash,
            baseline_screenshot_hash=None,
            diff_screenshot_hash=None,
            diff_percentage=None,
            visual_change=JourneyVisualChange.NEW,
        )
    diff = diff_screenshots(baseline_image, screenshot)
    return StoredScreenshot(
        screenshot_hash=screenshot_hash,
        baseline_screenshot_hash=baseline_hash,
        diff_screenshot_hash=store.put(team_id, diff.diff_image) if diff.diff_image is not None else None,
        diff_percentage=diff.diff_percentage,
        visual_change=(
            JourneyVisualChange.CHANGED
            if diff.diff_percentage > VISUAL_CHANGE_THRESHOLD_PERCENT
            else JourneyVisualChange.UNCHANGED
        ),
    )
