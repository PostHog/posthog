from datetime import UTC, date, datetime
from typing import Any, Optional

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.safetyculture import (
    SafetyCultureSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.safetyculture.safetyculture import (
    SafetyCultureResumeConfig,
    _format_modified_after,
    check_access,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.safetyculture.settings import (
    ENDPOINTS,
    SAFETYCULTURE_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.safetyculture.source import SafetyCultureSource

BASE_URL = "https://api.safetyculture.io"


def _response(
    items: Optional[list[dict[str, Any]]],
    next_page: Optional[str] = None,
    *,
    raw_body: Any = None,
    status: int = 200,
) -> ScriptedResponse:
    if raw_body is not None:
        body: Any = raw_body
    else:
        body = {"metadata": {"next_page": next_page, "remaining_records": 0}, "data": items or []}
    return ScriptedResponse(status=status, json=body)


def _driver() -> SourceDriver:
    return SourceDriver(SafetyCultureSource(), SafetyCultureSourceConfig(api_token="sc-token"))


class TestFormatModifiedAfter:
    @parameterized.expand(
        [
            ("aware_datetime", datetime(2024, 1, 28, 23, 14, 23, tzinfo=UTC), "2024-01-28T23:14:23.000Z"),
            ("naive_datetime", datetime(2024, 1, 28, 23, 14, 23), "2024-01-28T23:14:23.000Z"),
            ("date", date(2024, 1, 28), "2024-01-28T00:00:00.000Z"),
            ("string_passthrough", "2024-01-28T23:14:23.000Z", "2024-01-28T23:14:23.000Z"),
        ]
    )
    def test_internet_date_time_format(self, _name: str, value: Any, expected: str) -> None:
        # Since 2025-02-01 SafetyCulture rejects timestamps that aren't Internet Date-Time format.
        assert _format_modified_after(value) == expected


class TestInitialRequest:
    def test_incremental_first_request_carries_modified_after(self) -> None:
        result = _driver().run(
            "inspections",
            [_response([{"id": "a"}])],
            incremental_field="modified_at",
            db_incremental_field_last_value=datetime(2024, 3, 1, tzinfo=UTC),
        )

        assert {name: values[0] for name, values in result.queries[0].items()} == {
            "archived": "both",
            "completed": "both",
            "modified_after": "2024-03-01T00:00:00.000Z",
        }

    def test_full_refresh_endpoint_never_sends_modified_after(self) -> None:
        # The issues feed documents no modified_after — a stale watermark must never leak into it.
        result = _driver().run(
            "issues",
            [_response([{"id": "a"}])],
            incremental_field="modified_at",
            db_incremental_field_last_value=datetime(2024, 3, 1, tzinfo=UTC),
        )

        assert "modified_after" not in result.queries[0]


class TestPagination:
    def test_follows_next_page_verbatim_and_checkpoints(self) -> None:
        result = _driver().run(
            "users",
            [
                _response([{"id": "a"}], next_page="/feed/users?opaque-cursor=xyz"),
                _response([{"id": "b"}], next_page=None),
            ],
        )

        assert result.rows == [{"id": "a"}, {"id": "b"}]
        # Page 2 targets the server-issued next_page (resolved to the API host), and carries no
        # re-appended query params.
        assert result.urls[1] == f"{BASE_URL}/feed/users?opaque-cursor=xyz"
        assert set(result.queries[1]) == {"opaque-cursor"}
        # State is saved after the first page yields, holding the next page to fetch.
        assert result.saved_states == [SafetyCultureResumeConfig(next_page=f"{BASE_URL}/feed/users?opaque-cursor=xyz")]

    def test_offhost_next_page_rejected_before_send(self) -> None:
        # An absolute, off-host metadata.next_page is followed verbatim, so it must be rejected by the
        # client's host pin before the Bearer token can be replayed to an attacker-controlled host.
        result = _driver().run(
            "users",
            [
                _response([{"id": "a"}], next_page="https://evil.example/feed/users?opaque-cursor=xyz"),
                _response([{"id": "b"}], next_page=None),
            ],
        )

        assert isinstance(result.raised, ValueError)
        assert "disallowed host" in str(result.raised)
        # Only the on-host first page went out; the off-host next_page never reached the network.
        assert len(result.requests) == 1

    @parameterized.expand(
        [
            ("relative_saved_path", "/feed/users?opaque-cursor=xyz"),
            ("absolute_saved_url", f"{BASE_URL}/feed/users?opaque-cursor=xyz"),
        ]
    )
    def test_resumes_from_saved_next_page(self, _name: str, saved: str) -> None:
        # A relative path (historic save) and an absolute URL (new save) both resolve to the same
        # request, and the initial unfiltered page is never fetched.
        result = _driver().run(
            "users",
            [_response([{"id": "b"}], next_page=None)],
            resume_state=SafetyCultureResumeConfig(next_page=saved),
        )

        assert result.rows == [{"id": "b"}]
        assert len(result.requests) == 1
        assert result.urls[0] == f"{BASE_URL}/feed/users?opaque-cursor=xyz"

    def test_a_run_with_no_saved_state_starts_from_the_first_page(self) -> None:
        result = _driver().run("users", [_response([{"id": "a"}], next_page=None)])

        assert result.urls[0] == f"{BASE_URL}/feed/users"

    def test_empty_first_page_yields_nothing_and_no_checkpoint(self) -> None:
        result = _driver().run("users", [_response([], next_page=None)])

        assert result.rows == []
        assert result.saved_states == []

    @parameterized.expand(
        [
            ("null_next_page", {"metadata": {"next_page": None}, "data": [{"id": "a"}]}),
            ("missing_metadata", {"data": [{"id": "a"}]}),
            ("empty_next_page", {"metadata": {"next_page": ""}, "data": [{"id": "a"}]}),
        ]
    )
    def test_terminal_next_page_shapes_stop(self, _name: str, body: dict) -> None:
        result = _driver().run("users", [_response(None, raw_body=body)])

        assert result.rows == [{"id": "a"}]
        assert len(result.requests) == 1
        assert result.saved_states == []


def _structures_response(results: list[dict[str, Any]], next_page_token: str = "") -> ScriptedResponse:
    return _response(
        None,
        raw_body={"results": results, "next_page_token": next_page_token, "total_count": len(results)},
    )


def _structures_body(structure_type: str, page_token: Optional[str] = None) -> dict[str, Any]:
    page: dict[str, Any] = {"page_size": 100}
    if page_token:
        page["page_token"] = page_token
    return {
        "params": {"query": "", "include_fields": True, "page": page},
        "structure_type": {"system_structure_type": structure_type},
    }


class TestStructures:
    def test_walks_each_structure_type_with_body_page_token(self) -> None:
        result = _driver().run(
            "structures",
            [
                _structures_response([{"structure_uuid": "s1"}], next_page_token="tok-1"),
                _structures_response([{"structure_uuid": "s2"}]),
                # Protobuf JSON drops an empty `results`, so a type with no structures has no key.
                _response(None, raw_body={"next_page_token": ""}),
            ],
        )

        assert result.rows == [{"structure_uuid": "s1"}, {"structure_uuid": "s2"}]
        assert result.urls == [f"{BASE_URL}/structures/v1/structures/search"] * 3
        assert [request.json() for request in result.requests] == [
            _structures_body("SYSTEM_STRUCTURE_TYPE_SITE"),
            _structures_body("SYSTEM_STRUCTURE_TYPE_SITE", "tok-1"),
            _structures_body("SYSTEM_STRUCTURE_TYPE_GROUP"),
        ]
        assert result.saved_states == [
            SafetyCultureResumeConfig(structure_type_index=0, page_token="tok-1"),
            SafetyCultureResumeConfig(structure_type_index=1, page_token=None),
        ]

    def test_repeated_page_token_ends_the_structure_type(self) -> None:
        result = _driver().run(
            "structures",
            [
                _structures_response([{"structure_uuid": "s1"}], next_page_token="tok-1"),
                _structures_response([{"structure_uuid": "s2"}], next_page_token="tok-1"),
                _structures_response([{"structure_uuid": "g1"}]),
            ],
        )

        assert result.rows == [{"structure_uuid": "s1"}, {"structure_uuid": "s2"}, {"structure_uuid": "g1"}]
        assert result.requests[2].json() == _structures_body("SYSTEM_STRUCTURE_TYPE_GROUP")

    def test_resumes_from_saved_structure_type_and_token(self) -> None:
        result = _driver().run(
            "structures",
            [_structures_response([{"structure_uuid": "g2"}])],
            resume_state=SafetyCultureResumeConfig(structure_type_index=1, page_token="tok-g"),
        )

        assert result.rows == [{"structure_uuid": "g2"}]
        assert [request.json() for request in result.requests] == [
            _structures_body("SYSTEM_STRUCTURE_TYPE_GROUP", "tok-g")
        ]

    def test_a_run_with_no_saved_state_starts_from_the_first_structure_type(self) -> None:
        result = _driver().run("structures", [_structures_response([{"structure_uuid": "s1"}])])

        assert result.requests[0].json() == _structures_body("SYSTEM_STRUCTURE_TYPE_SITE")


class TestErrorHandling:
    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    def test_retryable_statuses_raise_retryable_after_exhausting(self, _name: str, status: int) -> None:
        result = _driver().run("users", always(_response([{"id": "a"}], status=status)))

        assert isinstance(result.raised, RESTClientRetryableError)
        # Retried before giving up.
        assert len(result.requests) > 1

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_client_errors_raise_for_status(self, _name: str, status: int) -> None:
        result = _driver().run("users", [_response(None, raw_body={}, status=status)])

        assert isinstance(result.raised, requests.HTTPError)
        # A permanent client error is not retried.
        assert len(result.requests) == 1

    @parameterized.expand(
        [
            ("non_dict_body", [{"id": "a"}]),
            ("non_list_data", {"metadata": {}, "data": {"id": "a"}}),
            ("dict_without_data", {"metadata": {}}),
        ]
    )
    def test_unexpected_200_payload_is_retryable(self, _name: str, body: Any) -> None:
        # A 200 whose body isn't the documented {"metadata", "data": [...]} envelope is retried.
        result = _driver().run("users", always(_response(None, raw_body=body)))

        assert isinstance(result.raised, RESTClientRetryableError)
        assert len(result.requests) > 1

    def test_bearer_token_redacted_from_errors(self) -> None:
        # The framework auth scrubs the token from any raised error message.
        result = _driver().run("users", [_response(None, raw_body={}, status=401)])

        assert isinstance(result.raised, requests.HTTPError)
        assert "sc-token" not in str(result.raised)


class TestCheckAccess:
    @parameterized.expand(
        [
            (403, 403, None),
        ]
    )
    def test_status_mapping(self, status: int, expected_status: int, expected_message: str | None) -> None:
        with scripted_network(always(ScriptedResponse(status=status))):
            assert check_access("sc-token") == (expected_status, expected_message)

    def test_structures_probe_posts_a_scoped_search(self) -> None:
        with scripted_network([ScriptedResponse(json={})]) as network:
            assert check_access("sc-token", "/structures/v1/structures/search", "SYSTEM_STRUCTURE_TYPE_SITE") == (
                200,
                None,
            )

        assert [request.method for request in network.requests_log] == ["POST"]
        assert network.requests_log[0].json() == {
            "structure_type": {"system_structure_type": "SYSTEM_STRUCTURE_TYPE_SITE"},
            "params": {"page": {"page_size": 1}},
        }


class TestSafetyCultureSourceResponse:
    @parameterized.expand([(e,) for e in ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        result = _driver().run(
            endpoint, always(_response(None, raw_body={"metadata": {"next_page": None}, "data": [], "results": []}))
        )

        response = result.response
        assert response is not None
        config = SAFETYCULTURE_ENDPOINTS[endpoint]
        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        assert response.sort_mode == "asc"
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_format == "month"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None

    def test_incremental_endpoints_match_documented_modified_after_support(self) -> None:
        # Only these four feeds document a server-side modified_after filter; flipping any other
        # endpoint to incremental would silently ship a full-refresh-cost "incremental" sync.
        incremental = {name for name, config in SAFETYCULTURE_ENDPOINTS.items() if config.supports_incremental}
        assert incremental == {"inspections", "inspection_items", "templates", "actions"}
