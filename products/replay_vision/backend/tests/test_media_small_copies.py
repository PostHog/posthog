import io
from datetime import timedelta

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.test import SimpleTestCase
from django.utils import timezone

from parameterized import parameterized
from PIL import Image

from posthog.models.utils import uuid7

from products.exports.backend.models.exported_asset import ExportedAsset
from products.replay_vision.backend.media_small_copies import (
    backfill_small_copies,
    media_missing_small_copies,
    shrink_frame,
)
from products.replay_vision.backend.models.replay_observation import (
    ObservationStatus,
    ObservationTrigger,
    ReplayObservation,
)
from products.replay_vision.backend.models.replay_observation_media import ReplayObservationMedia
from products.replay_vision.backend.models.replay_scanner import ReplayScanner, ScannerModel, ScannerType
from products.replay_vision.backend.tests.helpers import snapshot_for


def _png(width: int, height: int) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (width, height), (40, 120, 200)).save(out, format="PNG")
    return out.getvalue()


class TestShrinkPng(SimpleTestCase):
    @parameterized.expand(
        [
            ("desktop_frame_scales_to_an_even_height", 1280, 689, (480, 258)),
            ("phone_frame_is_never_upscaled", 336, 688, (336, 688)),
        ]
    )
    def test_shrink(self, _name: str, width: int, height: int, expected: tuple[int, int]) -> None:
        with Image.open(io.BytesIO(shrink_frame(_png(width, height)))) as image:
            assert (image.format, image.size) == ("WEBP", expected)


class TestBackfillSmallCopies(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        scanner = ReplayScanner.objects.create(
            team=self.team,
            name="Checkout monitor",
            scanner_type=ScannerType.MONITOR,
            scanner_config={"prompt": "did the user check out?"},
            model=ScannerModel.GEMINI_3_8_FLASH,
        )
        self.observation = ReplayObservation.objects.create(
            scanner=scanner,
            team=self.team,
            session_id=f"s-{uuid7()}",
            status=ObservationStatus.SUCCEEDED,
            completed_at=timezone.now(),
            scanner_snapshot=snapshot_for(scanner),
            triggered_by=ObservationTrigger.SCHEDULE,
        )

    def _media(self, position: int, *, rendered: bool = True, expired: bool = False) -> ReplayObservationMedia:
        asset = ExportedAsset.objects.create(
            team=self.team,
            export_format=ExportedAsset.ExportFormat.PNG,
            export_context={"observation_id": str(self.observation.id), "media_kind": "chapter"},
            content_location=f"replay-vision/media/team-{self.team.id}/{self.observation.id}/{position}.png"
            if rendered
            else None,
            expires_after=timezone.now() + (timedelta(seconds=-1) if expired else timedelta(days=60)),
            is_system=True,
        )
        return ReplayObservationMedia.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            observation=self.observation,
            asset=asset,
            kind=ReplayObservationMedia.Kind.CHAPTER,
            position=position,
            video_start_ms=1000,
        )

    def test_it_links_a_small_copy_to_each_servable_frame_once(self) -> None:
        servable = self._media(0)
        self._media(1, rendered=False)
        self._media(2, expired=True)

        with (
            patch("products.replay_vision.backend.media_small_copies.object_storage.read_bytes") as read,
            patch("products.replay_vision.backend.media_small_copies.object_storage.write") as write,
        ):
            read.return_value = _png(1280, 688)

            assert media_missing_small_copies(self.team.id).count() == 1

            result = backfill_small_copies(self.team.id)
            again = backfill_small_copies(self.team.id)

        assert (result.candidates, result.created, result.failed) == (1, 1, 0)
        assert again.candidates == 0
        assert write.call_count == 1
        small_location, small_bytes = write.call_args.args
        assert small_location == (servable.asset.content_location or "").removesuffix(".png") + "-small.webp"
        with Image.open(io.BytesIO(small_bytes)) as image:
            assert image.width == 480

        servable.refresh_from_db()
        assert servable.small_asset is not None
        assert servable.small_asset.content_location == small_location
        assert servable.small_asset.expires_after == servable.asset.expires_after
        assert servable.small_asset.export_format == ExportedAsset.ExportFormat.WEBP

    def test_a_copy_written_while_its_observation_is_deleted_is_removed(self) -> None:
        media = self._media(0)
        small_location = (media.asset.content_location or "").removesuffix(".png") + "-small.webp"

        with (
            patch(
                "products.replay_vision.backend.media_small_copies.object_storage.read_bytes",
                return_value=_png(1280, 688),
            ),
            patch(
                "products.replay_vision.backend.media_small_copies.object_storage.write",
                side_effect=lambda *_: self.observation.delete(),
            ),
            patch("products.replay_vision.backend.media_small_copies.object_storage.delete") as delete,
        ):
            result = backfill_small_copies(self.team.id)

        assert result.created == 0
        delete.assert_called_once_with(small_location)
