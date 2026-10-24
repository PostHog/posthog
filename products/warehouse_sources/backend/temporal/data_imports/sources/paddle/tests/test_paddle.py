from collections.abc import Iterator
from datetime import datetime
from typing import Any

import pytest
import time_machine
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.paddle import PaddleSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.paddle.paddle import (
    PADDLE_BASE_URL,
    PaddlePermissionError,
    PaddleResumeConfig,
    _format_paddle_datetime_query_value,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.paddle.source import (
    INVALID_API_KEY_ERROR,
    KEY_CHECK_FAILED_ERROR,
    MISSING_PERMISSIONS_ERROR,
    PaddleSource,
)

SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.paddle.source"


def _response(
    items: list[dict[str, Any]] | None,
    *,
    next_url: str | None = None,
    has_more: bool | None = None,
    drop_data: bool = False,
) -> ScriptedResponse:
    # Real Paddle bodies always carry has_more; default it from next_url so fixture
    # pages terminate the way real responses do (via has_more, not a null next).
    if has_more is None:
        has_more = next_url is not None
    body: dict[str, Any] = {"meta": {"pagination": {"per_page": 200, "next": next_url, "has_more": has_more}}}
    if not drop_data:
        body["data"] = items or []
    return ScriptedResponse(json=body)


EXPLORE_CATALOG = [
    {
        "entity": "transactions.completed",
        "time_dimension": {"intervals": ["day", "week", "month"], "max_lookback_days": 1096},
        "dimensions": [],
        "measures": [
            {"name": "gross_revenue", "type": "currency", "aggs": ["sum"]},
            {"name": "id", "type": "string", "aggs": ["count"]},
        ],
    },
    {
        "entity": "subscriptions",
        "time_dimension": {"intervals": ["month"], "max_lookback_days": 70},
        "dimensions": [],
        "measures": [{"name": "mrr", "type": "currency", "aggs": None}],
    },
]


def _explore_network(request: RecordedRequest) -> ScriptedResponse:
    if request.path.endswith("/metrics/explore/entities"):
        return ScriptedResponse(json={"data": EXPLORE_CATALOG})
    body = request.json()
    measures = [
        {"name": f"{m['agg']}_{m['field']}" if "agg" in m else m["field"], "type": "currency", **m}
        for m in body["measures"]
    ]
    return ScriptedResponse(
        json={
            "data": {
                "entity": body["entity"],
                "interval": body["interval"],
                "currency_code": "USD",
                "updated_at": "2026-08-20T06:00:00Z",
                "fields": {"dimensions": [], "measures": measures},
                "series": [
                    {
                        "dimensions": {},
                        "timeseries": [{"timestamp": body["from"], "measures": {m["name"]: "100" for m in measures}}],
                    }
                ],
            },
            "meta": {"pagination": {"per_page": 5, "next": None, "has_more": False, "estimated_total": 1}},
        }
    )


def _explore_queries(result: Any) -> list[tuple[str, str, str, str]]:
    bodies = [request.json() for request in result.requests if request.method == "POST"]
    return [(body["entity"], body["interval"], body["from"], body["to"]) for body in bodies]


def _driver() -> SourceDriver:
    return SourceDriver(PaddleSource(), PaddleSourceConfig(paddle_api_key="key"))


class TestPagination:
    def test_follows_body_next_url_and_terminates(self) -> None:
        next_url = f"{PADDLE_BASE_URL}/customers?after=c_1"
        result = _driver().run(
            "customers",
            [
                _response([{"id": "c_1"}], next_url=next_url),
                _response([{"id": "c_2"}], next_url=None),
            ],
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["c_1", "c_2"]
        # First request hits the base path with list params; second follows the self-contained next URL.
        assert result.requests[0].param("per_page") == "200"
        assert result.requests[0].param("order_by") == "id[ASC]"
        assert result.requests[0].url.startswith(f"{PADDLE_BASE_URL}/customers?")
        assert result.urls[1] == next_url
        # The next URL already carries every query param, so the follow-up request drops the originals.
        assert result.requests[1].query == {"after": ("c_1",)}


class TestIncremental:
    def test_incremental_field_adds_server_side_filter(self) -> None:
        result = _driver().run(
            "transactions",
            [_response([{"id": "t_1"}])],
            should_use_incremental_field=True,
            db_incremental_field_last_value="2024-01-02T03:04:05Z",
        )

        assert result.raised is None
        assert result.requests[0].param("order_by") == "billed_at[ASC]"
        assert result.requests[0].param("billed_at[GT]") == "2024-01-02T03:04:05Z"


class TestExploreMetrics:
    @pytest.fixture(autouse=True)
    def _frozen_clock(self) -> Iterator[None]:
        with time_machine.travel("2026-08-20T12:00:00Z", tick=False):
            yield

    @pytest.mark.parametrize(
        "inputs, expected_queries",
        [
            (
                # The shortest lookback (70 days) bounds every entity, rounded up to the next month start.
                {},
                [
                    ("subscriptions", "month", "2026-07-01", "2026-08-01"),
                    ("transactions.completed", "day", "2026-07-01", "2026-08-01"),
                    ("subscriptions", "month", "2026-08-01", "2026-08-21"),
                    ("transactions.completed", "day", "2026-08-01", "2026-08-21"),
                ],
            ),
            (
                {"should_use_incremental_field": True, "db_incremental_field_last_value": "2026-08-02T00:00:00Z"},
                [
                    ("subscriptions", "month", "2026-08-01", "2026-08-21"),
                    ("transactions.completed", "day", "2026-08-01", "2026-08-21"),
                ],
            ),
        ],
    )
    def test_queries_each_entity_per_calendar_month(
        self, inputs: dict[str, Any], expected_queries: list[tuple[str, str, str, str]]
    ) -> None:
        result = _driver().run("explore_metrics", _explore_network, **inputs)

        assert result.raised is None
        assert _explore_queries(result) == expected_queries
        posts = [request.json() for request in result.requests if request.method == "POST"]
        assert posts[0]["measures"] == [{"field": "mrr"}]
        assert posts[1]["measures"] == [{"field": "gross_revenue", "agg": "sum"}, {"field": "id", "agg": "count"}]
        assert {
            "entity": "transactions.completed",
            "interval": "day",
            "timestamp": f"{expected_queries[1][2]}T00:00:00Z",
            "measure": "sum_gross_revenue",
            "field": "gross_revenue",
            "agg": "sum",
            "value_type": "currency",
            "value": "100",
            "currency_code": "USD",
            "updated_at": "2026-08-20T06:00:00Z",
        } in result.rows
        assert len(result.rows) == 3 * len(expected_queries) // 2
        assert result.saved_states[-1] == PaddleResumeConfig()

    def test_resume_continues_at_saved_window_and_entity(self) -> None:
        result = _driver().run(
            "explore_metrics",
            _explore_network,
            resume_state=PaddleResumeConfig(explore_window_start="2026-08-01", explore_entity="transactions.completed"),
        )

        assert result.raised is None
        assert _explore_queries(result) == [("transactions.completed", "day", "2026-08-01", "2026-08-21")]


class TestResume:
    def test_checkpoint_saved_on_last_page_terminates_on_resume(self) -> None:
        # A checkpoint saved while looping on the final page points at that page.
        # The resumed fetch sees has_more=false, completes, and writes the empty
        # terminal marker instead of re-saving the same URL.
        saved_url = f"{PADDLE_BASE_URL}/customers?after=c_9"
        result = _driver().run(
            "customers",
            [_response([], next_url=saved_url, has_more=False)],
            resume_state=PaddleResumeConfig(next_url=saved_url),
        )

        assert result.raised is None
        assert result.rows == []
        assert result.urls == [saved_url]
        assert result.saved_states == [PaddleResumeConfig(next_url="")]


class TestValidateCredentials:
    def test_permission_error_on_403(self) -> None:
        with scripted_network([ScriptedResponse(status=403)]) as network:
            with pytest.raises(PaddlePermissionError, match="Missing permissions for"):
                validate_credentials("key")
        assert network.requests_log[0].headers["authorization"] == "Bearer key"

    @pytest.mark.parametrize(
        "table_name, expected_paths",
        [
            # A key without `metrics.read` must still connect, so the create-time check skips Explore.
            (
                None,
                ["/customers", "/discounts", "/prices", "/products", "/subscriptions", "/transactions", "/adjustments"],
            ),
            ("explore_metrics", ["/metrics/explore/entities"]),
        ],
    )
    def test_probed_paths(self, table_name: str | None, expected_paths: list[str]) -> None:
        with scripted_network(always(ScriptedResponse(status=200))) as network:
            assert validate_credentials("key", table_name) is True
        assert [request.path for request in network.requests_log] == expected_paths


class TestSourceValidateCredentials:
    def _validate(self) -> tuple[bool, str | None]:
        return PaddleSource().validate_credentials(PaddleSourceConfig(paddle_api_key="key"), team_id=1)

    def test_ok(self) -> None:
        with scripted_network(always(ScriptedResponse(status=200))):
            assert self._validate() == (True, None)

    @pytest.mark.parametrize(
        "status_code,expected",
        [(401, INVALID_API_KEY_ERROR), (403, MISSING_PERMISSIONS_ERROR)],
    )
    def test_refusal_message(self, status_code: int, expected: str) -> None:
        with scripted_network([ScriptedResponse(status=status_code)]):
            valid, message = self._validate()

        assert valid is False
        assert message == expected
        # The wizard shows this string and nothing else, so it has to name a next step and must
        # not carry the probed endpoint name the permission error reports.
        assert "reconnect" in message
        assert "Missing permissions" not in message

    def test_unreachable_paddle_does_not_blame_the_key(self) -> None:
        with scripted_network(always(ConnectionError("boom"))):
            valid, message = self._validate()

        # Paddle never judged the key, so telling the customer to replace it would send them
        # rotating a key that works.
        assert valid is False
        assert message == KEY_CHECK_FAILED_ERROR

    @mock.patch(f"{SOURCE_MODULE}.validate_paddle_credentials", side_effect=RuntimeError("probe blew up"))
    @mock.patch(f"{SOURCE_MODULE}.capture_exception")
    def test_unexpected_failure_is_captured_not_shown(self, mock_capture, _mock_validate) -> None:
        valid, message = self._validate()

        assert valid is False
        assert message == KEY_CHECK_FAILED_ERROR
        assert "probe blew up" not in message
        assert mock_capture.call_count == 1


class TestFormatDatetimeQueryValue:
    @pytest.mark.parametrize(
        "value, expected",
        [
            ("2024-01-01T00:00:00Z", "2024-01-01T00:00:00Z"),
            # Paddle's billed_at[GT] filter is UTC-only, so an offset timestamp must be normalized.
            ("2024-01-01T02:00:00+02:00", "2024-01-01T00:00:00Z"),
            (datetime(2024, 1, 1, 0, 0, 0), "2024-01-01T00:00:00Z"),
        ],
    )
    def test_normalizes_to_utc_z(self, value: Any, expected: str) -> None:
        assert _format_paddle_datetime_query_value(value) == expected
