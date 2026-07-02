import json
from datetime import UTC, datetime
from typing import Any, cast

import pytest
from unittest.mock import patch

from requests import Request, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import ZendeskSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.zendesk.settings import (
    INCREMENTAL_ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.zendesk.source import ZendeskSource
from products.warehouse_sources.backend.temporal.data_imports.sources.zendesk.zendesk import (
    ZendeskCursorIncrementalPaginator,
    ZendeskIncrementalEndpointPaginator,
    get_resource,
    normalize_subdomain,
    to_zendesk_start_time,
)


def _make_response(json_body: dict[str, Any] | None = None) -> Response:
    resp = Response()
    resp.status_code = 200
    resp.headers["Content-Type"] = "application/json"
    resp._content = json.dumps(json_body or {}).encode()
    return resp


def _endpoint(resource: Any) -> dict[str, Any]:
    # resource["endpoint"] is typed Optional[str | Endpoint]; narrow it for key access.
    return cast(dict[str, Any], resource["endpoint"])


class TestZendeskValidateCredentials:
    def _config(self) -> ZendeskSourceConfig:
        return ZendeskSourceConfig(subdomain="nibbles", api_key="token", email_address="user@example.com")

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.zendesk.source.validate_credentials",
        return_value=False,
    )
    def test_rejected_credentials_message_names_each_credential(self, _mock_validate) -> None:
        valid, error = ZendeskSource().validate_credentials(self._config(), team_id=1)

        assert not valid
        assert error is not None
        assert "subdomain" in error
        assert "email address" in error
        assert "API token" in error

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.zendesk.source.validate_credentials",
        return_value=True,
    )
    def test_accepts_valid_credentials(self, _mock_validate) -> None:
        assert ZendeskSource().validate_credentials(self._config(), team_id=1) == (True, None)


class TestNormalizeSubdomain:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            pytest.param("nibbles", "nibbles", id="bare_subdomain"),
            pytest.param("nibbles.zendesk.com", "nibbles", id="full_host"),
            pytest.param("https://nibbles.zendesk.com", "nibbles", id="https_url"),
            pytest.param("https://nibbles.zendesk.com/", "nibbles", id="https_url_trailing_slash"),
            pytest.param("http://nibbles.zendesk.com/api/v2", "nibbles", id="url_with_path"),
            pytest.param("  nibbles.zendesk.com  ", "nibbles", id="whitespace"),
            pytest.param("nibbles.ZENDESK.com", "nibbles", id="mixed_case_host"),
            pytest.param("multi-word-team", "multi-word-team", id="hyphenated_subdomain"),
        ],
    )
    def test_collapses_to_subdomain_label(self, raw: str, expected: str) -> None:
        assert normalize_subdomain(raw) == expected

    def test_full_host_does_not_double_when_building_base_url(self) -> None:
        # Regression: a pasted full host previously produced "nibbles.zendesk.com.zendesk.com",
        # whose TLS handshake the Zendesk edge rejects.
        assert f"https://{normalize_subdomain('nibbles.zendesk.com')}.zendesk.com/" == "https://nibbles.zendesk.com/"


class TestZendeskCursorIncrementalPaginator:
    def test_advances_to_next_cursor(self) -> None:
        p = ZendeskCursorIncrementalPaginator()
        resp = _make_response({"tickets": [{"id": 1}], "after_cursor": "abc123", "end_of_stream": False})

        p.update_state(resp)

        assert p.has_next_page is True

        req = Request(method="GET", url="https://x.zendesk.com/api/v2/incremental/tickets/cursor")
        req.params = {"per_page": 1000, "start_time": 1591394586}
        p.update_request(req)

        assert req.params["cursor"] == "abc123"
        # The seed start_time is dropped once we paginate by cursor.
        assert "start_time" not in req.params
        assert req.params["per_page"] == 1000

    def test_first_request_keeps_seed_start_time(self) -> None:
        p = ZendeskCursorIncrementalPaginator()

        # Before any response, has_next_page is True and no cursor is set, so the
        # first request must go out untouched (with its seed start_time).
        assert p.has_next_page is True

        req = Request(method="GET", url="https://x.zendesk.com/api/v2/incremental/tickets/cursor")
        req.params = {"per_page": 1000, "start_time": 1591394586}
        p.init_request(req)

        assert req.params["start_time"] == 1591394586
        assert "cursor" not in req.params

    def test_works_for_any_data_key(self) -> None:
        # The paginator only reads top-level after_cursor/end_of_stream, so the users
        # cursor export (data key "users") paginates identically to tickets.
        p = ZendeskCursorIncrementalPaginator()
        p.update_state(_make_response({"users": [{"id": 1}], "after_cursor": "u1", "end_of_stream": False}))
        assert p.has_next_page is True

        req = Request(method="GET", url="https://x.zendesk.com/api/v2/incremental/users/cursor")
        req.params = {"per_page": 1000, "start_time": 0}
        p.update_request(req)
        assert req.params["cursor"] == "u1"
        # The seed start_time must be dropped once we paginate by cursor, same as tickets.
        assert "start_time" not in req.params

    @pytest.mark.parametrize(
        "body",
        [
            pytest.param({"tickets": [], "after_cursor": "abc123", "end_of_stream": True}, id="end_of_stream"),
            pytest.param({}, id="empty_response"),
        ],
    )
    def test_stops_pagination(self, body: dict[str, Any]) -> None:
        p = ZendeskCursorIncrementalPaginator()

        p.update_state(_make_response(body))

        assert p.has_next_page is False

    @pytest.mark.parametrize(
        "body",
        [
            pytest.param({"tickets": [{"id": 1}], "after_cursor": None, "end_of_stream": False}, id="missing_cursor"),
            pytest.param({"tickets": [{"id": 1}], "after_cursor": "abc123"}, id="missing_end_of_stream"),
        ],
    )
    def test_raises_on_invalid_response(self, body: dict[str, Any]) -> None:
        p = ZendeskCursorIncrementalPaginator()

        with pytest.raises(ValueError):
            p.update_state(_make_response(body))

    def test_raises_when_cursor_does_not_advance(self) -> None:
        """A cursor that never moves while end_of_stream is False is the time-based
        export's failure mode; fail loud so the activity retries instead of
        silently truncating data."""
        p = ZendeskCursorIncrementalPaginator()

        first = _make_response({"tickets": [{"id": 1}], "after_cursor": "abc123", "end_of_stream": False})
        p.update_state(first)
        assert p.has_next_page is True

        repeated = _make_response({"tickets": [{"id": 1}], "after_cursor": "abc123", "end_of_stream": False})
        with pytest.raises(ValueError):
            p.update_state(repeated)

    def test_paginates_across_multiple_pages(self) -> None:
        p = ZendeskCursorIncrementalPaginator()
        req = Request(method="GET", url="https://x.zendesk.com/api/v2/incremental/tickets/cursor")
        req.params = {"per_page": 1000, "start_time": 1591394586}

        p.update_state(_make_response({"tickets": [{"id": 1}], "after_cursor": "cursor_1", "end_of_stream": False}))
        p.update_request(req)
        assert req.params["cursor"] == "cursor_1"

        p.update_state(_make_response({"tickets": [{"id": 2}], "after_cursor": "cursor_2", "end_of_stream": False}))
        p.update_request(req)
        assert req.params["cursor"] == "cursor_2"

        p.update_state(_make_response({"tickets": [{"id": 3}], "after_cursor": "cursor_3", "end_of_stream": True}))
        assert p.has_next_page is False


class TestZendeskIncrementalEndpointPaginator:
    def test_advances_to_next_page(self) -> None:
        p = ZendeskIncrementalEndpointPaginator()
        p.update_state(_make_response({"end_of_stream": False, "next_page": "https://x.zendesk.com/next"}))

        assert p.has_next_page is True

        req = Request(method="GET", url="https://x.zendesk.com/api/v2/incremental/organizations")
        req.params = {"per_page": 1000, "start_time": 0}
        p.update_request(req)
        assert req.url == "https://x.zendesk.com/next"
        # next_page is a full URL carrying its own query string, so existing params are cleared.
        assert req.params == {}

    @pytest.mark.parametrize(
        "body",
        [
            pytest.param({"end_of_stream": True, "next_page": None}, id="end_of_stream"),
            pytest.param({}, id="empty_response"),
        ],
    )
    def test_stops_pagination(self, body: dict[str, Any]) -> None:
        p = ZendeskIncrementalEndpointPaginator()

        p.update_state(_make_response(body))

        assert p.has_next_page is False

    @pytest.mark.parametrize(
        "body",
        [
            pytest.param({"organizations": [{"id": 1}]}, id="missing_end_of_stream"),
            pytest.param({"end_of_stream": False, "next_page": None}, id="missing_next_page"),
        ],
    )
    def test_raises_on_invalid_response(self, body: dict[str, Any]) -> None:
        # organizations now routes through this paginator, so a malformed time-based export
        # response must fail loud (retryable) rather than raise an uncaught KeyError.
        p = ZendeskIncrementalEndpointPaginator()

        with pytest.raises(ValueError):
            p.update_state(_make_response(body))


class TestToZendeskStartTime:
    @pytest.mark.parametrize(
        "value,expected",
        [
            pytest.param(0, 0, id="initial_value_zero"),
            pytest.param(1591394586, 1591394586, id="passthrough_int"),
            pytest.param(datetime(2020, 6, 5, 21, 23, 6, tzinfo=UTC), 1591392186, id="aware_datetime"),
            # Naive datetimes are interpreted as UTC.
            pytest.param(datetime(2020, 6, 5, 21, 23, 6), 1591392186, id="naive_datetime_as_utc"),
        ],
    )
    def test_converts_to_unix_epoch(self, value: Any, expected: int) -> None:
        assert to_zendesk_start_time(value) == expected


class TestIncrementalResourceWiring:
    """The four endpoints that have a Zendesk Incremental Export API must declare a server-side
    `start_time` cursor so incremental sync actually filters data, not just flips write disposition."""

    @pytest.mark.parametrize(
        "endpoint,expected_path,expected_paginator,cursor_path,expected_include",
        [
            pytest.param(
                "users",
                "/api/v2/incremental/users/cursor",
                ZendeskCursorIncrementalPaginator,
                "updated_at",
                None,
                id="users",
            ),
            pytest.param(
                "organizations",
                "/api/v2/incremental/organizations",
                ZendeskIncrementalEndpointPaginator,
                "updated_at",
                None,
                id="organizations",
            ),
            pytest.param(
                "ticket_events",
                "/api/v2/incremental/ticket_events",
                ZendeskIncrementalEndpointPaginator,
                "created_at",
                "comment_events",
                id="ticket_events",
            ),
            pytest.param(
                "ticket_metric_events",
                "/api/v2/incremental/ticket_metric_events",
                ZendeskIncrementalEndpointPaginator,
                "time",
                None,
                id="ticket_metric_events",
            ),
        ],
    )
    def test_endpoint_declares_incremental_start_time(
        self,
        endpoint: str,
        expected_path: str,
        expected_paginator: type,
        cursor_path: str,
        expected_include: str | None,
    ) -> None:
        resource = get_resource(endpoint, should_use_incremental_field=True)
        endpoint_config = _endpoint(resource)

        assert endpoint_config["path"] == expected_path
        assert isinstance(endpoint_config["paginator"], expected_paginator)
        # Without include=comment_events the ticket_events export strips comment bodies from
        # child_events — assert the sideload stays wired.
        assert endpoint_config["params"].get("include") == expected_include

        start_time = endpoint_config["params"]["start_time"]
        assert start_time["type"] == "incremental"
        assert start_time["cursor_path"] == cursor_path
        assert start_time["initial_value"] == 0
        # Datetime cursors must convert to the Unix epoch Zendesk expects.
        assert start_time["convert"] is to_zendesk_start_time

    @pytest.mark.parametrize("endpoint", ["users", "organizations", "ticket_events", "ticket_metric_events"])
    def test_write_disposition_follows_incremental_flag(self, endpoint: str) -> None:
        incremental = get_resource(endpoint, should_use_incremental_field=True)
        full_refresh = get_resource(endpoint, should_use_incremental_field=False)

        assert incremental["write_disposition"] == {"disposition": "merge", "strategy": "upsert"}
        assert full_refresh["write_disposition"] == "replace"

    def test_incremental_fields_cover_incremental_endpoints(self) -> None:
        # Every endpoint advertised as incremental must declare its incremental field(s).
        for endpoint in INCREMENTAL_ENDPOINTS:
            assert INCREMENTAL_FIELDS.get(endpoint), (
                f"{endpoint} is in INCREMENTAL_ENDPOINTS but has no incremental field"
            )
