import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import time_machine
from posthog.test.base import BaseTest
from unittest.mock import patch

from django.utils import timezone

from parameterized import parameterized
from temporalio.testing import ActivityEnvironment

from posthog.models import Team

from products.replay_vision.backend.highlight_builds import (
    BUILD_RETENTION,
    STALE_AFTER,
    build_highlight_feed,
    rank_window,
    rebuild_changed_feeds,
    stored_generation,
)
from products.replay_vision.backend.models.replay_highlight_feed import (
    ReplayHighlightFeedEntry,
    ReplayHighlightFeedState,
)
from products.replay_vision.backend.models.replay_observation import (
    ObservationStatus,
    ObservationTrigger,
    ReplayObservation,
)
from products.replay_vision.backend.models.replay_observation_rank import RankCategory, ReplayObservationRank
from products.replay_vision.backend.models.replay_scanner import ReplayScanner, ScannerModel, ScannerType
from products.replay_vision.backend.observation_ranks import NewRank, record_ranks
from products.replay_vision.backend.temporal.activities.rebuild_highlight_feeds import rebuild_highlight_feeds_activity
from products.replay_vision.backend.tests.helpers import snapshot_for
from products.replay_vision.backend.watch_rank import ANCHOR_VERSION

_NOW = datetime(2026, 10, 20, 12, tzinfo=UTC)


@time_machine.travel(_NOW, tick=False)
class TestHighlightBuilds(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.scanner = self._scanner("checkout")

    def _scanner(self, name: str) -> ReplayScanner:
        return ReplayScanner.objects.create(
            team=self.team,
            name=name,
            scanner_type=ScannerType.MONITOR,
            scanner_config={"prompt": "p"},
            model=ScannerModel.GEMINI_3_8_FLASH,
        )

    def _observation(
        self, created_at: datetime, *, scanner: ReplayScanner | None = None, person: str = "", **fields: Any
    ) -> ReplayObservation:
        scanner = scanner or self.scanner
        fields.setdefault("scanner_snapshot", snapshot_for(scanner))
        fields.setdefault("completed_at", created_at)
        fields.setdefault("team", self.team)
        observation = ReplayObservation.objects.create(
            scanner=scanner,
            session_id=f"sess-{uuid.uuid4()}",
            distinct_id=person,
            triggered_by=ObservationTrigger.ON_DEMAND,
            status=ObservationStatus.SUCCEEDED,
            **fields,
        )
        ReplayObservation.objects.filter(id=observation.id).update(created_at=created_at)
        return observation

    def _ranked(self, count: int, *, age: timedelta, top: float = 1.0) -> list[str]:
        ids = []
        for index in range(count):
            observation = self._observation(_NOW - age - timedelta(minutes=index))
            ids.append(str(observation.id))
            record_ranks(
                self.team.id, ANCHOR_VERSION, {ids[-1]: NewRank(contrast=top - index / 100, category="failure")}
            )
        return ids

    def test_a_build_keeps_each_windows_top_fifth_with_percentiles(self) -> None:
        recent = self._ranked(10, age=timedelta(hours=1))
        older = self._ranked(10, age=timedelta(days=3), top=0.5)

        build_highlight_feed(self.team.id, ANCHOR_VERSION)

        entries = {
            (entry.window_days, str(entry.observation_id)): (entry.place, round(entry.percentile, 3))
            for entry in ReplayHighlightFeedEntry.objects.for_team(self.team.id)
        }
        people = dict(ReplayObservationRank.objects.for_team(self.team.id).values_list("observation_id", "person_key"))
        assert all(
            entry.person_key is not None and entry.person_key == people[entry.observation_id]
            for entry in ReplayHighlightFeedEntry.objects.for_team(self.team.id)
        )
        # The day window has ten rows, so its best two clear the cut; the week window places all twenty.
        assert {key: value for key, value in entries.items() if key[0] == 1} == {
            (1, recent[0]): (1, 0.95),
            (1, recent[1]): (2, 0.85),
        }
        assert {key: value for key, value in entries.items() if key[0] == 7} == {
            (7, recent[0]): (1, 0.975),
            (7, recent[1]): (2, 0.925),
            (7, recent[2]): (3, 0.875),
            (7, recent[3]): (4, 0.825),
        }
        assert older[0] not in {observation_id for _, observation_id in entries}

    @parameterized.expand(
        [
            ("too_few_rows_for_a_percentile", 9, 0),
            ("enough_rows", 10, 2),
        ]
    )
    def test_a_scanner_needs_enough_rows_to_be_placed(self, _name: str, rows: int, kept: int) -> None:
        self._ranked(rows, age=timedelta(hours=1))

        build_highlight_feed(self.team.id, ANCHOR_VERSION)

        assert ReplayHighlightFeedEntry.objects.for_team(self.team.id).filter(window_days=1).count() == kept

    @parameterized.expand(
        [
            ("targeted", {"experiment_targeting": {"experiment_id": 9}}, 9),
            ("config", {"scanner_config": {"experiment_id": 4}}, 4),
            # A value no viewer's experiment can match keeps the row hidden from everyone.
            ("unparseable", {"experiment_targeting": {"experiment_id": 9.5}}, -1),
            ("untargeted", {}, 0),
        ]
    )
    def test_a_rank_row_records_the_experiment_its_scan_was_scoped_to(
        self, _name: str, snapshot: dict[str, Any], experiment_id: int
    ) -> None:
        observation = self._observation(_NOW, scanner_snapshot=snapshot)

        record_ranks(self.team.id, ANCHOR_VERSION, {str(observation.id): NewRank(contrast=0.1, category="failure")})

        assert ReplayObservationRank.objects.for_team(self.team.id).get().experiment_id == experiment_id

    def test_an_arbitrary_window_ranks_like_a_build_and_narrows_to_its_scanners(self) -> None:
        self._ranked(10, age=timedelta(hours=1))
        other = self._scanner("other")
        for index in range(10):
            observation = self._observation(_NOW - timedelta(hours=2, minutes=index), scanner=other)
            record_ranks(self.team.id, ANCHOR_VERSION, {str(observation.id): NewRank(contrast=0.5, category="failure")})

        build_highlight_feed(self.team.id, ANCHOR_VERSION)
        ranked = rank_window(self.team.id, ANCHOR_VERSION, _NOW - timedelta(days=1), _NOW, [self.scanner.id])

        stored = ReplayHighlightFeedEntry.objects.for_team(self.team.id).filter(
            window_days=1, scanner_id=self.scanner.id
        )
        assert sorted((entry.observation_id, entry.place) for entry in ranked) == sorted(
            (entry.observation_id, entry.place) for entry in stored
        )
        assert rank_window(self.team.id, ANCHOR_VERSION, _NOW - timedelta(days=1), _NOW, []) == []

    def test_a_build_keeps_recent_builds_and_drops_ones_past_retention(self) -> None:
        self._ranked(10, age=timedelta(hours=1))

        build_highlight_feed(self.team.id, ANCHOR_VERSION, force=True)
        with time_machine.travel(_NOW + BUILD_RETENTION + timedelta(minutes=1), tick=False):
            build_highlight_feed(self.team.id, ANCHOR_VERSION, force=True)
            build_highlight_feed(self.team.id, ANCHOR_VERSION, force=True)

        state = ReplayHighlightFeedState.objects.for_team(self.team.id).get()
        assert set(
            ReplayHighlightFeedEntry.objects.for_team(self.team.id).values_list("generation", flat=True).distinct()
        ) == {2, 3}
        assert [build[0] for build in state.builds] == [2, 3]

    def test_a_team_built_since_its_last_change_keeps_its_build(self) -> None:
        self._ranked(10, age=timedelta(hours=1))
        first = build_highlight_feed(self.team.id, ANCHOR_VERSION)

        unchanged = build_highlight_feed(self.team.id, ANCHOR_VERSION)
        self._ranked(1, age=timedelta(minutes=5))
        changed = build_highlight_feed(self.team.id, ANCHOR_VERSION)

        assert (first, unchanged, changed) == (1, 1, 2)

    @parameterized.expand(
        [
            ("redelivery_keeps_the_first_rank", ANCHOR_VERSION, 0, 0.4, RankCategory.FAILURE),
            ("new_anchors_rank_afresh", ANCHOR_VERSION + 1, 1, 0.9, RankCategory.STRUGGLE),
        ]
    )
    def test_a_second_rank_replaces_only_a_rank_from_other_anchors(
        self, _name: str, second_version: int, written: int, contrast: float, category: int
    ) -> None:
        observation = self._observation(_NOW)
        record_ranks(self.team.id, ANCHOR_VERSION, {str(observation.id): NewRank(contrast=0.4, category="failure")})
        ReplayObservationRank.objects.for_team(self.team.id).update(feed_group_id=uuid.uuid4())

        again = record_ranks(
            self.team.id, second_version, {str(observation.id): NewRank(contrast=0.9, category="struggle")}
        )

        rank = ReplayObservationRank.objects.for_team(self.team.id).get(observation_id=observation.id)
        assert (again, rank.contrast, rank.category, rank.feed_group_id is None) == (
            written,
            contrast,
            category,
            written == 1,
        )

    def test_a_child_environments_ranks_reach_its_projects_builds(self) -> None:
        child = Team.objects.create(organization=self.organization, project=self.team.project, parent_team=self.team)
        scanner = ReplayScanner.objects.create(
            team=child,
            name="child",
            scanner_type=ScannerType.MONITOR,
            scanner_config={"prompt": "p"},
            model=ScannerModel.GEMINI_3_8_FLASH,
        )
        for index in range(10):
            observation = self._observation(_NOW - timedelta(hours=1, minutes=index), scanner=scanner, team=child)
            record_ranks(
                child.id, ANCHOR_VERSION, {str(observation.id): NewRank(contrast=1 - index / 100, category="failure")}
            )

        build_highlight_feed(child.id, ANCHOR_VERSION)

        assert ReplayHighlightFeedEntry.objects.for_team(self.team.id).filter(window_days=1).count() == 2

    def test_a_stale_build_is_served_and_the_sweep_rebuilds_it_once(self) -> None:
        self._ranked(10, age=timedelta(hours=1))
        first = build_highlight_feed(self.team.id, ANCHOR_VERSION)

        with time_machine.travel(_NOW + STALE_AFTER + timedelta(minutes=1), tick=False):
            served = stored_generation(self.team.id, ANCHOR_VERSION, timezone.now())
            built = [rebuild_changed_feeds(ANCHOR_VERSION), rebuild_changed_feeds(ANCHOR_VERSION)]

        assert (first, served, built) == (1, 1, [1, 0])
        assert ReplayHighlightFeedState.objects.for_team(self.team.id).get().generation == 2

    def test_the_rebuild_activity_works_through_every_due_batch(self) -> None:
        other = Team.objects.create(organization=self.organization, name="other")
        other_scanner = ReplayScanner.objects.create(
            team=other,
            name="other",
            scanner_type=ScannerType.MONITOR,
            scanner_config={"prompt": "p"},
            model=ScannerModel.GEMINI_3_8_FLASH,
        )
        self._ranked(10, age=timedelta(hours=1))
        for index in range(10):
            observation = self._observation(_NOW - timedelta(hours=1, minutes=index), scanner=other_scanner, team=other)
            record_ranks(
                other.id, ANCHOR_VERSION, {str(observation.id): NewRank(contrast=index / 10, category="failure")}
            )

        with patch("products.replay_vision.backend.highlight_builds.REBUILDS_PER_SWEEP", 1):
            result = ActivityEnvironment().run(rebuild_highlight_feeds_activity)

        assert result.built == 2
        assert set(ReplayHighlightFeedState.objects.unscoped().values_list("team_id", "generation")) == {
            (self.team.id, 1),
            (other.id, 1),
        }

    def test_a_load_that_began_before_a_rebuild_stays_on_the_build_it_started_on(self) -> None:
        self._ranked(10, age=timedelta(hours=1))

        first = stored_generation(self.team.id, ANCHOR_VERSION, _NOW)
        with time_machine.travel(_NOW + timedelta(minutes=10), tick=False):
            build_highlight_feed(self.team.id, ANCHOR_VERSION, force=True)
            later_page = stored_generation(self.team.id, ANCHOR_VERSION, _NOW)
            new_load = stored_generation(self.team.id, ANCHOR_VERSION, timezone.now())

        assert (first, later_page, new_load) == (1, 1, 2)
        assert ReplayHighlightFeedEntry.objects.for_team(self.team.id).filter(generation=1).exists()
