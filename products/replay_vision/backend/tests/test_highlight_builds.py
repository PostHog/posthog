import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import time_machine
from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.models import Team

from products.replay_vision.backend.highlight_builds import build_highlight_feed, rank_window
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
from products.replay_vision.backend.observation_ranks import NewRank, copy_team_ranks, record_ranks
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

    def test_group_reach_counts_people_once_and_leaves_out_experiment_rows(self) -> None:
        ids = self._ranked(10, age=timedelta(hours=1))
        group = uuid.uuid4()
        same_person = [self._observation(_NOW - timedelta(hours=2), person="p1") for _ in range(2)]
        experiment = self._observation(
            _NOW - timedelta(hours=2), scanner_snapshot={"experiment_targeting": {"experiment_id": 9}}
        )
        members = [*same_person, experiment]
        record_ranks(
            self.team.id,
            ANCHOR_VERSION,
            {str(member.id): NewRank(contrast=0.1, category="failure") for member in members},
        )
        ReplayObservationRank.objects.for_team(self.team.id).filter(
            observation_id__in=[ids[0], *(member.id for member in members)]
        ).update(feed_group_id=group)

        build_highlight_feed(self.team.id, ANCHOR_VERSION)

        best = ReplayHighlightFeedEntry.objects.for_team(self.team.id).get(window_days=1, observation_id=ids[0])
        assert (best.group_root, best.group_sessions, best.group_people) == (group, 3, 2)
        assert ReplayObservationRank.objects.for_team(self.team.id).get(observation_id=experiment.id).experiment_id == 9

    def test_an_arbitrary_window_ranks_like_a_build(self) -> None:
        self._ranked(10, age=timedelta(hours=1))

        build_highlight_feed(self.team.id, ANCHOR_VERSION)
        ranked = rank_window(self.team.id, ANCHOR_VERSION, _NOW - timedelta(days=1), _NOW)

        stored = ReplayHighlightFeedEntry.objects.for_team(self.team.id).filter(window_days=1)
        assert sorted((entry.observation_id, entry.place) for entry in ranked) == sorted(
            (entry.observation_id, entry.place) for entry in stored
        )

    def test_a_new_build_keeps_the_build_it_replaces_and_drops_older_ones(self) -> None:
        self._ranked(10, age=timedelta(hours=1))

        generations = [build_highlight_feed(self.team.id, ANCHOR_VERSION, force=True) for _ in range(3)]

        state = ReplayHighlightFeedState.objects.for_team(self.team.id).get()
        assert set(
            ReplayHighlightFeedEntry.objects.for_team(self.team.id).values_list("generation", flat=True).distinct()
        ) == {2, 3}
        assert (generations, state.generation, state.previous_generation) == ([1, 2, 3], 3, 2)

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

    def test_copy_fills_a_missing_group_from_the_rank_json_once(self) -> None:
        group = uuid.uuid4()
        observation = self._observation(
            _NOW,
            watch_rank={"category": "struggle", "contrast": 0.7, "anchor_version": ANCHOR_VERSION, "group": str(group)},
        )
        self._observation(_NOW, watch_rank={"category": "failure", "contrast": 0.7, "anchor_version": 99})

        copied = copy_team_ranks(self.team.id, ANCHOR_VERSION, _NOW - timedelta(days=1))
        again = copy_team_ranks(self.team.id, ANCHOR_VERSION, _NOW - timedelta(days=1))

        rank = ReplayObservationRank.objects.for_team(self.team.id).get()
        assert (copied, again) == (1, 0)
        assert (rank.observation_id, rank.category, rank.feed_group_id) == (
            observation.id,
            RankCategory.STRUGGLE,
            group,
        )
