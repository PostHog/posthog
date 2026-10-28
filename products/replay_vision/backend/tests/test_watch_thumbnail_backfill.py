from datetime import timedelta

from posthog.test.base import BaseTest

from django.utils import timezone

from products.exports.backend.models.exported_asset import ExportedAsset
from products.replay_vision.backend.models.replay_observation import ObservationTrigger, ReplayObservation
from products.replay_vision.backend.models.replay_observation_media import ReplayObservationMedia
from products.replay_vision.backend.models.replay_scanner import ReplayScanner, ScannerModel, ScannerType
from products.replay_vision.backend.temporal.activities.ensure_session_asset import analysis_export_context
from products.replay_vision.backend.tests.helpers import snapshot_for
from products.replay_vision.backend.watch_rank import ANCHOR_VERSION
from products.replay_vision.backend.watch_thumbnail_backfill import thumbnail_backfill_targets


class TestThumbnailBackfillTargets(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.scanner = ReplayScanner.objects.create(
            team=self.team,
            name="checkout",
            scanner_type=ScannerType.SUMMARIZER,
            scanner_config={"prompt": "What happened at checkout?"},
            model=ScannerModel.GEMINI_3_8_FLASH,
        )
        self.now = timezone.now()

    def _observation(self, session_id: str, category: str, contrast: float) -> ReplayObservation:
        return ReplayObservation.objects.create(
            scanner=self.scanner,
            team=self.team,
            session_id=session_id,
            status="succeeded",
            completed_at=self.now - timedelta(days=40),
            triggered_by=ObservationTrigger.ON_DEMAND,
            scanner_snapshot=snapshot_for(self.scanner),
            watch_rank={"category": category, "contrast": contrast, "group": None, "anchor_version": ANCHOR_VERSION},
            scanner_result={"model_output": {"scanner_type": "summarizer", "summary": ""}},
        )

    def _video(self, session_id: str, *, expired: bool = False) -> ExportedAsset:
        return ExportedAsset.objects.create(
            team=self.team,
            export_format="video/mp4",
            export_context=analysis_export_context(session_id),
            content_location=f"replay-vision/{session_id}.mp4",
            is_system=True,
            expires_after=self.now - timedelta(days=1) if expired else self.now + timedelta(days=30),
        )

    def test_it_renders_only_picks_without_a_thumbnail_that_still_have_their_video(self) -> None:
        for index in range(12):
            self._observation(f"routine-{index}", "routine", -0.1)
        has_thumbnail = self._observation("has-thumbnail", "failure", 0.5)
        needs_thumbnail = self._observation("needs-thumbnail", "failure", 0.4)
        self._observation("video-gone", "failure", 0.3)
        ReplayObservationMedia.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            observation=has_thumbnail,
            asset=self._video("has-thumbnail"),
            kind=ReplayObservationMedia.Kind.THUMBNAIL,
            position=0,
            video_start_ms=0,
        )
        video = self._video("needs-thumbnail")
        self._video("video-gone", expired=True)

        targets = thumbnail_backfill_targets(self.team.id, self.now - timedelta(days=90), self.now, 1000)

        assert targets.picks == 3
        assert [(r.observation_id, r.analysis_asset_id) for r in targets.renders] == [(needs_thumbnail.id, video.id)]
        assert targets.without_video == 1
