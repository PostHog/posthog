from datetime import UTC, date, datetime
from typing import Any

import pytest

import requests
from parameterized import parameterized
from requests import PreparedRequest

from products.warehouse_sources.backend.temporal.data_imports.sources.campfire.campfire import (
    CampfireResumeConfig,
    CampfireTokenAuth,
    _format_incremental_value,
    _incremental_config,
    _validate_next_url,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.campfire.settings import (
    CAMPFIRE_BASE_URL,
    ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.campfire.source import CampfireSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.campfire import (
    CampfireSourceConfig,
)


def _driver() -> SourceDriver:
    return SourceDriver(CampfireSource(), CampfireSourceConfig(api_key="key"))


def _response(body: Any, status: int = 200) -> ScriptedResponse:
    return ScriptedResponse(status=status, json=body)


class TestTokenAuth:
    def test_sets_token_authorization_header(self) -> None:
        request = PreparedRequest()
        request.prepare_headers({})
        CampfireTokenAuth("secret-key")(request)
        assert request.headers["Authorization"] == "Token secret-key"

    def test_secret_values_expose_the_key_for_redaction(self) -> None:
        assert CampfireTokenAuth("secret-key").secret_values() == ("secret-key",)
        assert CampfireTokenAuth("").secret_values() == ()


class TestFormatIncrementalValue:
    @parameterized.expand(
        [
            ("aware_datetime", datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC), "2026-01-02T03:04:05Z"),
            ("naive_datetime", datetime(2026, 1, 2, 3, 4, 5), "2026-01-02T03:04:05Z"),
            ("date", date(2026, 1, 2), "2026-01-02"),
            ("string_passthrough", "2026-01-02T03:04:05Z", "2026-01-02T03:04:05Z"),
        ]
    )
    def test_formats(self, _name: str, value: Any, expected: str) -> None:
        assert _format_incremental_value(value) == expected


class TestValidateNextUrl:
    @parameterized.expand(
        [
            ("other_host", "https://evil.example.com/coa/api/vendor?offset=100"),
            ("http_downgrade", "http://api.meetcampfire.com/coa/api/vendor?offset=100"),
        ]
    )
    def test_off_host_links_are_rejected(self, _name: str, url: str) -> None:
        # The API key rides in a header; following an off-host/downgraded next link would leak it.
        with pytest.raises(ValueError):
            _validate_next_url(url)


class TestFirstRequestParams:
    """The first request carries the page size, cursor opt-in, static params, and incremental filter."""

    @parameterized.expand(
        [
            # Without all_time=true these endpoints silently default to roughly the last six months.
            ("chart_transactions_all_time", "chart_transactions", "all_time", "true"),
            ("journal_entries_all_time", "journal_entries", "all_time", "true"),
            # Inactive tags still label historical transactions, and the API hides them by default.
            ("custom_dimensions_include_inactive", "custom_dimensions", "include_inactive", "true"),
        ]
    )
    def test_static_params_on_first_request(self, _name: str, endpoint: str, param: str, value: str) -> None:
        result = _driver().run(endpoint, [_response({"results": [], "next": None})])
        assert result.raised is None
        assert result.requests[0].param(param) == value

    def test_cursor_endpoints_send_empty_cursor(self) -> None:
        result = _driver().run("bill_payments", [_response({"results": [], "next": None})])
        assert result.raised is None
        assert "cursor=" in result.urls[0]

    def test_incremental_value_becomes_last_modified_filter(self) -> None:
        result = _driver().run(
            "vendors",
            [_response({"results": [], "next": None})],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
        )
        assert result.raised is None
        assert result.requests[0].param("last_modified_at__gte") == "2026-01-02T03:04:05Z"

    @parameterized.expand([("full_refresh", False, None), ("incremental_no_watermark", True, None)])
    def test_no_filter_without_watermark(self, _name: str, use_incremental: bool, last_value: Any) -> None:
        result = _driver().run(
            "vendors",
            [_response({"results": [], "next": None})],
            should_use_incremental_field=use_incremental,
            db_incremental_field_last_value=last_value,
        )
        assert result.raised is None
        assert result.requests[0].param("last_modified_at__gte") is None

    def test_full_refresh_only_endpoint_never_sends_filter(self) -> None:
        # journal_entries has no server-side last_modified filter; sending one anyway would be
        # silently ignored at best.
        result = _driver().run(
            "journal_entries",
            [_response({"results": [], "next": None})],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
        )
        assert result.raised is None
        assert result.requests[0].param("last_modified_at__gte") is None


class TestPagination:
    def test_follows_next_links_and_saves_state_after_each_yield(self) -> None:
        page2 = f"{CAMPFIRE_BASE_URL}/coa/api/vendor?limit=500&offset=500"
        result = _driver().run(
            "vendors",
            [
                _response({"count": 3, "next": page2, "results": [{"id": 1}, {"id": 2}]}),
                _response({"count": 3, "next": None, "results": [{"id": 3}]}),
            ],
        )

        assert result.raised is None
        assert result.rows == [{"id": 1}, {"id": 2}, {"id": 3}]
        assert result.urls[1] == page2
        # State is saved only while more pages remain, so a crash re-yields (not skips) the last
        # page — merge dedupes on the primary key.
        assert result.saved_states == [CampfireResumeConfig(next_url=page2)]

    def test_resumes_from_saved_next_url(self) -> None:
        page2 = f"{CAMPFIRE_BASE_URL}/coa/api/vendor?limit=500&offset=500"
        result = _driver().run(
            "vendors",
            [_response({"count": 3, "next": None, "results": [{"id": 3}]})],
            resume_state=CampfireResumeConfig(next_url=page2),
        )

        assert result.raised is None
        assert result.rows == [{"id": 3}]
        assert result.urls == [page2]

    def test_off_host_next_link_stops_the_sync(self) -> None:
        result = _driver().run(
            "vendors",
            [_response({"count": 1, "next": "https://evil.example.com/x", "results": [{"id": 1}]})],
        )
        assert isinstance(result.raised, ValueError)


class TestRetries:
    @parameterized.expand([("rate_limited", 429), ("server_error", 503)])
    def test_retryable_status_codes_are_retried(self, _name: str, status: int) -> None:
        result = _driver().run(
            "vendors",
            [_response({}, status=status), _response({"count": 0, "next": None, "results": []})],
        )
        assert result.rows == []
        assert len(result.requests) == 2
        assert result.raised is None

    def test_client_error_raises_without_retry(self) -> None:
        result = _driver().run("vendors", [_response({}, status=401)])
        assert isinstance(result.raised, requests.HTTPError)
        assert len(result.requests) == 1


class TestCampfireSourceResponse:
    def test_every_endpoint_builds_a_source_response(self) -> None:
        # Catches a catalog entry whose wiring can't be built at all -- a fan-out naming a parent
        # that isn't in the catalog raises here rather than mid-sync.
        for endpoint in ENDPOINTS:
            answer = [] if endpoint == "chart_entities" else {"results": [], "next": None}
            result = _driver().run(endpoint, [_response(answer)])
            assert result.raised is None
            assert result.response is not None
            assert result.response.name == endpoint

    def test_undocumented_order_endpoints_are_descending(self) -> None:
        # Everything else has no documented response order, so the watermark must only be persisted
        # once the sync completes.
        for endpoint in ("chart_transactions", "vendors", "contracts"):
            result = _driver().run(endpoint, [_response({"results": [], "next": None})])
            assert result.raised is None
            assert result.response is not None
            assert result.response.sort_mode == "desc"

    @parameterized.expand(
        [
            ("partitioned", "journal_entries", ["created_at"]),
            ("unpartitioned", "chart_of_accounts", None),
        ]
    )
    def test_partitioning(self, _name: str, endpoint: str, expected_keys: list[str] | None) -> None:
        result = _driver().run(endpoint, [_response({"results": [], "next": None})])
        assert result.raised is None
        assert result.response is not None
        assert result.response.partition_keys == expected_keys
        assert result.response.partition_mode == ("datetime" if expected_keys else None)


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True),
        ]
    )
    def test_status_maps_to_validity(self, _name: str, status: int, expected: bool) -> None:
        with scripted_network([ScriptedResponse(status=status)]) as network:
            assert validate_credentials("cf_test_key") is expected
        assert network.requests_log[0].path == "/coa/api/account"
        assert network.requests_log[0].param("limit") == "1"


class TestIncrementalConfig:
    def test_unknown_cursor_field_gets_no_request_window(self) -> None:
        # Campfire filters on `last_modified_at` and nothing else, so any other field must not
        # produce a param the API would ignore.
        assert _incremental_config("created_at") is None


class TestFanout:
    """Fan-out children are only reachable per parent, so they walk the parent listing first."""

    def _responses(self) -> list[ScriptedResponse]:
        return [
            _response({"count": 2, "next": None, "results": [{"id": 11}, {"id": 22}]}),
            _response([{"id": 1, "contract": 11}]),
            _response([{"id": 2, "contract": 22}]),
        ]

    @parameterized.expand(
        [
            (
                "contract_subscriptions",
                "/rr/api/v1/contracts",
                [[{"id": 1, "contract": 11}], [{"id": 2, "contract": 22}]],
                ["/rr/api/v1/contracts/11/subscriptions", "/rr/api/v1/contracts/22/subscriptions"],
            ),
            (
                "contract_milestones",
                "/rr/api/v1/contracts",
                [
                    {"count": 1, "next": None, "results": [{"id": 1, "contract": 11}]},
                    {"count": 1, "next": None, "results": [{"id": 2, "contract": 22}]},
                ],
                ["/rr/api/v1/contracts/11/milestones", "/rr/api/v1/contracts/22/milestones"],
            ),
            (
                "budget_accounts",
                "/coa/api/budgets",
                [[{"id": 1, "budget": 11}], [{"id": 2, "budget": 22}]],
                ["/coa/api/budgets/11/accounts", "/coa/api/budgets/22/accounts"],
            ),
        ]
    )
    def test_walks_each_parent_and_checkpoints_it(
        self, endpoint: str, parent_path: str, child_bodies: list[Any], child_paths: list[str]
    ) -> None:
        result = _driver().run(
            endpoint,
            [
                _response({"count": 2, "next": None, "results": [{"id": 11}, {"id": 22}]}),
                *[_response(body) for body in child_bodies],
            ],
        )
        assert result.raised is None
        assert result.paths == [parent_path, *child_paths]
        assert [row["id"] for row in result.rows] == [1, 2]
        assert result.saved_states[-1].completed == child_paths

    def test_paginated_child_follows_next_link_within_a_parent(self) -> None:
        page2 = f"{CAMPFIRE_BASE_URL}/rr/api/v1/contracts/11/milestones?limit=500&offset=500"
        result = _driver().run(
            "contract_milestones",
            [
                _response({"count": 1, "next": None, "results": [{"id": 11}]}),
                _response({"count": 2, "next": page2, "results": [{"id": 1, "contract": 11}]}),
                _response({"count": 2, "next": None, "results": [{"id": 2, "contract": 11}]}),
            ],
        )
        assert result.raised is None
        assert result.requests[1].param("limit") == "500"
        assert result.urls[2] == page2
        assert [row["id"] for row in result.rows] == [1, 2]

    def test_child_requests_carry_the_watermark(self) -> None:
        result = _driver().run(
            "contract_subscriptions",
            self._responses(),
            should_use_incremental_field=True,
            incremental_field="last_modified_at",
            db_incremental_field_last_value=datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
        )
        assert result.raised is None
        assert result.params("last_modified_at__gte")[1:] == [
            "2026-01-02T03:04:05Z",
            "2026-01-02T03:04:05Z",
        ]
        # The parent walk is unfiltered: a subscription can change without its contract changing.
        assert result.requests[0].param("last_modified_at__gte") is None

    def test_first_incremental_sync_sends_an_epoch_floor(self) -> None:
        # The framework sends the start param on every request, so with no stored watermark it
        # must still be a timestamp that selects everything.
        result = _driver().run(
            "contract_subscriptions",
            self._responses(),
            should_use_incremental_field=True,
            incremental_field="last_modified_at",
            db_incremental_field_last_value=None,
        )
        assert result.raised is None
        assert result.requests[1].param("last_modified_at__gte") == "1970-01-01T00:00:00Z"

    def test_resumes_past_contracts_already_synced(self) -> None:
        result = _driver().run(
            "contract_subscriptions",
            [
                _response({"count": 2, "next": None, "results": [{"id": 11}, {"id": 22}]}),
                _response([{"id": 2, "contract": 22}]),
            ],
            resume_state=CampfireResumeConfig(
                completed=["/rr/api/v1/contracts/11/subscriptions"], current=None, child_state=None
            ),
        )

        assert result.raised is None
        assert result.rows == [{"id": 2, "contract": 22}]
        assert result.paths[1:] == ["/rr/api/v1/contracts/22/subscriptions"]
