from datetime import timedelta

from posthog.test.base import BaseTest

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from asgiref.sync import async_to_sync
from parameterized import parameterized

from posthog.models.utils import uuid7

from products.exports.backend.models.exported_asset import ExportedAsset
from products.replay_vision.backend.models.replay_observation import (
    ObservationStatus,
    ObservationTrigger,
    ReplayObservation,
)
from products.replay_vision.backend.models.replay_observation_media import ReplayObservationMedia
from products.replay_vision.backend.models.replay_scanner import ReplayScanner, ScannerModel, ScannerType
from products.replay_vision.backend.temporal.activities.ensure_session_asset import analysis_export_context
from products.replay_vision.backend.temporal.media_backfill.activities import find_media_backfill_candidates_activity
from products.replay_vision.backend.temporal.media_backfill.constants import (
    ATTEMPT_COOLDOWN,
    MAX_OBSERVATION_AGE,
    MAX_RENDER_ATTEMPTS,
    MIN_OBSERVATION_AGE,
)
from products.replay_vision.backend.temporal.media_backfill.types import MediaBackfillInputs
from products.replay_vision.backend.tests.helpers import snapshot_for


class TestMediaBackfillCandidates(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.scanner = ReplayScanner.objects.create(
            team=self.team,
            name="Checkout monitor",
            scanner_type=ScannerType.MONITOR,
            scanner_config={"prompt": "did the user check out?"},
            model=ScannerModel.GEMINI_3_8_FLASH,
        )

    def _observation(
        self, *, status: str = ObservationStatus.SUCCEEDED, age: timedelta | None = None
    ) -> ReplayObservation:
        observation = ReplayObservation.objects.create(
            scanner=self.scanner,
            team=self.team,
            session_id=f"s-{uuid7()}",
            status=status,
            completed_at=timezone.now(),
            scanner_snapshot=snapshot_for(self.scanner),
            triggered_by=ObservationTrigger.SCHEDULE,
        )
        created = timezone.now() - (age if age is not None else MIN_OBSERVATION_AGE + timedelta(minutes=5))
        ReplayObservation.objects.filter(pk=observation.pk).update(created_at=created)
        observation.refresh_from_db()
        return observation

    def _analysis_video(self, observation: ReplayObservation, *, rendered: bool = True) -> ExportedAsset:
        return ExportedAsset.objects.create(
            team=self.team,
            export_format=ExportedAsset.ExportFormat.MP4,
            export_context=analysis_export_context(observation.session_id),
            content_location=f"exports/mp4/team-{self.team.id}/{observation.session_id}.mp4" if rendered else None,
            is_system=True,
        )

    def _record_attempt(self, observation: ReplayObservation, *, attempts: int, when) -> None:
        ReplayObservation.objects.filter(pk=observation.pk).update(
            media_render_attempts=attempts, media_render_attempted_at=when
        )

    def _candidates(self, limit: int | None = None):
        return async_to_sync(find_media_backfill_candidates_activity)(MediaBackfillInputs(limit=limit))

    def test_an_observation_without_media_is_a_candidate(self) -> None:
        observation = self._observation()
        asset = self._analysis_video(observation)

        result = self._candidates()

        assert [c.observation_id for c in result.candidates] == [observation.id]
        assert result.candidates[0].analysis_asset_id == asset.id

    def test_an_observation_that_already_has_a_poster_is_skipped(self) -> None:
        observation = self._observation()
        asset = self._analysis_video(observation)
        ReplayObservationMedia.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            observation=observation,
            asset=asset,
            kind=ReplayObservationMedia.Kind.THUMBNAIL,
            position=0,
            video_start_ms=1000,
        )

        assert self._candidates().candidates == []

    @parameterized.expand(["video expired", "video never rendered", "observation failed"])
    def test_an_ineligible_observation_is_not_dispatched(self, case: str) -> None:
        failed = case == "observation failed"
        observation = self._observation(status=ObservationStatus.FAILED if failed else ObservationStatus.SUCCEEDED)
        if case == "video never rendered":
            self._analysis_video(observation, rendered=False)
        elif failed:
            self._analysis_video(observation)

        assert self._candidates().candidates == []

    def test_an_unfillable_observation_is_counted(self) -> None:
        # Its analysis video has expired, so no tick will ever fix it.
        self._observation()

        assert self._candidates().without_video == 1

    def test_a_fresh_observation_is_left_to_its_own_scan(self) -> None:
        # The live path is already rendering it, and both would race the same workflow id.
        fresh = self._observation(age=timedelta(minutes=1))
        self._analysis_video(fresh)

        assert self._candidates().candidates == []

    def test_the_limit_caps_a_tick(self) -> None:
        for _ in range(3):
            self._analysis_video(self._observation())

        assert len(self._candidates(limit=2).candidates) == 2

    def test_the_newest_candidates_go_first(self) -> None:
        older = self._observation(age=timedelta(days=3))
        newer = self._observation(age=timedelta(hours=2))
        self._analysis_video(older)
        self._analysis_video(newer)

        result = self._candidates()

        assert [c.observation_id for c in result.candidates] == [newer.id, older.id]

    def test_the_walk_stops_at_the_video_retention_floor(self) -> None:
        # Past this age the analysis video is gone, so rescanning those rows every tick buys nothing.
        ancient = self._observation(age=MAX_OBSERVATION_AGE + timedelta(days=1))
        self._analysis_video(ancient)

        assert self._candidates().candidates == []

    def test_a_recent_attempt_waits_out_its_cooldown(self) -> None:
        observation = self._observation()
        self._analysis_video(observation)
        self._record_attempt(observation, attempts=1, when=timezone.now() - timedelta(minutes=5))

        result = self._candidates()

        assert result.candidates == []
        assert result.cooling_off == 1

    def test_an_old_attempt_is_tried_again(self) -> None:
        observation = self._observation()
        self._analysis_video(observation)
        self._record_attempt(observation, attempts=1, when=timezone.now() - ATTEMPT_COOLDOWN - timedelta(hours=1))

        assert [c.observation_id for c in self._candidates().candidates] == [observation.id]

    def test_an_observation_that_keeps_failing_is_given_up_on(self) -> None:
        # Otherwise it holds the head of a newest-first walk and nothing older is ever reached.
        observation = self._observation()
        self._analysis_video(observation)
        self._record_attempt(
            observation, attempts=MAX_RENDER_ATTEMPTS, when=timezone.now() - ATTEMPT_COOLDOWN - timedelta(hours=1)
        )

        result = self._candidates()

        assert result.candidates == []
        assert result.cooling_off == 0

    def test_a_page_of_candidates_costs_a_fixed_number_of_queries(self) -> None:
        # The tick dispatches up to 250, so a per-candidate lookup would be hundreds of round trips.
        for _ in range(6):
            self._analysis_video(self._observation())

        with CaptureQueriesContext(connection) as queries:
            result = self._candidates()

        assert len(result.candidates) == 6
        assert len(queries.captured_queries) <= 4
