import datetime as dt

import pytest
from posthog.test.base import BaseTest, ClickhouseTestMixin
from unittest.mock import patch

from django.utils import timezone

from parameterized import parameterized

from posthog.clickhouse.client import sync_execute
from posthog.models import Team
from posthog.session_recordings.queries.test.session_replay_sql import produce_replay_summary
from posthog.session_recordings.sql.session_replay_event_sql import TRUNCATE_SESSION_REPLAY_EVENTS_TABLE_SQL

from products.replay_vision.backend.models.replay_scanner import ReplayScanner, SamplingMode, ScannerModel, ScannerType
from products.replay_vision.backend.queries.scanner_candidate_query import MIN_SAMPLING_RATE
from products.replay_vision.backend.sampling_mode_retirement import retire_sampling_modes, retired_sampling_rate


@pytest.mark.parametrize(
    "rate,share,expected",
    [
        (0.5, 0.4, 0.2),
        (1.0, 1.0, 1.0),
        (0.3333, 0.5, 0.1666),
        (0.001, 0.01, MIN_SAMPLING_RATE),
        (0.0, 0.5, 0.0),
    ],
)
def test_retired_sampling_rate(rate: float, share: float, expected: float) -> None:
    assert retired_sampling_rate(rate, share) == pytest.approx(expected)


class TestRetireSamplingModes(ClickhouseTestMixin, BaseTest):
    def setUp(self) -> None:
        super().setUp()
        sync_execute(TRUNCATE_SESSION_REPLAY_EVENTS_TABLE_SQL())
        self.small_team = Team.objects.create(organization=self.organization, name="small")

    def _session(self, team: Team, session_id: str, score: float | None) -> None:
        start = timezone.now() - dt.timedelta(hours=2)
        produce_replay_summary(
            team_id=team.id,
            session_id=session_id,
            first_timestamp=start.isoformat(),
            last_timestamp=(start + dt.timedelta(minutes=1)).isoformat(),
            active_milliseconds=30_000,
            surfacing_score=score,
        )

    def _scanner(self, team: Team, mode: str, rate: float) -> ReplayScanner:
        return ReplayScanner.objects.create(
            team=team,
            name=f"{mode}-{team.id}",
            scanner_type=ScannerType.MONITOR,
            scanner_config={"prompt": "p"},
            model=ScannerModel.GEMINI_3_8_FLASH,
            sampling_mode=mode,
            sampling_rate=rate,
        )

    @parameterized.expand(
        [
            ("dry_run", False, False),
            ("apply", True, False),
            # The pooled share still covers every team when one run selects only the small team.
            ("apply_small_team_only", True, True),
        ]
    )
    @patch("products.replay_vision.backend.sampling_mode_retirement.MIN_TEAM_SESSIONS", 5)
    def test_scales_each_rate_by_its_teams_pass_share(self, _name: str, apply: bool, small_team_only: bool) -> None:
        # Focused keeps 0.8 and the unscored session (read as 0.36): 5 of 10. Balanced keeps all 10.
        for i, score in enumerate([0.8] * 4 + [None] + [0.2] * 5):
            self._session(self.team, f"big-{i}", score)
        # Too few sessions for its own share, so the pooled 10 of 12 kept by balanced applies.
        for i in range(2):
            self._session(self.small_team, f"small-{i}", 0.05)
        focused = self._scanner(self.team, SamplingMode.FOCUSED, 0.5)
        balanced = self._scanner(self.team, SamplingMode.BALANCED, 0.5)
        pooled = self._scanner(self.small_team, SamplingMode.BALANCED, 0.6)
        comprehensive = self._scanner(self.team, SamplingMode.COMPREHENSIVE, 0.7)

        retired = retire_sampling_modes(apply=apply, team_ids=[self.small_team.id] if small_team_only else None)

        new_rates = {focused.id: 0.25, balanced.id: 0.5, pooled.id: 0.5}
        selected = {pooled.id} if small_team_only else set(new_rates)
        assert {r.scanner_id: r.pooled_share for r in retired} == {str(pk): pk == pooled.id for pk in selected}
        assert {r.scanner_id: r.new_rate for r in retired} == pytest.approx(
            {str(pk): new_rates[pk] for pk in selected}, abs=1e-4
        )
        before = {focused.id: (SamplingMode.FOCUSED, 0.5), balanced.id: (SamplingMode.BALANCED, 0.5)}
        before[pooled.id] = (SamplingMode.BALANCED, 0.6)
        expected = {
            pk: (SamplingMode.COMPREHENSIVE, new_rates[pk]) if apply and pk in selected else state
            for pk, state in before.items()
        }
        expected[comprehensive.id] = (SamplingMode.COMPREHENSIVE, 0.7)
        stored = {s.id: s for s in ReplayScanner.objects.filter(pk__in=expected)}
        assert {pk: s.sampling_mode for pk, s in stored.items()} == {pk: mode for pk, (mode, _) in expected.items()}
        assert {pk: s.sampling_rate for pk, s in stored.items()} == pytest.approx(
            {pk: rate for pk, (_, rate) in expected.items()}, abs=1e-4
        )
