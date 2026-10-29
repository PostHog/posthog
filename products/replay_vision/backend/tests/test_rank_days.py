from datetime import UTC, datetime, timedelta

from posthog.test.base import BaseTest

from parameterized import parameterized

from products.replay_vision.backend.models.replay_observation import (
    ObservationStatus,
    ObservationTrigger,
    ReplayObservation,
)
from products.replay_vision.backend.models.replay_scanner import ReplayScanner, ScannerModel, ScannerType
from products.replay_vision.backend.models.replay_scanner_rank_day import ReplayScannerRankDay
from products.replay_vision.backend.rank_days import backfill_team_rank_days, scanner_rank_counts
from products.replay_vision.backend.tests.helpers import snapshot_for
from products.replay_vision.backend.watch_rank import ANCHOR_VERSION

_DAY = datetime(2026, 10, 1, tzinfo=UTC)
_ROW_TIMES = [
    _DAY,
    _DAY + timedelta(hours=12),
    _DAY + timedelta(days=1, hours=6),
    _DAY + timedelta(days=3) - timedelta(seconds=1),
    _DAY + timedelta(days=3),
    _DAY + timedelta(days=4, hours=10),
    _DAY + timedelta(days=5),
]


class TestRankDays(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.scanner = ReplayScanner.objects.create(
            team=self.team,
            name="s",
            scanner_type=ScannerType.MONITOR,
            scanner_config={"prompt": "p"},
            model=ScannerModel.GEMINI_3_8_FLASH,
        )
        self.rows = []
        for index, created_at in enumerate(_ROW_TIMES):
            row = ReplayObservation.objects.create(
                scanner=self.scanner,
                team=self.team,
                session_id=f"sess-{index}",
                triggered_by=ObservationTrigger.ON_DEMAND,
                scanner_snapshot=snapshot_for(self.scanner),
                status=ObservationStatus.SUCCEEDED,
                watch_rank={"anchor_version": ANCHOR_VERSION, "category": "failure", "contrast": 0.5},
            )
            ReplayObservation.objects.filter(id=row.id).update(created_at=created_at)
            self.rows.append(row)

    @parameterized.expand(
        [
            ("inside_one_day", _DAY + timedelta(hours=1), _DAY + timedelta(hours=23), []),
            ("adjacent_days", _DAY + timedelta(hours=12), _DAY + timedelta(days=1, hours=12), []),
            ("from_midnight_to_midnight", _DAY, _DAY + timedelta(days=5), []),
            ("ends_on_a_row_at_midnight", _DAY + timedelta(days=1), _DAY + timedelta(days=3), []),
            ("dismissed_row_on_a_middle_day", _DAY, _DAY + timedelta(days=5), [3]),
        ]
    )
    def test_window_counts_match_the_rows(
        self, _name: str, date_from: datetime, date_to: datetime, dismissed: list[int]
    ) -> None:
        backfill_team_rank_days(self.team.id, _DAY - timedelta(days=1), ANCHOR_VERSION)
        excluded_ids = [self.rows[index].id for index in dismissed]
        ranked = ReplayObservation.objects.filter(
            team_id=self.team.id,
            status=ObservationStatus.SUCCEEDED,
            created_at__gte=date_from,
            created_at__lte=date_to,
            watch_rank__anchor_version=ANCHOR_VERSION,
        ).exclude(id__in=excluded_ids)

        counts = scanner_rank_counts(
            ranked, self.team.id, ANCHOR_VERSION, [self.scanner.id], date_from, date_to, excluded_ids
        )

        assert counts.get(self.scanner.id, 0) == ranked.count()

    def test_recount_replaces_wrong_and_stale_days(self) -> None:
        for day, count in [(_DAY.date(), 40), ((_DAY - timedelta(days=1)).date(), 9)]:
            ReplayScannerRankDay.objects.create(
                team=self.team, scanner=self.scanner, anchor_version=ANCHOR_VERSION, day=day, observation_count=count
            )

        backfill_team_rank_days(self.team.id, _DAY - timedelta(days=1), ANCHOR_VERSION)

        assert list(
            ReplayScannerRankDay.objects.for_team(self.team.id).order_by("day").values_list("day", "observation_count")
        ) == [
            (_DAY.date(), 2),
            ((_DAY + timedelta(days=1)).date(), 1),
            ((_DAY + timedelta(days=2)).date(), 1),
            ((_DAY + timedelta(days=3)).date(), 1),
            ((_DAY + timedelta(days=4)).date(), 1),
            ((_DAY + timedelta(days=5)).date(), 1),
        ]
