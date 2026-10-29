from datetime import UTC, datetime
from typing import Any

import pytest
from unittest import mock

from tenacity import Future, RetryCallState

from products.warehouse_sources.backend.temporal.data_imports.sources.apollo.apollo import (
    MAX_PAGES,
    MAX_RETRY_AFTER_SECONDS,
    PAGE_SIZE,
    ApolloResumeConfig,
    ApolloRetryableError,
    _parse_retry_after,
    _parse_timestamp,
    _wait_apollo,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.apollo.settings import APOLLO_ENDPOINTS, ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.apollo.source import ApolloSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.apollo import ApolloSourceConfig


def _driver() -> SourceDriver:
    return SourceDriver(ApolloSource(), ApolloSourceConfig(api_key="key"))


def _page(data_key: str, items: list[dict[str, Any]], total_pages: int = 1) -> ScriptedResponse:
    return ScriptedResponse(
        json={data_key: items, "pagination": {"page": 1, "per_page": PAGE_SIZE, "total_pages": total_pages}}
    )


class TestParseTimestamp:
    @pytest.mark.parametrize(
        "value, expected",
        [
            ("2024-01-02T03:04:05Z", datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC)),
            ("2024-01-02T03:04:05+00:00", datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC)),
            (datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC), datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC)),
            ("not-a-date", None),
            (None, None),
        ],
    )
    def test_parse_values(self, value, expected):
        assert _parse_timestamp(value) == expected


class TestValidateCredentials:
    def test_valid_when_logged_in(self) -> None:
        with scripted_network([ScriptedResponse(json={"is_logged_in": True})]) as network:
            assert validate_credentials("key") is True

        assert [request.path for request in network.requests_log] == ["/api/v1/auth/health"]
        assert network.requests_log[0].headers["x-api-key"] == "key"

    def test_invalid_when_not_logged_in(self) -> None:
        with scripted_network([ScriptedResponse(json={"is_logged_in": False})]):
            assert validate_credentials("key") is False


class TestGetRows:
    def test_incremental_sorts_desc_and_stops_at_watermark(self) -> None:
        page = [
            {"id": "new", "updated_at": "2024-06-01T00:00:00Z"},
            {"id": "old", "updated_at": "2024-01-01T00:00:00Z"},
        ]
        result = _driver().run(
            "contacts",
            [_page("contacts", page, total_pages=5)],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2024, 3, 1, tzinfo=UTC),
        )

        # Only the newer row is yielded and the walk stops on crossing.
        assert [item["id"] for item in result.rows] == ["new"]
        assert result.raised is None
        assert len(result.requests) == 1
        body = result.requests[0].json()
        assert body["sort_by_field"] == "contact_updated_at"
        assert body["sort_ascending"] is False

    @pytest.mark.parametrize("endpoint", ["tasks", "emailer_campaigns"])
    def test_query_param_post_endpoints_paginate_in_the_query_string(self, endpoint: str) -> None:
        # These POSTs only read page params from the query string. Sent in the JSON body they
        # are ignored, so every request comes back as page 1 and the walk re-yields it until
        # the 500-page cap.
        result = _driver().run(
            endpoint,
            [
                _page(endpoint, [{"id": "a1"}], total_pages=2),
                _page(endpoint, [{"id": "a2"}], total_pages=2),
            ],
        )

        assert [item["id"] for item in result.rows] == ["a1", "a2"]
        assert result.raised is None
        assert result.params("page") == ["1", "2"]
        assert result.params("per_page") == [str(PAGE_SIZE), str(PAGE_SIZE)]
        assert result.requests[0].json() == {}

    def test_emailer_messages_stops_without_a_pagination_object(self) -> None:
        # This endpoint answers with no pagination object at all, so there is no total_pages
        # to break on — the walk has to end on the first empty page instead of running to the cap.
        page = {"emailer_messages": [{"id": "m1", "created_at": "2024-01-01T00:00:00Z"}], "emailer_steps": []}
        empty: dict[str, list[Any]] = {"emailer_messages": [], "emailer_steps": []}
        result = _driver().run("emailer_messages", [ScriptedResponse(json=page), ScriptedResponse(json=empty)])

        assert [item["id"] for item in result.rows] == ["m1"]
        assert result.raised is None
        assert result.params("page") == ["1", "2"]

    @pytest.mark.parametrize("endpoint", ["contact_stages", "account_stages", "opportunity_stages"])
    def test_lookup_endpoints_read_one_unpaginated_page(self, endpoint: str) -> None:
        # Without the single-page stop these would loop forever: the response carries no
        # total_pages to break on, so every pass re-yields the same rows.
        # The stage lookups answer with just the rows: no page params echoed, no pagination object.
        result = _driver().run(endpoint, [ScriptedResponse(json={endpoint: [{"id": "s1"}]})])

        assert [item["id"] for item in result.rows] == ["s1"]
        assert result.raised is None
        assert len(result.requests) == 1
        assert result.requests[0].method == "GET"
        assert result.requests[0].query == {}
        assert result.saved_states == []

    def test_users_paginates_with_query_params(self) -> None:
        # Page params have to ride the query string on this GET; sent as a body they are
        # ignored and every page comes back as page 1.
        result = _driver().run(
            "users", [_page("users", [{"id": "u1"}], total_pages=2), _page("users", [{"id": "u2"}], total_pages=2)]
        )

        assert [item["id"] for item in result.rows] == ["u1", "u2"]
        assert result.raised is None
        assert result.params("page") == ["1", "2"]
        assert result.params("per_page") == [str(PAGE_SIZE), str(PAGE_SIZE)]

    def test_search_cap_is_logged(self) -> None:
        logger = mock.MagicMock()
        result = _driver().run(
            "contacts",
            [_page("contacts", [{"id": "c", "updated_at": "2024-01-01T00:00:00Z"}], MAX_PAGES + 10)],
            resume_state=ApolloResumeConfig(page=MAX_PAGES),
            logger=logger,
        )

        assert result.raised is None
        assert len(result.items) == 1
        assert result.requests[0].json()["page"] == MAX_PAGES
        assert len(result.requests) == 1
        logger.error.assert_called_once()

    def test_search_cap_is_logged_when_total_pages_equals_cap(self) -> None:
        # Exactly at the cap: the final reachable page coincides with total_pages,
        # so the cap must still be logged rather than swallowed by the total_pages break.
        logger = mock.MagicMock()
        result = _driver().run(
            "contacts",
            [_page("contacts", [{"id": "c", "updated_at": "2024-01-01T00:00:00Z"}], MAX_PAGES)],
            resume_state=ApolloResumeConfig(page=MAX_PAGES),
            logger=logger,
        )

        assert result.raised is None
        assert len(result.items) == 1
        assert result.requests[0].json()["page"] == MAX_PAGES
        assert len(result.requests) == 1
        logger.error.assert_called_once()

    def test_incremental_keeps_records_without_parseable_updated_at(self) -> None:
        # A record with a missing updated_at must not be dropped, and must not stop
        # the walk before a genuinely older record is reached.
        page = [
            {"id": "new", "updated_at": "2024-06-01T00:00:00Z"},
            {"id": "no-ts"},
            {"id": "old", "updated_at": "2024-01-01T00:00:00Z"},
        ]
        result = _driver().run(
            "contacts",
            [_page("contacts", page, total_pages=5)],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2024, 3, 1, tzinfo=UTC),
        )

        assert [item["id"] for item in result.rows] == ["new", "no-ts"]
        assert result.raised is None
        assert len(result.requests) == 1


class TestApolloSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint: str) -> None:
        config = APOLLO_ENDPOINTS[endpoint]
        result = _driver().run(endpoint, [ScriptedResponse(json={config.data_key: []})])
        response = result.response

        assert result.raised is None
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == [config.primary_key]
        assert response.sort_mode == ("desc" if config.sort_by_field else "asc")
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None

    @pytest.mark.parametrize("config", list(APOLLO_ENDPOINTS.values()))
    def test_partition_keys_are_stable_creation_fields(self, config):
        # A partition key that moves (updated_at, last_activity_date) rewrites partitions
        # on every sync. Only fields fixed when the record is written belong here.
        if config.partition_key:
            assert config.partition_key in {"created_at", "start_time"}


class TestRetryAfter:
    @pytest.mark.parametrize(
        "value, expected",
        [
            ("30", 30.0),
            (" 30 ", 30.0),
            ("0", 0.0),
            (None, None),
            ("", None),
            ("soon", None),
            # An HTTP-date already in the past clamps to no wait.
            ("Wed, 21 Oct 2015 07:28:00 GMT", 0.0),
        ],
    )
    def test_parse_retry_after(self, value, expected):
        assert _parse_retry_after(value) == expected

    def _state(self, exc: Exception) -> RetryCallState:
        state = RetryCallState(retry_object=mock.MagicMock(), fn=None, args=(), kwargs={})
        state.outcome = Future.construct(1, exc, has_exception=True)
        return state

    def test_wait_honors_retry_after_below_cap(self):
        assert _wait_apollo(self._state(ApolloRetryableError("rate limited", retry_after=45.0))) == 45.0

    def test_wait_caps_long_retry_after(self):
        # An hourly/daily window can dwarf the cap; a single retry must stay bounded.
        assert (
            _wait_apollo(self._state(ApolloRetryableError("rate limited", retry_after=99999.0)))
            == MAX_RETRY_AFTER_SECONDS
        )

    def test_429_is_retried_and_recovers(self) -> None:
        # Retry-After "0" keeps the retry instant while still proving the header is
        # read and honored end-to-end from the raise site through get_rows.
        result = _driver().run(
            "contacts",
            [
                ScriptedResponse(status=429, headers={"Retry-After": "0"}),
                _page("contacts", [{"id": "c1", "updated_at": "2024-01-01T00:00:00Z"}]),
            ],
        )

        assert [item["id"] for item in result.rows] == ["c1"]
        assert result.raised is None
        assert len(result.requests) == 2
