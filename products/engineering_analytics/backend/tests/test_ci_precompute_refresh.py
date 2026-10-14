from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import time_machine
from unittest.mock import MagicMock, patch

from django.core.cache.backends.locmem import LocMemCache
from django.test import SimpleTestCase

from parameterized import parameterized

from products.engineering_analytics.backend.logic import ci_precompute

_MODULE = "products.engineering_analytics.backend.logic.ci_precompute"
_NOW = datetime(2026, 10, 14, 12, tzinfo=UTC)
_TEAM: Any = SimpleNamespace(pk=1)


class TestRefreshAfterLoad(SimpleTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.first_created: str | None = "2026-10-04T08:00:00Z"
        self.flag_checks_on = 1000
        self.ensure_stored = MagicMock(return_value=SimpleNamespace(ready=True, errors=[]))
        flag_checks = iter(range(1000))
        source = SimpleNamespace(
            source_id="source",
            repository="posthog/posthog",
            github_workflow_runs="runs",
            github_workflow_jobs="jobs",
            depot_job_attempts=None,
        )
        for patcher in (
            time_machine.travel(_NOW, tick=False),
            patch(f"{_MODULE}.cache", LocMemCache(self.id(), {})),
            patch(f"{_MODULE}.team_flag", side_effect=lambda *_args: next(flag_checks) < self.flag_checks_on),
            patch(f"{_MODULE}.resolve_precompute_sources", return_value=[source]),
            patch(f"{_MODULE}.Database.create_for"),
            patch(f"{_MODULE}.create_default_modifiers_for_team"),
            patch(
                f"{_MODULE}.execute_hogql_query",
                side_effect=lambda **_kwargs: SimpleNamespace(results=[(self.first_created,)]),
            ),
            patch(f"{_MODULE}.ensure_stored", self.ensure_stored),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    @parameterized.expand(
        [
            ("stored", SimpleNamespace(ready=True, errors=[]), True),
            ("out_of_budget", SimpleNamespace(ready=False, errors=["timeout"], timed_out=True), True),
            (
                "insert_failed",
                SimpleNamespace(ready=False, errors=["Code: 241. Memory limit exceeded"], timed_out=False),
                False,
            ),
            ("refresh_raised", RuntimeError("connection lost"), False),
        ]
    )
    def test_next_load_refreshes_unless_an_insert_failed(
        self, _name: str, outcome: Any, next_load_refreshes: bool
    ) -> None:
        if isinstance(outcome, Exception):
            self.ensure_stored.side_effect = outcome
        else:
            self.ensure_stored.return_value = outcome
        ci_precompute.mark_in_use(_TEAM)
        try:
            ci_precompute.refresh_after_load(_TEAM)
        except RuntimeError:
            pass
        first_load_calls = self.ensure_stored.call_count
        self.ensure_stored.side_effect = None
        self.ensure_stored.return_value = SimpleNamespace(ready=True, errors=[])
        ci_precompute.refresh_after_load(_TEAM)

        assert (self.ensure_stored.call_count > first_load_calls) is next_load_refreshes

    @parameterized.expand(
        [
            ("in_use", True, 1000, 2),
            ("not_read_within_the_hour", False, 1000, 0),
            # The load's own check, then the runs table's history lookup and its one insert.
            ("flag_turned_off_mid_refresh", True, 3, 1),
        ]
    )
    def test_a_load_stores_days_only_while_the_team_is_read_and_flagged(
        self, _name: str, in_use: bool, flag_checks_on: int, inserts: int
    ) -> None:
        self.flag_checks_on = flag_checks_on
        if in_use:
            ci_precompute.mark_in_use(_TEAM)
        ci_precompute.refresh_after_load(_TEAM)

        assert self.ensure_stored.call_count == inserts

    @parameterized.expand(
        [
            (
                "seventy_days_of_history",
                "2026-08-05T10:00:00Z",
                [
                    datetime(2026, 9, 14, 12, tzinfo=UTC),
                    datetime(2026, 8, 15, 12, tzinfo=UTC),
                    datetime(2026, 8, 5, tzinfo=UTC),
                ],
            ),
            ("no_rows", None, []),
        ]
    )
    def test_a_refresh_stores_every_day_of_history_newest_first(
        self, _name: str, first_created: str | None, runs_since: list[datetime]
    ) -> None:
        self.first_created = first_created
        ci_precompute.mark_in_use(_TEAM)
        ci_precompute.refresh_after_load(_TEAM)

        stored_since = [
            call.kwargs["since"]
            for call in self.ensure_stored.call_args_list
            if call.args[0] == ci_precompute.STORED_RUNS
        ]
        assert stored_since == runs_since
