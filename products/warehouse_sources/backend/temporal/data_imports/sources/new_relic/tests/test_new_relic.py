from datetime import UTC, date, datetime
from typing import Any

import pytest
from freezegun import freeze_time
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.new_relic.new_relic import (
    DEFAULT_LOOKBACK_DAYS,
    DEFAULT_WINDOW_MS,
    INGEST_LAG_BUFFER_MS,
    MIN_WINDOW_MS,
    NRQL_ROW_LIMIT,
    NewRelicGraphQLError,
    NewRelicResumeConfig,
    NewRelicRetryableError,
    _execute_graphql,
    _fetch_event_window,
    _iter_alert_conditions,
    _iter_alert_policies,
    _iter_entities,
    _to_epoch_ms,
    get_graphql_url,
    get_rows,
    new_relic_source,
    validate_credentials,
)

ACCOUNT_ID = 1234567
NEW_RELIC_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.new_relic.new_relic"


class FakeResumableSourceManager:
    def __init__(self, state: NewRelicResumeConfig | None = None) -> None:
        self.state = state
        self.saved: list[NewRelicResumeConfig] = []

    def can_resume(self) -> bool:
        return self.state is not None

    def load_state(self) -> NewRelicResumeConfig | None:
        return self.state

    def save_state(self, state: NewRelicResumeConfig) -> None:
        self.saved.append(state)
        self.state = state


def _nrql_data(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {"actor": {"account": {"nrql": {"results": rows}}}}


def _parse_since_until(nrql: str) -> tuple[int, int]:
    parts = nrql.split()
    return int(parts[parts.index("SINCE") + 1]), int(parts[parts.index("UNTIL") + 1])


class RecordingNrqlExecutor:
    """Fake GraphQL executor that serves NRQL queries from a rows_for(start, until) callback."""

    def __init__(self, rows_for: Any) -> None:
        self.rows_for = rows_for
        self.queries: list[str] = []

    def __call__(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        nrql = variables["nrql"]
        self.queries.append(nrql)
        start_ms, until_ms = _parse_since_until(nrql)
        return _nrql_data(self.rows_for(start_ms, until_ms))


class TestToEpochMs:
    @parameterized.expand(
        [
            ("aware_datetime", datetime(2026, 1, 1, tzinfo=UTC), 1767225600000),
            ("naive_datetime_treated_as_utc", datetime(2026, 1, 1), 1767225600000),
            ("date_value", date(2026, 1, 1), 1767225600000),
            ("epoch_ms_int_passthrough", 1767225600000, 1767225600000),
            ("epoch_ms_float", 1767225600000.9, 1767225600000),
        ]
    )
    def test_converts_to_epoch_ms(self, _name: str, value: Any, expected: int) -> None:
        assert _to_epoch_ms(value) == expected

    def test_unsupported_type_raises(self) -> None:
        with pytest.raises(ValueError):
            _to_epoch_ms("2026-01-01")


class TestGetGraphqlUrl:
    @parameterized.expand(
        [
            ("us", "US", "https://api.newrelic.com/graphql"),
            ("eu", "EU", "https://api.eu.newrelic.com/graphql"),
            ("lowercase_eu", "eu", "https://api.eu.newrelic.com/graphql"),
            ("none_defaults_to_us", None, "https://api.newrelic.com/graphql"),
            ("unknown_defaults_to_us", "MARS", "https://api.newrelic.com/graphql"),
        ]
    )
    def test_region_maps_to_url(self, _name: str, region: str | None, expected: str) -> None:
        assert get_graphql_url(region) == expected


class TestExecuteGraphql:
    def _response(self, status_code: int = 200, body: dict | None = None) -> MagicMock:
        response = MagicMock()
        response.status_code = status_code
        response.ok = status_code < 400
        response.json.return_value = body if body is not None else {}
        if status_code >= 400:
            response.raise_for_status.side_effect = requests.HTTPError(response=response)
        return response

    def _execute(self, response: MagicMock) -> dict[str, Any]:
        session = MagicMock()
        session.post.return_value = response
        # Call the undecorated function so retryable-error tests don't sit through backoff.
        return _execute_graphql.__wrapped__(session, "https://api.newrelic.com/graphql", "query", {}, MagicMock())

    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 502)])
    def test_retryable_status_codes_raise_retryable_error(self, _name: str, status_code: int) -> None:
        with pytest.raises(NewRelicRetryableError):
            self._execute(self._response(status_code=status_code))

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_client_errors_raise_http_error(self, _name: str, status_code: int) -> None:
        with pytest.raises(requests.HTTPError):
            self._execute(self._response(status_code=status_code))

    def test_graphql_errors_raise(self) -> None:
        body = {"errors": [{"message": "authentication required"}]}
        with pytest.raises(NewRelicGraphQLError, match="authentication required"):
            self._execute(self._response(body=body))

    @parameterized.expand(
        [
            ("timeout", "NRQL query timeout after 120 seconds"),
            ("deadline", "Deadline exceeded"),
            ("throttled", "Too many requests"),
        ]
    )
    def test_transient_graphql_errors_are_retryable(self, _name: str, message: str) -> None:
        body = {"errors": [{"message": message}]}
        with pytest.raises(NewRelicRetryableError):
            self._execute(self._response(body=body))

    def test_returns_data_on_success(self) -> None:
        body = {"data": {"actor": {"account": {"id": ACCOUNT_ID}}}}
        assert self._execute(self._response(body=body)) == body["data"]


class TestFetchEventWindow:
    def test_yields_rows_sorted_ascending_with_datetime_timestamps(self) -> None:
        executor = RecordingNrqlExecutor(
            lambda start, until: [{"timestamp": 2000, "name": "b"}, {"timestamp": 1000, "name": "a"}]
        )

        batches = list(_fetch_event_window(executor, ACCOUNT_ID, "Transaction", 0, 10_000, MagicMock()))

        assert len(batches) == 1
        assert [row["name"] for row in batches[0]] == ["a", "b"]
        assert batches[0][0]["timestamp"] == datetime.fromtimestamp(1, tz=UTC)
        assert "SELECT * FROM Transaction SINCE 0 UNTIL 10000" in executor.queries[0]

    def test_empty_window_yields_nothing(self) -> None:
        executor = RecordingNrqlExecutor(lambda start, until: [])
        assert list(_fetch_event_window(executor, ACCOUNT_ID, "Transaction", 0, 10_000, MagicMock())) == []

    def test_full_window_splits_recursively_until_under_cap(self) -> None:
        full_page = [{"timestamp": 1} for _ in range(NRQL_ROW_LIMIT)]

        def rows_for(start: int, until: int) -> list[dict[str, Any]]:
            # The whole window is over the cap; each half fits.
            return full_page if (until - start) > 5_000 else [{"timestamp": start}]

        executor = RecordingNrqlExecutor(rows_for)
        batches = list(_fetch_event_window(executor, ACCOUNT_ID, "Transaction", 0, 10_000, MagicMock()))

        assert [_parse_since_until(q) for q in executor.queries] == [(0, 10_000), (0, 5_000), (5_000, 10_000)]
        assert [row["timestamp"] for batch in batches for row in batch] == [
            datetime.fromtimestamp(0, tz=UTC),
            datetime.fromtimestamp(5, tz=UTC),
        ]

    def test_minimum_window_at_cap_yields_with_truncation_warning(self) -> None:
        full_page = [{"timestamp": i} for i in range(NRQL_ROW_LIMIT)]
        executor = RecordingNrqlExecutor(lambda start, until: full_page)
        logger = MagicMock()

        batches = list(_fetch_event_window(executor, ACCOUNT_ID, "Transaction", 0, MIN_WINDOW_MS, logger))

        assert len(executor.queries) == 1
        assert len(batches) == 1
        assert len(batches[0]) == NRQL_ROW_LIMIT
        logger.warning.assert_called_once()


@freeze_time("2026-01-02 12:00:00")
class TestGetEventRows:
    def _now_ms(self) -> int:
        return int(datetime(2026, 1, 2, 12, tzinfo=UTC).timestamp() * 1000)

    def _get_rows(
        self,
        executor: RecordingNrqlExecutor,
        manager: FakeResumableSourceManager,
        should_use_incremental_field: bool = False,
        db_incremental_field_last_value: Any = None,
    ) -> list[list[dict[str, Any]]]:
        with patch(f"{NEW_RELIC_MODULE}._make_executor", return_value=executor):
            return list(
                get_rows(
                    api_key="NRAK-x",
                    account_id=ACCOUNT_ID,
                    region="US",
                    endpoint="transactions",
                    logger=MagicMock(),
                    resumable_source_manager=manager,  # type: ignore[arg-type]
                    should_use_incremental_field=should_use_incremental_field,
                    db_incremental_field_last_value=db_incremental_field_last_value,
                )
            )

    def test_incremental_sync_starts_one_ms_past_the_watermark(self) -> None:
        watermark = datetime(2026, 1, 2, 10, tzinfo=UTC)
        executor = RecordingNrqlExecutor(lambda start, until: [])

        self._get_rows(
            executor,
            FakeResumableSourceManager(),
            should_use_incremental_field=True,
            db_incremental_field_last_value=watermark,
        )

        first_since, _ = _parse_since_until(executor.queries[0])
        assert first_since == int(watermark.timestamp() * 1000) + 1

    def test_first_sync_reaches_back_the_default_lookback(self) -> None:
        executor = RecordingNrqlExecutor(lambda start, until: [])

        self._get_rows(executor, FakeResumableSourceManager())

        first_since, _ = _parse_since_until(executor.queries[0])
        assert first_since == self._now_ms() - DEFAULT_LOOKBACK_DAYS * 24 * 60 * 60 * 1000

    def test_until_excludes_the_ingest_lag_buffer(self) -> None:
        watermark = datetime(2026, 1, 2, 11, 30, tzinfo=UTC)
        executor = RecordingNrqlExecutor(lambda start, until: [])

        self._get_rows(
            executor,
            FakeResumableSourceManager(),
            should_use_incremental_field=True,
            db_incremental_field_last_value=watermark,
        )

        _, last_until = _parse_since_until(executor.queries[-1])
        assert last_until == self._now_ms() - INGEST_LAG_BUFFER_MS

    def test_watermark_past_until_makes_no_queries(self) -> None:
        watermark = datetime(2026, 1, 2, 11, 59, tzinfo=UTC)  # inside the ingest-lag buffer
        executor = RecordingNrqlExecutor(lambda start, until: [])

        batches = self._get_rows(
            executor,
            FakeResumableSourceManager(),
            should_use_incremental_field=True,
            db_incremental_field_last_value=watermark,
        )

        assert batches == []
        assert executor.queries == []

    def test_saves_resume_state_after_each_window_except_the_last(self) -> None:
        watermark = datetime(2026, 1, 2, tzinfo=UTC)  # ~12h of data → 2 windows
        executor = RecordingNrqlExecutor(lambda start, until: [{"timestamp": start}])
        manager = FakeResumableSourceManager()

        batches = self._get_rows(
            executor,
            manager,
            should_use_incremental_field=True,
            db_incremental_field_last_value=watermark,
        )

        assert len(batches) == 2
        assert [state.window_start_ms for state in manager.saved] == [
            int(watermark.timestamp() * 1000) + 1 + DEFAULT_WINDOW_MS
        ]

    def test_resumes_from_saved_window_start(self) -> None:
        resume_start = int(datetime(2026, 1, 2, 11, tzinfo=UTC).timestamp() * 1000)
        executor = RecordingNrqlExecutor(lambda start, until: [])
        manager = FakeResumableSourceManager(state=NewRelicResumeConfig(window_start_ms=resume_start))

        self._get_rows(
            executor,
            manager,
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
        )

        first_since, _ = _parse_since_until(executor.queries[0])
        assert first_since == resume_start


class TestEntityStyleIterators:
    def test_entities_paginate_until_cursor_exhausted(self) -> None:
        pages = [
            {"entities": [{"guid": "g1"}], "nextCursor": "cursor-2"},
            {"entities": [{"guid": "g2"}], "nextCursor": None},
        ]
        calls: list[str | None] = []

        def execute(query: str, variables: dict[str, Any]) -> dict[str, Any]:
            calls.append(variables["cursor"])
            return {"actor": {"entitySearch": {"results": pages[len(calls) - 1]}}}

        batches = list(_iter_entities(execute, ACCOUNT_ID))

        assert batches == [[{"guid": "g1"}], [{"guid": "g2"}]]
        assert calls == [None, "cursor-2"]

    def test_alert_policies_paginate_and_scope_to_account(self) -> None:
        pages = [
            {"policies": [{"id": "1"}], "nextCursor": "next"},
            {"policies": [{"id": "2"}], "nextCursor": None},
        ]
        calls: list[dict[str, Any]] = []

        def execute(query: str, variables: dict[str, Any]) -> dict[str, Any]:
            calls.append(variables)
            return {"actor": {"account": {"alerts": {"policiesSearch": pages[len(calls) - 1]}}}}

        batches = list(_iter_alert_policies(execute, ACCOUNT_ID))

        assert batches == [[{"id": "1"}], [{"id": "2"}]]
        assert all(call["accountId"] == ACCOUNT_ID for call in calls)

    def test_alert_conditions_flatten_nested_nrql_query(self) -> None:
        page = {
            "nrqlConditions": [{"id": "1", "name": "cond", "nrql": {"query": "SELECT count(*) FROM Transaction"}}],
            "nextCursor": None,
        }

        def execute(query: str, variables: dict[str, Any]) -> dict[str, Any]:
            return {"actor": {"account": {"alerts": {"nrqlConditionsSearch": page}}}}

        batches = list(_iter_alert_conditions(execute, ACCOUNT_ID))

        assert batches == [[{"id": "1", "name": "cond", "nrql_query": "SELECT count(*) FROM Transaction"}]]


class TestValidateCredentials:
    def _validate(self, execute: Any) -> tuple[bool, str | None]:
        with patch(f"{NEW_RELIC_MODULE}._make_executor", return_value=execute):
            return validate_credentials("NRAK-x", ACCOUNT_ID, "US")

    def test_valid_key_with_account_access(self) -> None:
        is_valid, error = self._validate(
            lambda query, variables: {"actor": {"account": {"id": ACCOUNT_ID, "name": "acme"}}}
        )
        assert is_valid is True
        assert error is None

    def test_valid_key_without_account_access(self) -> None:
        is_valid, error = self._validate(lambda query, variables: {"actor": {"account": None}})
        assert is_valid is False
        assert error is not None and str(ACCOUNT_ID) in error

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403)])
    def test_auth_http_errors_report_invalid_key(self, _name: str, status_code: int) -> None:
        response = MagicMock()
        response.status_code = status_code

        def execute(query: str, variables: dict[str, Any]) -> dict[str, Any]:
            raise requests.HTTPError(response=response)

        is_valid, error = self._validate(execute)
        assert is_valid is False
        assert error is not None and "API key" in error

    def test_graphql_error_is_reported(self) -> None:
        def execute(query: str, variables: dict[str, Any]) -> dict[str, Any]:
            raise NewRelicGraphQLError("boom")

        is_valid, error = self._validate(execute)
        assert is_valid is False
        assert error is not None and "boom" in error


class TestNewRelicSourceResponse:
    def test_event_endpoint_is_append_only_with_datetime_partitions(self) -> None:
        response = new_relic_source(
            api_key="NRAK-x",
            account_id=ACCOUNT_ID,
            region="US",
            endpoint="transactions",
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )

        assert response.name == "transactions"
        assert response.primary_keys is None
        assert response.sort_mode == "asc"
        assert response.partition_mode == "datetime"
        assert response.partition_format == "week"
        assert response.partition_keys == ["timestamp"]

    @parameterized.expand(
        [
            ("entities", ["guid"]),
            ("alert_policies", ["id"]),
            ("alert_conditions", ["id"]),
        ]
    )
    def test_entity_endpoints_have_primary_keys_and_no_partitions(self, endpoint: str, primary_keys: list[str]) -> None:
        response = new_relic_source(
            api_key="NRAK-x",
            account_id=ACCOUNT_ID,
            region="US",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )

        assert response.primary_keys == primary_keys
        assert response.partition_mode is None
        assert response.partition_keys is None

    def test_entity_endpoint_rows_flow_through_get_rows(self) -> None:
        def execute(query: str, variables: dict[str, Any]) -> dict[str, Any]:
            return {"actor": {"entitySearch": {"results": {"entities": [{"guid": "g1"}], "nextCursor": None}}}}

        with patch(f"{NEW_RELIC_MODULE}._make_executor", return_value=execute):
            response = new_relic_source(
                api_key="NRAK-x",
                account_id=ACCOUNT_ID,
                region="US",
                endpoint="entities",
                logger=MagicMock(),
                resumable_source_manager=MagicMock(),
            )
            assert list(response.items()) == [[{"guid": "g1"}]]
