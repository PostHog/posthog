import re
from datetime import UTC, date, datetime
from typing import Any, Optional

import pytest
from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.pretix import PretixSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.pretix.pretix import (
    HOST_NOT_ALLOWED_ERROR,
    INVALID_ORGANIZER_ERROR,
    PretixHostNotAllowedError,
    PretixResumeConfig,
    _format_modified_since,
    _quote_organizer,
    normalize_base_url,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.pretix.source import PretixSource

IS_CLOUD_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins.is_cloud"


def _envelope(items: list[dict[str, Any]], next_url: Optional[str] = None) -> ScriptedResponse:
    return ScriptedResponse(json={"count": len(items), "next": next_url, "previous": None, "results": items})


def _driver(base_url: str | None = None) -> SourceDriver:
    return SourceDriver(PretixSource(), PretixSourceConfig(organizer="acme", api_token="tok", base_url=base_url))


class TestNormalizeBaseUrl:
    @parameterized.expand(
        [
            (None, "https://pretix.eu/api/v1"),
            ("", "https://pretix.eu/api/v1"),
            ("  ", "https://pretix.eu/api/v1"),
            ("tickets.example.com", "https://tickets.example.com/api/v1"),
            ("https://tickets.example.com", "https://tickets.example.com/api/v1"),
            ("https://tickets.example.com/", "https://tickets.example.com/api/v1"),
            ("https://tickets.example.com/api/v1", "https://tickets.example.com/api/v1"),
            ("http://tickets.example.com", "http://tickets.example.com/api/v1"),
        ]
    )
    def test_normalize_base_url(self, raw: Optional[str], expected: str) -> None:
        assert normalize_base_url(raw) == expected


class TestFormatModifiedSince:
    @parameterized.expand(
        [
            (datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14Z"),
            (datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14Z"),
            (date(2026, 3, 4), "2026-03-04T00:00:00Z"),
            ("2026-03-04T02:58:14Z", "2026-03-04T02:58:14Z"),
        ]
    )
    def test_format_modified_since(self, value: object, expected: str) -> None:
        assert _format_modified_since(value) == expected


class TestQuoteOrganizer:
    @parameterized.expand(
        [
            ("my-organizer", "my-organizer"),
            (" my-organizer ", "my-organizer"),
            ("/my-organizer/", "my-organizer"),
            ("a/../b", "a%2F..%2Fb"),
        ]
    )
    def test_quotes_path_segments(self, raw: str, expected: str) -> None:
        assert _quote_organizer(raw) == expected

    @parameterized.expand([("",), ("  ",), ("/",)])
    def test_rejects_empty(self, raw: str) -> None:
        with pytest.raises(ValueError, match=INVALID_ORGANIZER_ERROR):
            _quote_organizer(raw)


class TestOrganizerScopePagination:
    def test_orders_incremental_url_has_filter_and_stable_ordering(self) -> None:
        result = _driver().run(
            "orders",
            [_envelope([{"code": "A1", "event": "conf"}])],
            incremental_field="last_modified",
            db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
        )

        assert result.requests[0].param("modified_since") == "2026-01-01T00:00:00Z"
        assert result.requests[0].param("ordering") == "last_modified"

    @parameterized.expand(
        [
            (False, "last_modified"),
            # A user-selected cursor the server filter doesn't target must not be silently rewritten
            # into a `modified_since` filter.
            (True, "datetime"),
        ]
    )
    def test_no_modified_since_when_not_applicable(self, should_use: bool, incremental_field: str) -> None:
        result = _driver().run(
            "orders",
            [_envelope([])],
            should_use_incremental_field=should_use,
            incremental_field=incremental_field,
            db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
        )

        assert "modified_since" not in result.requests[0].query
        # `ordering` is always requested for orders regardless of the incremental filter.
        assert result.requests[0].param("ordering") == "last_modified"

    def test_redirect_is_rejected(self) -> None:
        # A 3xx is not followed (allow_redirects=False) — it must not be silently parsed as data.
        result = _driver().run(
            "orders", [ScriptedResponse(status=302, json={}, headers={"Location": "https://pretix.eu/login"})]
        )

        assert isinstance(result.raised, ValueError)
        assert re.search("[Rr]edirect", str(result.raised))


class TestHostPinning:
    def test_off_host_next_url_is_not_fetched(self) -> None:
        # A malicious server handing out an off-host `next` link must never be fetched — the
        # Authorization header would otherwise be sent to an attacker-controlled origin.
        result = _driver().run("orders", [_envelope([{"code": "A1"}], "https://evil.example.com/steal?page=2")])

        assert isinstance(result.raised, ValueError)
        assert "disallowed host" in str(result.raised)
        # Only the first (on-host) page was ever sent.
        assert len(result.requests) == 1

    def test_off_host_resume_url_is_rejected_before_any_request(self) -> None:
        result = _driver().run(
            "orders",
            [],
            resume_state=PretixResumeConfig(next_url="https://evil.example.com/steal?page=5"),
        )

        assert isinstance(result.raised, ValueError)
        assert "disallowed host" in str(result.raised)
        assert result.requests == []

    @mock.patch(IS_CLOUD_PATCH, return_value=True)
    def test_unsafe_host_raises_before_building_the_source(self, _is_cloud) -> None:
        result = _driver(base_url="https://10.0.0.5").run("orders", [], team_id=3)

        assert isinstance(result.raised, PretixHostNotAllowedError)
        assert result.response is None
        assert result.requests == []

    def test_http_base_url_raises_before_building_the_source(self) -> None:
        result = _driver(base_url="http://tickets.example.com").run("orders", [])

        assert isinstance(result.raised, PretixHostNotAllowedError)
        assert result.response is None
        assert result.requests == []


class TestEventFanOut:
    def test_fans_out_per_event_and_stamps_event_slug(self) -> None:
        result = _driver().run(
            "items",
            [
                _envelope([{"slug": "conf-a"}, {"slug": "conf-b"}]),  # events discovery
                _envelope([{"id": 1}]),  # conf-a items
                _envelope([{"id": 1}, {"id": 2}]),  # conf-b items
            ],
        )

        # The composite primary key (event_slug, id) stays unique even though both events reuse id=1.
        assert [(r["event_slug"], r["id"]) for r in result.rows] == [("conf-a", 1), ("conf-b", 1), ("conf-b", 2)]
        # The single-hop fan-out is resumable — a per-event checkpoint is persisted.
        assert result.saved_states
        assert result.saved_states[-1].fanout_state is not None

    def test_event_slug_is_url_quoted_in_child_path(self) -> None:
        result = _driver().run("items", [_envelope([{"slug": "a/b"}]), _envelope([])])

        # The slug is percent-encoded in the child URL so it can't inject an extra path segment...
        assert any("/events/a%2Fb/items/" in url for url in result.urls)
        # ...while the raw slug is stamped into rows unchanged (there are no rows here, so just the URL).
        assert result.rows == []


class TestValidateCredentials:
    @parameterized.expand(
        [
            (200, True, None),
            (401, False, "Invalid pretix API token"),
            (403, False, "does not have access to this organizer"),
            (302, False, HOST_NOT_ALLOWED_ERROR),
            (500, False, "HTTP 500"),
        ]
    )
    def test_status_mapping(self, status_code: int, expected_valid: bool, message_fragment: str | None) -> None:
        with scripted_network(always(ScriptedResponse(status=status_code, json={}))):
            is_valid, message = validate_credentials("tok", "acme", None, team_id=1)

        assert is_valid is expected_valid
        if message_fragment is None:
            assert message is None
        else:
            assert message is not None and message_fragment in message

    def test_invalid_organizer_rejected_without_request(self) -> None:
        with scripted_network([]) as network:
            is_valid, message = validate_credentials("tok", "  ", None, team_id=1)

        assert is_valid is False
        assert message == INVALID_ORGANIZER_ERROR
        assert network.requests_log == []

    def test_http_base_url_rejected_without_request(self) -> None:
        with scripted_network([]) as network:
            is_valid, message = validate_credentials("tok", "acme", "http://tickets.example.com", team_id=1)

        assert is_valid is False
        assert message is not None and "HTTPS" in message
        assert network.requests_log == []


class TestPretixSourceResponse:
    @parameterized.expand(
        [
            ("events", ["slug"]),
            ("invoices", ["event", "number"]),
            ("customers", ["identifier"]),
            ("gift_cards", ["id"]),
            ("items", ["event_slug", "id"]),
            ("vouchers", ["event_slug", "id"]),
        ]
    )
    def test_primary_keys_per_endpoint(self, endpoint: str, primary_keys: list[str]) -> None:
        response = _driver().run(endpoint, always(_envelope([]))).response

        assert response is not None
        assert response.primary_keys == primary_keys
        assert response.partition_mode is None
