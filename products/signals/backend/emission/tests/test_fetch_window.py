from datetime import UTC, datetime
from typing import Any

from posthog.test.base import BaseTest

from django.test import SimpleTestCase

from parameterized import parameterized

from products.signals.backend.emission.fetch_window import fetch_records, replay_window_start
from products.signals.backend.emission.registry import SignalEmitterOutput, SignalSourceTableConfig
from products.signals.backend.filter_expression import FilterValidationError
from products.signals.backend.models import SignalSourceFilterState

EARLY = datetime(2026, 1, 1, tzinfo=UTC)
MIDDLE = datetime(2026, 1, 2, tzinfo=UTC)
LATE = datetime(2026, 1, 3, tzinfo=UTC)


class TestReplayWindowStart(SimpleTestCase):
    @parameterized.expand(
        [
            ("nothing_pending", MIDDLE, None, MIDDLE),
            ("first_sync_nothing_pending", None, None, None),
            ("pending_before_last_sync", LATE, EARLY, EARLY),
            ("pending_after_last_sync", EARLY, LATE, EARLY),
            ("first_sync_with_pending", None, LATE, MIDDLE),
        ]
    )
    def test_replay_window_start(
        self, _name: str, last_synced_at: datetime | None, pending: datetime | None, expected: datetime | None
    ) -> None:
        assert (
            replay_window_start(last_synced_at=last_synced_at, pending=pending, first_sync_start=lambda: MIDDLE)
            == expected
        )


class TestFetchRecords(BaseTest):
    def test_failed_windows_are_read_again_until_a_fetch_succeeds(self) -> None:
        windows: list[str | None] = []
        outcomes: list[Exception | int] = [
            FilterValidationError("catalog_missing", "The filter's catalog version no longer exists."),
            RuntimeError("Code: 60. DB::Exception: secret row value"),
            2,
        ]

        def fetcher(team: Any, config: SignalSourceTableConfig, context: dict[str, Any]) -> list[dict[str, Any]]:
            windows.append(context["last_synced_at"])
            outcome = outcomes.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            context["malformed_count"] = outcome
            return [{"id": 1}]

        config = SignalSourceTableConfig(
            source_product="linear",
            source_type="issue",
            emitter=lambda team_id, record: SignalEmitterOutput(
                source_product="linear", source_type="issue", source_id="1", description="", weight=1.0, extra={}
            ),
            record_fetcher=fetcher,
            partition_field="created_at",
            fields=("id",),
        )
        context = {"table_name": "linear.issues", "extra": {}, "source_config": {"hogql_filter": {}}}

        with self.assertRaises(FilterValidationError):
            fetch_records(self.team, config, {**context, "last_synced_at": MIDDLE.isoformat()})
        with self.assertRaises(RuntimeError):
            fetch_records(self.team, config, {**context, "last_synced_at": LATE.isoformat()})
        state = SignalSourceFilterState.objects.for_team(self.team.id).get(source_product="linear")
        assert (state.pending_window_start, state.last_error_code, state.last_error_message) == (
            MIDDLE,
            "query_failed",
            "RuntimeError",
        )

        assert fetch_records(self.team, config, {**context, "last_synced_at": LATE.isoformat()}) == [{"id": 1}]

        assert windows == [MIDDLE.isoformat(), MIDDLE.isoformat(), MIDDLE.isoformat()]
        state.refresh_from_db()
        assert (state.pending_window_start, state.last_error_code, state.last_malformed_count) == (None, "", 2)

    def test_unfiltered_failure_keeps_no_window(self) -> None:
        def fetcher(team: Any, config: SignalSourceTableConfig, context: dict[str, Any]) -> list[dict[str, Any]]:
            raise RuntimeError("query failed")

        config = SignalSourceTableConfig(
            source_product="zendesk",
            source_type="ticket",
            emitter=lambda team_id, record: None,
            record_fetcher=fetcher,
            partition_field="created_at",
            fields=("id",),
        )

        with self.assertRaises(RuntimeError):
            fetch_records(self.team, config, {"table_name": "t", "extra": {}, "last_synced_at": MIDDLE.isoformat()})

        assert not SignalSourceFilterState.objects.for_team(self.team.id).exists()
