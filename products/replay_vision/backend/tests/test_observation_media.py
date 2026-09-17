from datetime import timedelta
from typing import Any

from posthog.test.base import BaseTest

from django.conf import settings
from django.utils import timezone

from asgiref.sync import async_to_sync
from parameterized import parameterized

from posthog.models.utils import uuid7

from products.exports.backend.models.exported_asset import ExportedAsset
from products.replay_vision.backend.media_expiry import expire_media_for_observations, expire_media_for_scanner
from products.replay_vision.backend.models.replay_observation import (
    ObservationStatus,
    ObservationTrigger,
    ReplayObservation,
)
from products.replay_vision.backend.models.replay_observation_media import ReplayObservationMedia
from products.replay_vision.backend.models.replay_scanner import ReplayScanner, ScannerModel, ScannerType
from products.replay_vision.backend.temporal.activities.observation_media import (
    finalize_observation_thumbnail_activity,
    prepare_observation_thumbnail_activity,
)
from products.replay_vision.backend.temporal.media_types import (
    ExtractThumbnailActivityOutput,
    FinalizeObservationThumbnailInputs,
    ObservationMediaInputs,
    PrepareObservationThumbnailInputs,
)
from products.replay_vision.backend.tests.helpers import snapshot_for


class TestObservationMedia(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.scanner = ReplayScanner.objects.create(
            team=self.team,
            name="Checkout monitor",
            scanner_type=ScannerType.MONITOR,
            scanner_config={"prompt": "did the user check out?"},
            model=ScannerModel.GEMINI_3_8_FLASH,
        )
        self.session_id = f"s-{uuid7()}"
        self.observation = ReplayObservation.objects.create(
            scanner=self.scanner,
            team=self.team,
            session_id=self.session_id,
            status=ObservationStatus.SUCCEEDED,
            completed_at=timezone.now(),
            scanner_snapshot=snapshot_for(self.scanner),
            triggered_by=ObservationTrigger.SCHEDULE,
        )
        self.analysis_asset = ExportedAsset.objects.create(
            team=self.team,
            export_format=ExportedAsset.ExportFormat.MP4,
            export_context={
                "session_recording_id": self.session_id,
                "video_duration_s": 100,
                "show_metadata_footer": True,
            },
            content_location="exports/mp4/team-1/task-1",
            is_system=True,
        )

    def _prepare(self, **overrides: Any) -> Any:
        fields: dict[str, Any] = {
            "team_id": self.team.id,
            "observation_id": self.observation.id,
            "session_id": self.session_id,
            "analysis_asset_id": self.analysis_asset.id,
        }
        fields.update(overrides)
        return async_to_sync(prepare_observation_thumbnail_activity)(
            PrepareObservationThumbnailInputs(inputs=ObservationMediaInputs(**fields))
        )

    def test_media_object_is_written_outside_the_exports_prefix(self) -> None:
        prepared = self._prepare()

        assert prepared.activity_input.s3_key_prefix == (
            f"replay-vision/media/team-{self.team.id}/{self.observation.id}"
        )
        asset = ExportedAsset.objects.get(pk=prepared.media_asset_id)
        assert asset.is_system is True
        assert asset.export_context["observation_id"] == str(self.observation.id)
        assert asset.export_context["session_recording_id"] == self.session_id
        assert 89 <= (asset.expires_after - asset.created_at).days <= 90

    def test_the_models_pick_wins_over_every_fallback(self) -> None:
        self.observation.scanner_result = {
            "model_output": {"summary_segments": [{"kind": "chip", "timestamp_ms": 12_000}]}
        }
        self.observation.save(update_fields=["scanner_result"])

        prepared = self._prepare(thumbnail_video_s=70, signal_video_times=[(40, 60)])

        assert prepared.activity_input.video_time_s == 70.0

    @parameterized.expand(
        [
            ("citation_wins", {"summary_segments": [{"kind": "chip", "timestamp_ms": 12_000}]}, [(40, 60)], 12.0),
            ("signal_midpoint", {"summary_segments": [{"kind": "text", "value": "no chip"}]}, [(40, 60)], 50.0),
            ("quarter_of_the_video", {}, [], 25.0),
        ]
    )
    def test_thumbnail_moment(
        self, _name: str, model_output: dict[str, Any], signals: list[tuple[int, int]], expected_s: float
    ) -> None:
        self.observation.scanner_result = {"model_output": model_output}
        self.observation.save(update_fields=["scanner_result"])

        prepared = self._prepare(signal_video_times=signals)

        assert prepared.activity_input.video_time_s == expected_s
        assert prepared.video_start_ms == int(expected_s * 1000)

    def test_finalize_links_the_rendered_object_to_the_observation(self) -> None:
        prepared = self._prepare()

        async_to_sync(finalize_observation_thumbnail_activity)(
            FinalizeObservationThumbnailInputs(
                team_id=self.team.id,
                observation_id=self.observation.id,
                media_asset_id=prepared.media_asset_id,
                video_start_ms=prepared.video_start_ms,
                rec_start_ms=prepared.rec_start_ms,
                result=ExtractThumbnailActivityOutput(
                    s3_uri=f"s3://{settings.OBJECT_STORAGE_BUCKET}/replay-vision/media/team-{self.team.id}/{self.observation.id}/x.png",
                    file_size_bytes=4096,
                ),
            )
        )

        media = ReplayObservationMedia.objects.for_team(self.team.id).get(observation_id=self.observation.id)
        assert media.kind == ReplayObservationMedia.Kind.THUMBNAIL
        assert media.asset_id == prepared.media_asset_id
        assert media.asset.content_location.startswith("replay-vision/media/")


class TestObservationMediaExpiry(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.scanner = ReplayScanner.objects.create(
            team=self.team,
            name="Checkout monitor",
            scanner_type=ScannerType.MONITOR,
            scanner_config={"prompt": "did the user check out?"},
            model=ScannerModel.GEMINI_3_8_FLASH,
        )
        self.observation = ReplayObservation.objects.create(
            scanner=self.scanner,
            team=self.team,
            session_id=f"s-{uuid7()}",
            status=ObservationStatus.SUCCEEDED,
            completed_at=timezone.now(),
            scanner_snapshot=snapshot_for(self.scanner),
            triggered_by=ObservationTrigger.SCHEDULE,
        )
        self.media_asset = ExportedAsset.objects.create(
            team=self.team,
            export_format=ExportedAsset.ExportFormat.PNG,
            export_context={"observation_id": str(self.observation.id)},
            content_location=f"replay-vision/media/team-{self.team.id}/{self.observation.id}/x.png",
            expires_after=timezone.now() + timedelta(days=90),
            is_system=True,
        )
        self.other_asset = ExportedAsset.objects.create(
            team=self.team,
            export_format=ExportedAsset.ExportFormat.PNG,
            export_context={"observation_id": str(uuid7())},
            expires_after=timezone.now() + timedelta(days=90),
            is_system=True,
        )

    def _expires_after(self, asset: ExportedAsset) -> Any:
        return ExportedAsset.objects_including_ttl_deleted.get(pk=asset.pk).expires_after

    def test_only_the_named_observations_media_is_expired(self) -> None:
        expire_media_for_observations(self.team.id, [self.observation.id])

        assert self._expires_after(self.media_asset) <= timezone.now()
        assert self._expires_after(self.other_asset) > timezone.now()

    def test_a_scanners_whole_set_is_expired(self) -> None:
        expire_media_for_scanner(self.team.id, self.scanner.observations.all())

        assert self._expires_after(self.media_asset) <= timezone.now()

    def test_the_row_survives_so_the_sweep_can_delete_the_object(self) -> None:
        expire_media_for_observations(self.team.id, [self.observation.id])

        assert ExportedAsset.objects_including_ttl_deleted.filter(pk=self.media_asset.pk).exists()
