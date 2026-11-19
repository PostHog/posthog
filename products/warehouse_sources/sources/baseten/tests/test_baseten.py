import datetime
from typing import Any

import pytest
import time_machine

from products.warehouse_sources.sources.baseten._config import BasetenSourceConfig
from products.warehouse_sources.sources.baseten.baseten import BasetenResumeConfig, validate_credentials
from products.warehouse_sources.sources.baseten.settings import BASETEN_ENDPOINTS, ENDPOINTS
from products.warehouse_sources.sources.baseten.source import BasetenSource
from products.warehouse_sources.sources.sdk.testing import ScriptedResponse, SourceDriver, always, scripted_network


def _driver() -> SourceDriver:
    return SourceDriver(BasetenSource(), BasetenSourceConfig(api_key="test-key"))


def _page(body: dict[str, Any], status: int = 200) -> ScriptedResponse:
    return ScriptedResponse(status=status, json=body)


class TestTopLevelEndpoints:
    def test_instance_type_prices_flattened(self) -> None:
        body = {
            "instance_types": [
                # Nested object lifts into the root; root-level siblings win on collision.
                {"instance_type": {"id": "gpu-1", "name": "A100", "price": 999}, "price": 0.5},
                # Rows without the nested key pass through untouched.
                {"id": "plain"},
            ]
        }
        result = _driver().run("instance_type_prices", [_page(body)])

        assert result.raised is None
        assert result.rows == [{"id": "gpu-1", "name": "A100", "price": 0.5}, {"id": "plain"}]


class TestCursorPagination:
    def test_pages_until_has_more_false_and_saves_cursor(self) -> None:
        result = _driver().run(
            "users",
            [
                _page({"items": [{"user_id": "u1"}], "pagination": {"has_more": True, "cursor": "c1"}}),
                _page({"items": [{"user_id": "u2"}], "pagination": {"has_more": True, "cursor": "c2"}}),
                _page({"items": [{"user_id": "u3"}], "pagination": {"has_more": False, "cursor": None}}),
            ],
        )

        assert result.raised is None
        assert result.rows == [{"user_id": "u1"}, {"user_id": "u2"}, {"user_id": "u3"}]
        # First request has no cursor; later requests carry the prior page's cursor.
        assert result.params("cursor") == [None, "c1", "c2"]
        assert result.params("limit") == ["100", "100", "100"]
        assert result.saved_states == [BasetenResumeConfig(cursor="c1"), BasetenResumeConfig(cursor="c2")]

    def test_has_more_false_stops_even_if_cursor_echoed(self) -> None:
        # A cursor echoed on the terminal page must not cause a loop.
        result = _driver().run(
            "users", [_page({"items": [{"user_id": "u1"}], "pagination": {"has_more": False, "cursor": "stale"}})]
        )

        assert result.raised is None
        assert result.rows == [{"user_id": "u1"}]
        assert result.paths == ["/v1/users"]

    def test_resume_seeds_saved_cursor(self) -> None:
        result = _driver().run(
            "users",
            [_page({"items": [{"user_id": "u9"}], "pagination": {}})],
            resume_state=BasetenResumeConfig(cursor="resumed-cursor"),
        )

        assert result.raised is None
        assert result.requests[0].param("cursor") == "resumed-cursor"

    def test_does_not_load_state_when_cannot_resume(self) -> None:
        result = _driver().run("users", [_page({"items": [], "pagination": {}})])

        assert result.raised is None
        assert result.params("cursor") == [None]


class TestAuditLogs:
    @pytest.mark.parametrize(
        "incremental,last_value,expected_start",
        [
            pytest.param(False, None, None, id="full_refresh"),
            pytest.param(True, None, None, id="first_incremental_run"),
            pytest.param(
                True, datetime.datetime(2026, 3, 1, 12, 0, tzinfo=datetime.UTC), "1772366400000", id="datetime"
            ),
            pytest.param(True, datetime.datetime(2026, 3, 1, 12, 0), "1772366400000", id="naive_datetime"),
            pytest.param(True, "2026-03-01T12:00:00Z", "1772366400000", id="iso_string"),
            pytest.param(True, datetime.date(2026, 3, 1), "1772323200000", id="date"),
            pytest.param(True, "not-a-date", None, id="unparseable_string"),
        ],
    )
    def test_request_shaping(self, incremental: bool, last_value: Any, expected_start: str | None) -> None:
        result = _driver().run(
            "audit_logs",
            [
                _page({"items": [{"id": "a1"}], "pagination": {"has_more": True, "cursor": "c1"}}),
                _page({"items": [{"id": "a2"}], "pagination": {"has_more": False}}),
            ],
            incremental_field="created" if incremental else None,
            db_incremental_field_last_value=last_value,
        )

        assert result.raised is None
        assert result.rows == [{"id": "a1"}, {"id": "a2"}]
        assert result.paths == ["/v1/audit_logs", "/v1/audit_logs"]
        assert result.params("start_epoch_millis") == [expected_start, expected_start]
        assert result.params("direction") == ["ASC", "ASC"]
        assert result.params("cursor") == [None, "c1"]
        assert result.response is not None
        assert result.response.sort_mode is None


def _usage_summary(day: str) -> dict[str, Any]:
    return {
        "dedicated_usage": {
            "subtotal": "13.50",
            "credits_used": "5.00",
            "total": "8.50",
            "minutes": 30,
            "breakdown": [
                {
                    "billable_resource": {"id": "dep1", "model_name": "whisper", "team_id": "t1", "team_name": "Core"},
                    "daily": [{"date": day, "subtotal": "12.50", "minutes": 30, "inference_requests": 7}],
                },
                {"billable_resource": {"id": "dep2"}, "daily": []},
                # An item without a resource id cannot be keyed and is dropped.
                {"billable_resource": {"name": "orphan"}, "daily": [{"date": day, "subtotal": "1"}]},
            ],
        },
        "training_usage": None,
        "model_apis_usage": {
            "subtotal": "0.30",
            "credits_used": "0",
            "total": "0.30",
            # Multi-team organizations split one model's usage by team.
            "breakdown": [
                {
                    "model_name": "llama-example",
                    "team_id": "t1",
                    "team_name": "Core",
                    "daily": [{"date": day, "subtotal": "0.10"}, {"subtotal": "9"}],
                },
                {
                    "model_name": "llama-example",
                    "team_id": "t2",
                    "team_name": "Labs",
                    "daily": [{"date": day, "subtotal": "0.20"}],
                },
                {"model_name": "mistral-example", "daily": [{"date": day, "subtotal": "0.05"}]},
            ],
        },
    }


def _model_api_row(day: str, resource_id: str, model: str, subtotal: str, team: tuple[str, str] | None):
    return {
        "date": day,
        "subtotal": subtotal,
        "usage_type": "model_apis",
        "resource_id": resource_id,
        "billable_resource": None,
        "model_name": model,
        "model_family": None,
        "team_id": team[0] if team else None,
        "team_name": team[1] if team else None,
    }


def _usage_rows_for(day: str) -> list[dict[str, Any]]:
    return [
        {
            "date": day,
            "subtotal": "12.50",
            "minutes": 30,
            "inference_requests": 7,
            "usage_type": "dedicated",
            "resource_id": "dep1",
            "billable_resource": {"id": "dep1", "model_name": "whisper", "team_id": "t1", "team_name": "Core"},
            "model_name": "whisper",
            "model_family": None,
            "team_id": "t1",
            "team_name": "Core",
        },
        _model_api_row(day, "t1:llama-example", "llama-example", "0.10", ("t1", "Core")),
        _model_api_row(day, "t2:llama-example", "llama-example", "0.20", ("t2", "Labs")),
        _model_api_row(day, "mistral-example", "mistral-example", "0.05", None),
    ]


def _usage_total_rows_for(window_start: str, window_end: str) -> list[dict[str, Any]]:
    return [
        {
            "subtotal": "13.50",
            "credits_used": "5.00",
            "total": "8.50",
            "minutes": 30,
            "usage_type": "dedicated",
            "window_start": window_start,
            "window_end": window_end,
        },
        {
            "subtotal": "0.30",
            "credits_used": "0",
            "total": "0.30",
            "usage_type": "model_apis",
            "window_start": window_start,
            "window_end": window_end,
        },
    ]


class TestBillingUsage:
    @pytest.fixture(autouse=True)
    def _frozen_clock(self):
        with time_machine.travel("2026-03-05T15:00:00Z", tick=False):
            yield

    @pytest.mark.parametrize(
        "endpoint,expected_rows",
        [
            pytest.param(
                "billing_usage", _usage_rows_for("2026-01-02") + _usage_rows_for("2026-02-10"), id="daily_rows"
            ),
            pytest.param(
                "billing_usage_totals",
                _usage_total_rows_for("2026-01-01", "2026-01-31") + _usage_total_rows_for("2026-01-31", "2026-03-02"),
                id="window_totals",
            ),
        ],
    )
    def test_walks_windows_to_end_of_today_and_explodes_rows(
        self, endpoint: str, expected_rows: list[dict[str, Any]]
    ) -> None:
        result = _driver().run(
            endpoint,
            [
                _page(_usage_summary("2026-01-02")),
                _page(_usage_summary("2026-02-10")),
                _page({"dedicated_usage": None, "training_usage": None, "model_apis_usage": None}),
            ],
        )

        assert result.raised is None
        assert result.paths == ["/v1/billing/usage_summary"] * 3
        assert result.params("start_date") == [
            "2026-01-01T00:00:00Z",
            "2026-01-31T00:00:00Z",
            "2026-03-02T00:00:00Z",
        ]
        # The last window stops at the exclusive end of today (UTC), so today's partial usage is read.
        assert result.params("end_date") == [
            "2026-01-31T00:00:00Z",
            "2026-03-02T00:00:00Z",
            "2026-03-06T00:00:00Z",
        ]
        assert result.rows == expected_rows
        assert result.saved_states == [
            BasetenResumeConfig(window_start="2026-01-31"),
            BasetenResumeConfig(window_start="2026-03-02"),
        ]

    @pytest.mark.parametrize(
        "window_start,expected_first_start",
        [
            pytest.param("2026-03-02", ["2026-03-02T00:00:00Z"], id="resumes_at_saved_window"),
            # A saved window past today's limit cannot be sent; the walk starts over.
            pytest.param("2026-03-10", ["2026-01-01T00:00:00Z"], id="ignores_window_past_today"),
        ],
    )
    def test_resume(self, window_start: str, expected_first_start: list[str]) -> None:
        result = _driver().run(
            "billing_usage",
            [_page({})],
            resume_state=BasetenResumeConfig(window_start=window_start),
        )

        assert result.params("start_date")[:1] == expected_first_start


class TestFanOut:
    def test_injects_parent_id_and_yields_per_parent(self) -> None:
        result = _driver().run(
            "deployments",
            [
                _page({"models": [{"id": "m1"}, {"id": "m2"}]}),  # parent list
                _page({"deployments": [{"id": "d1"}]}),  # m1 children
                _page({"deployments": [{"id": "d2"}]}),  # m2 children
            ],
        )

        assert result.raised is None
        assert result.rows == [{"id": "d1", "model_id": "m1"}, {"id": "d2", "model_id": "m2"}]
        assert result.urls[1] == "https://api.baseten.co/v1/models/m1/deployments"
        assert result.urls[2] == "https://api.baseten.co/v1/models/m2/deployments"
        # The resolve param binds into the path, not the query string.
        assert result.requests[1].param("model_id") is None
        # A checkpoint marking m1 complete is saved before m2 is processed.
        assert (
            BasetenResumeConfig(
                fanout_state={"completed": ["/v1/models/m1/deployments"], "current": None, "child_state": None}
            )
            in result.saved_states
        )
        # Every checkpoint stays parseable as the resume dataclass (cursor/parent_id untouched).
        assert all(
            state.cursor is None and state.parent_id is None and isinstance(state.fanout_state, dict)
            for state in result.saved_states
        )

    def test_404_child_is_skipped(self) -> None:
        result = _driver().run(
            "deployments",
            [
                _page({"models": [{"id": "gone"}, {"id": "m2"}]}),
                _page({"code": "NOT_FOUND"}, status=404),  # parent deleted mid-sync
                _page({"deployments": [{"id": "d2"}]}),
            ],
        )

        assert result.raised is None
        assert result.rows == [{"id": "d2", "model_id": "m2"}]

    def test_parent_without_id_is_skipped(self) -> None:
        result = _driver().run(
            "deployments",
            [
                _page({"models": [{"id": "m1"}, {"name": "orphan"}]}),  # second parent has no id
                _page({"deployments": [{"id": "d1"}]}),  # only m1's children are fetched
            ],
        )

        assert result.raised is None
        assert result.rows == [{"id": "d1", "model_id": "m1"}]
        # The id-less parent must not produce a request against a stringified "None" id.
        assert not any("/models/None/" in url for url in result.urls)

    def test_resume_skips_completed_parents(self) -> None:
        result = _driver().run(
            "deployments",
            [
                _page({"models": [{"id": "m1"}, {"id": "m2"}]}),
                _page({"deployments": [{"id": "d2"}]}),  # only m2 is fetched
            ],
            resume_state=BasetenResumeConfig(
                fanout_state={"completed": ["/v1/models/m1/deployments"], "current": None, "child_state": None}
            ),
        )

        assert result.raised is None
        assert result.rows == [{"id": "d2", "model_id": "m2"}]
        child_urls = [url for url in result.urls if url.endswith("/deployments") and "/models/" in url]
        assert child_urls == ["https://api.baseten.co/v1/models/m2/deployments"]

    def test_legacy_parent_id_state_restarts_fan_out(self) -> None:
        # Pre-migration states bookmarked the next parent id; they still parse but the fan-out
        # restarts from the top (full-refresh tables, so re-appending is bounded).
        result = _driver().run(
            "deployments",
            [
                _page({"models": [{"id": "m1"}, {"id": "m2"}]}),
                _page({"deployments": [{"id": "d1"}]}),
                _page({"deployments": [{"id": "d2"}]}),
            ],
            resume_state=BasetenResumeConfig(parent_id="m2"),
        )

        assert result.raised is None
        assert result.rows == [{"id": "d1", "model_id": "m1"}, {"id": "d2", "model_id": "m2"}]


class TestValidateCredentials:
    def test_network_error_is_false(self) -> None:
        with scripted_network(always(ConnectionError("boom"))) as network:
            assert validate_credentials("key") is False

        assert {request.path for request in network.requests_log} == {"/v1/users/me"}


class TestSourceResponseShape:
    @pytest.fixture(autouse=True)
    def _frozen_clock(self):
        # One billing usage window, so a single scripted response ends the walk.
        with time_machine.travel("2026-01-10T00:00:00Z", tick=False):
            yield

    @pytest.mark.parametrize("endpoint", ENDPOINTS)
    def test_partition_and_primary_keys_match_config(self, endpoint: str) -> None:
        config = BASETEN_ENDPOINTS[endpoint]
        if config.fan_out_parent:
            parent_config = BASETEN_ENDPOINTS[config.fan_out_parent]
            script = [_page({parent_config.data_key: []})]
        elif config.mode in ("usage_daily", "usage_totals"):
            script = [_page({})]
        else:
            script = [_page({config.data_key: []})]

        result = _driver().run(endpoint, script)

        assert result.raised is None
        assert result.response is not None
        assert result.response.name == endpoint
        assert result.response.primary_keys == config.primary_keys
        if config.partition_key:
            assert result.response.partition_mode == "datetime"
            assert result.response.partition_keys == [config.partition_key]
        else:
            assert result.response.partition_mode is None
            assert result.response.partition_keys is None
