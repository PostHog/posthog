from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from posthog.test.base import BaseTest

from django.test import SimpleTestCase

from parameterized import parameterized

from products.signals.backend.emission.fetch_window import complete_fetch, fetch_records, replay_window_start
from products.signals.backend.emission.registry import SignalEmitterOutput, SignalSourceTableConfig
from products.signals.backend.filter_expression import FilterValidationError
from products.signals.backend.models import SignalSourceFilterState
from products.signals.backend.source_filters import FilterStateKey, record_fetch_failure

EARLY = datetime(2026, 1, 1, tzinfo=UTC)
MIDDLE = datetime(2026, 1, 2, tzinfo=UTC)
LATE = datetime(2026, 1, 3, tzinfo=UTC)
FILTERED: dict[str, object] = {"hogql_filter": {}}


class TestReplayWindowStart(SimpleTestCase):
    @parameterized.expand(
        [
            ("nothing_pending", MIDDLE, None, None, MIDDLE),
            ("untracked_first_sync", None, None, None, None),
            ("tracked_first_sync", None, None, MIDDLE, MIDDLE),
            ("pending_before_last_sync", LATE, EARLY, None, EARLY),
            ("pending_after_last_sync", EARLY, LATE, None, EARLY),
            ("first_sync_with_pending", None, LATE, MIDDLE, MIDDLE),
        ]
    )
    def test_replay_window_start(
        self,
        _name: str,
        last_synced_at: datetime | None,
        pending: datetime | None,
        first_sync_start: datetime | None,
        expected: datetime | None,
    ) -> None:
        assert (
            replay_window_start(last_synced_at=last_synced_at, pending=pending, first_sync_start=first_sync_start)
            == expected
        )


class TestFetchRecords(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.windows: list[str | None] = []
        self.resume_ids: list[str | None] = []
        self.outcomes: list[Exception | int | datetime] = []

    def fetcher(self, team: Any, config: SignalSourceTableConfig, context: dict[str, Any]) -> list[dict[str, Any]]:
        self.windows.append(context["last_synced_at"])
        self.resume_ids.append(context["resume_after_id"])
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        if isinstance(outcome, datetime):
            assert context["drain_window"] is True
            context["window_end"] = outcome.replace(tzinfo=None)
            context["window_capped"] = True
            context["window_end_id"] = "issue-7"
        else:
            context["malformed_count"] = outcome
        return [{"id": 1}]

    def config(self) -> SignalSourceTableConfig:
        return SignalSourceTableConfig(
            source_product="linear",
            source_type="issue",
            emitter=lambda team_id, record: SignalEmitterOutput(
                source_product="linear", source_type="issue", source_id="1", description="", weight=1.0, extra={}
            ),
            record_fetcher=self.fetcher,
            partition_field="created_at",
            fields=("id",),
        )

    def fetch(self, schema_id: UUID, last_synced_at: datetime | None, source_config: object = FILTERED) -> Any:
        context = {
            "table_name": "linear.issues",
            "extra": {},
            "source_config": source_config,
            "last_synced_at": last_synced_at.isoformat() if last_synced_at else None,
        }
        return fetch_records(self.team, self.config(), context, schema_id=schema_id)

    def state(self, schema_id: UUID) -> SignalSourceFilterState:
        return SignalSourceFilterState.objects.for_team(self.team.id).get(schema_id=schema_id)

    def test_failed_window_is_read_again_until_it_is_processed(self) -> None:
        schema_a, schema_b = uuid4(), uuid4()
        self.outcomes = [
            FilterValidationError("catalog_missing", "The filter's catalog version no longer exists."),
            RuntimeError("Code: 60. DB::Exception: secret row value"),
            0,
            2,
        ]

        with self.assertRaises(FilterValidationError):
            self.fetch(schema_a, MIDDLE)
        with self.assertRaises(RuntimeError):
            self.fetch(schema_a, LATE)
        complete_fetch(self.fetch(schema_b, LATE))
        fetched = self.fetch(schema_a, LATE)

        state = self.state(schema_a)
        assert (state.pending_window_start, state.last_error_code, state.last_error_message) == (
            MIDDLE,
            "query_failed",
            "RuntimeError",
        )
        assert self.state(schema_b).pending_window_start is None

        complete_fetch(fetched)

        assert self.windows == [MIDDLE.isoformat(), MIDDLE.isoformat(), LATE.isoformat(), MIDDLE.isoformat()]
        state.refresh_from_db()
        assert (state.pending_window_start, state.last_error_code, state.last_malformed_count) == (None, "", 2)

    def test_capped_batch_resumes_where_it_stopped(self) -> None:
        schema_id = uuid4()
        self.outcomes = [RuntimeError("query failed"), MIDDLE, 0]

        with self.assertRaises(RuntimeError):
            self.fetch(schema_id, EARLY)
        complete_fetch(self.fetch(schema_id, LATE))

        assert self.state(schema_id).pending_window_start == MIDDLE

        complete_fetch(self.fetch(schema_id, LATE))

        assert self.windows == [EARLY.isoformat(), EARLY.isoformat(), MIDDLE.isoformat()]
        assert self.resume_ids == [None, None, "issue-7"]
        assert self.state(schema_id).pending_window_start is None

    def test_first_sync_failure_keeps_the_window_it_read(self) -> None:
        schema_id = uuid4()
        self.outcomes = [RuntimeError("query failed")]

        with self.assertRaises(RuntimeError):
            self.fetch(schema_id, None)

        assert self.windows[0] is not None
        assert self.state(schema_id).pending_window_start == datetime.fromisoformat(self.windows[0])

    def test_completion_keeps_an_earlier_window_stored_after_its_fetch(self) -> None:
        schema_id = uuid4()
        self.outcomes = [0]
        fetched = self.fetch(schema_id, MIDDLE)
        key = FilterStateKey(team_id=self.team.id, source_product="linear", source_type="issue", schema_id=schema_id)
        record_fetch_failure(key, window_start=EARLY, error=RuntimeError("query failed"))

        complete_fetch(fetched)

        assert self.state(schema_id).pending_window_start == EARLY

    def test_unfiltered_failure_keeps_no_window(self) -> None:
        self.outcomes = [RuntimeError("query failed")]

        with self.assertRaises(RuntimeError):
            self.fetch(uuid4(), MIDDLE, source_config={})

        assert not SignalSourceFilterState.objects.for_team(self.team.id).exists()
