import dataclasses
from datetime import datetime, timedelta
from typing import Any

from posthog.test.base import BaseTest

from django.conf import settings
from django.utils import timezone

from asgiref.sync import async_to_sync
from parameterized import parameterized
from temporalio.testing import ActivityEnvironment

from posthog.models.utils import uuid7

from products.exports.backend.models.exported_asset import ExportedAsset
from products.replay_vision.backend.api.observations import ReplayObservationSerializer
from products.replay_vision.backend.models.replay_observation import (
    ObservationStatus,
    ObservationTrigger,
    ReplayObservation,
    hydrate_for_serialization,
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

    def _inputs(self, **overrides: Any) -> ObservationMediaInputs:
        fields: dict[str, Any] = {
            "team_id": self.team.id,
            "observation_id": self.observation.id,
            "session_id": self.session_id,
            "analysis_asset_id": self.analysis_asset.id,
        }
        fields.update(overrides)
        return ObservationMediaInputs(**fields)

    def _prepare(self, **overrides: Any) -> Any:
        return async_to_sync(prepare_observation_thumbnail_activity)(self._inputs(**overrides))

    def test_media_object_is_written_outside_the_exports_prefix(self) -> None:
        prepared = self._prepare()

        assert prepared.activity_input.s3_key_prefix == (
            f"replay-vision/media/team-{self.team.id}/{self.observation.id}"
        )
        asset = ExportedAsset.objects.get(pk=prepared.media_asset_id)
        assert asset.is_system is True
        assert (asset.export_context or {})["observation_id"] == str(self.observation.id)
        assert (asset.export_context or {})["session_recording_id"] == self.session_id
        assert asset.expires_after is not None
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
        assert (media.asset.content_location or "").startswith("replay-vision/media/")

    def test_a_retry_of_the_same_render_does_not_spend_another_attempt(self) -> None:
        # The backfill sweep gives up after three attempts, so an activity retry must not count as one.
        self._prepare()
        self.observation.refresh_from_db()
        assert self.observation.media_render_attempts == 1
        assert self.observation.media_render_attempted_at is not None

        async def retry_the_same_activity() -> None:
            environment = ActivityEnvironment()
            environment.info = dataclasses.replace(environment.info, attempt=2)
            await environment.run(prepare_observation_thumbnail_activity, self._inputs())

        async_to_sync(retry_the_same_activity)()

        self.observation.refresh_from_db()
        assert self.observation.media_render_attempts == 1

    def test_an_observation_deleted_mid_render_expires_the_asset_with_its_location(self) -> None:
        prepared = self._prepare()
        observation_id = self.observation.id
        self.observation.delete()

        async_to_sync(finalize_observation_thumbnail_activity)(
            FinalizeObservationThumbnailInputs(
                team_id=self.team.id,
                observation_id=observation_id,
                media_asset_id=prepared.media_asset_id,
                video_start_ms=prepared.video_start_ms,
                rec_start_ms=prepared.rec_start_ms,
                result=ExtractThumbnailActivityOutput(
                    s3_uri=f"s3://{settings.OBJECT_STORAGE_BUCKET}/replay-vision/media/team-{self.team.id}/{observation_id}/x.png",
                    file_size_bytes=4096,
                ),
            )
        )

        asset = ExportedAsset.objects_including_ttl_deleted.get(pk=prepared.media_asset_id)
        assert asset.expires_after is not None
        assert (asset.content_location or "").startswith("replay-vision/media/")


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
        self.asset = ExportedAsset.objects.create(
            team=self.team,
            export_format=ExportedAsset.ExportFormat.PNG,
            export_context={"observation_id": str(self.observation.id)},
            content_location=f"replay-vision/media/team-{self.team.id}/{self.observation.id}/x.png",
            expires_after=timezone.now() + timedelta(days=90),
            is_system=True,
        )
        ReplayObservationMedia.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            observation=self.observation,
            asset=self.asset,
            kind=ReplayObservationMedia.Kind.THUMBNAIL,
            position=0,
            video_start_ms=1000,
        )

    def _expires_after(self) -> datetime:
        expires_after = ExportedAsset.objects_including_ttl_deleted.get(pk=self.asset.pk).expires_after
        assert expires_after is not None
        return expires_after

    @parameterized.expand(
        [
            # Every path that removes an observation reaches the media row through a cascade.
            ("observation delete, as a retry does", lambda self: self.observation.delete()),
            ("scanner delete", lambda self: self.scanner.delete()),
        ]
    )
    def test_media_is_expired_when_its_observation_goes_away(self, _name: str, delete) -> None:
        delete(self)

        assert self._expires_after() <= timezone.now()
        assert ExportedAsset.objects_including_ttl_deleted.filter(pk=self.asset.pk).exists()

    def test_the_sweeps_own_delete_is_not_undone(self) -> None:
        self.asset.delete()

        assert not ExportedAsset.objects_including_ttl_deleted.filter(pk=self.asset.pk).exists()


class TestObservationMediaSerialization(BaseTest):
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

    def _add_media(self, *, rendered: bool, position: int = 0) -> ReplayObservationMedia:
        asset = ExportedAsset.objects.create(
            team=self.team,
            export_format=ExportedAsset.ExportFormat.PNG,
            export_context={"observation_id": str(self.observation.id)},
            content_location=f"replay-vision/media/team-{self.team.id}/x-{position}.png" if rendered else None,
            is_system=True,
        )
        return ReplayObservationMedia.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            observation=self.observation,
            asset=asset,
            kind=ReplayObservationMedia.Kind.THUMBNAIL,
            position=position,
            video_start_ms=1000 * (position + 1),
        )

    def test_only_rendered_media_is_served(self) -> None:
        ready = self._add_media(rendered=True, position=0)
        self._add_media(rendered=False, position=1)

        observation = hydrate_for_serialization(ReplayObservation.objects.filter(pk=self.observation.pk)).get()
        media = ReplayObservationSerializer(observation).data["media"]

        assert [entry["id"] for entry in media] == [ready.id]
        assert media[0]["asset_id"] == ready.asset_id
        assert media[0]["video_start_ms"] == 1000
