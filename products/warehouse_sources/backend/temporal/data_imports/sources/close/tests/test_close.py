import json
from datetime import UTC, date, datetime
from typing import Any, cast

import pytest
from unittest.mock import MagicMock

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.close.close import (
    INITIAL_INCREMENTAL_VALUE,
    CloseEventCursorPaginator,
    CloseOffsetPaginator,
    CloseResumeConfig,
    _format_close_datetime,
    _organization_ids,
    get_resource,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.close.source import CloseSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.close import CloseSourceConfig


class TestCloseOffsetPaginator:
    def test_update_state_empty_page_stops(self) -> None:
        paginator = CloseOffsetPaginator()
        response = MagicMock()
        response.json.return_value = {"data": [], "has_more": True}
        paginator.update_state(response, [])
        assert paginator.has_next_page is False

    def test_get_resume_state_none_on_terminal_page(self) -> None:
        paginator = CloseOffsetPaginator()
        response = MagicMock()
        response.json.return_value = {"data": [{"id": "user_1"}], "has_more": False}
        paginator.update_state(response, [{"id": "user_1"}])
        assert paginator.get_resume_state() is None


class TestFormatCloseDatetime:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC), "2024-01-02T03:04:05+00:00"),
            (date(2024, 1, 2), "2024-01-02T00:00:00+00:00"),
            ("2024-01-02T03:04:05+00:00", "2024-01-02T03:04:05+00:00"),
        ],
    )
    def test_formats_to_iso8601_utc(self, value: Any, expected: str) -> None:
        assert _format_close_datetime(value) == expected

    def test_unparseable_value_falls_back_to_str(self) -> None:
        assert _format_close_datetime("not-a-date") == "not-a-date"


def _endpoint(resource: Any) -> dict[str, Any]:
    return cast(dict[str, Any], resource["endpoint"])


def _params(resource: Any) -> dict[str, Any]:
    return cast(dict[str, Any], _endpoint(resource)["params"])


class TestGetResource:
    @pytest.mark.parametrize(
        "endpoint", ["Users", "Pipelines", "EmailTemplates", "Outcomes", "LeadCustomFields", "SharedCustomFields"]
    )
    def test_full_refresh_endpoints_never_incremental(self, endpoint: str) -> None:
        # Even when the user enables incremental, endpoints with no server-side date filter
        # stay on full replace and emit no `__gte` param.
        resource = get_resource(endpoint, should_use_incremental_field=True, incremental_field="date_created")
        assert resource["write_disposition"] == "replace"
        assert not any(key.endswith("__gte") for key in _params(resource))


class TestCloseSourcePartitioning:
    @pytest.mark.parametrize(
        ("endpoint", "expects_partition"),
        [
            ("Leads", True),
            ("Contacts", True),
            ("Opportunities", True),
            ("Activities", True),
            ("Tasks", True),
            ("Events", True),
            ("Users", False),
            ("LeadStatuses", False),
            ("Pipelines", False),
            ("Outcomes", False),
            ("LeadCustomFields", False),
        ],
    )
    def test_partition_config(self, endpoint: str, expects_partition: bool) -> None:
        result = SourceDriver(CloseSource(), CloseSourceConfig(api_key="test-key")).run(
            endpoint, [ScriptedResponse(json={"data": []})]
        )
        assert result.raised is None
        response = result.response
        assert response is not None

        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        if expects_partition:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == ["date_created"]
            assert response.partition_format == "month"
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None


def _make_http_response(body: dict[str, Any], status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    resp.headers["Content-Type"] = "application/json"
    return resp


class TestCloseSourceResumeBehavior:
    """End-to-end resume behaviour of ``CloseSource`` via ``rest_api_resource``."""

    @staticmethod
    def _driver() -> SourceDriver:
        return SourceDriver(CloseSource(), CloseSourceConfig(api_key="test-key"))

    @staticmethod
    def _page(rows: list[dict[str, Any]], has_more: bool) -> ScriptedResponse:
        return ScriptedResponse(json={"data": rows, "has_more": has_more})

    def test_fresh_run_saves_skip_after_each_non_terminal_page(self) -> None:
        result = self._driver().run(
            "Users",
            [
                self._page([{"id": "user_1"}], True),
                self._page([{"id": "user_2"}], True),
                self._page([{"id": "user_3"}], False),
            ],
        )

        assert result.raised is None
        assert result.params("_skip") == ["0", "100", "200"]
        assert result.rows == [{"id": "user_1"}, {"id": "user_2"}, {"id": "user_3"}]
        assert result.saved_states == [CloseResumeConfig(next_skip=100), CloseResumeConfig(next_skip=200)]

    def test_resume_seeds_paginator_with_saved_skip(self) -> None:
        result = self._driver().run(
            "Users", [self._page([{"id": "user_9"}], False)], resume_state=CloseResumeConfig(next_skip=200)
        )

        assert result.raised is None
        assert result.params("_skip") == ["200"]

    def test_does_not_load_state_when_cannot_resume(self) -> None:
        result = self._driver().run("Users", [self._page([{"id": "a"}], False)])

        assert result.raised is None
        assert result.params("_skip") == ["0"]

    def test_incremental_request_carries_gte_and_order_by(self) -> None:
        result = self._driver().run(
            "Opportunities",
            [self._page([{"id": "oppo_1"}], False)],
            incremental_field="date_created",
        )

        assert result.raised is None
        assert result.requests[0].param("date_created__gte") == INITIAL_INCREMENTAL_VALUE
        assert result.requests[0].param("_order_by") == "date_created"

    def test_events_stop_once_a_page_predates_the_watermark(self) -> None:
        # Without the client-side stop the cursor walk would keep going back through Close's
        # whole retention window on every incremental sync.
        result = self._driver().run(
            "Events",
            [
                ScriptedResponse(
                    json={
                        "data": [{"id": "ev_2", "date_updated": "2024-06-05T00:00:00+00:00"}],
                        "cursor_next": "cursor_2",
                    }
                ),
                ScriptedResponse(
                    json={
                        "data": [{"id": "ev_1", "date_updated": "2024-05-20T00:00:00+00:00"}],
                        "cursor_next": "cursor_3",
                    }
                ),
            ],
            incremental_field="date_updated",
            db_incremental_field_last_value=datetime(2024, 6, 1, 12, 0, 0, tzinfo=UTC),
        )

        assert result.raised is None
        assert result.paths == ["/api/v1/event/", "/api/v1/event/"]
        assert result.params("_cursor") == [None, "cursor_2"]

    def test_events_resume_seeds_the_saved_cursor(self) -> None:
        result = self._driver().run(
            "Events",
            [
                ScriptedResponse(
                    json={"data": [{"id": "ev_9", "date_updated": "2024-06-05T00:00:00+00:00"}], "cursor_next": None}
                )
            ],
            resume_state=CloseResumeConfig(next_cursor="cursor_7"),
        )

        assert result.raised is None
        assert result.requests[0].param("_cursor") == "cursor_7"


class TestCloseEventCursorPaginator:
    @staticmethod
    def _page(rows: list[dict[str, Any]], cursor_next: str | None) -> Response:
        return _make_http_response({"data": rows, "cursor_next": cursor_next})

    def test_empty_page_stops(self) -> None:
        paginator = CloseEventCursorPaginator()
        paginator.update_state(self._page([], "cursor_2"), [])
        assert paginator.has_next_page is False

    def test_a_row_we_cannot_date_keeps_the_walk_going(self) -> None:
        # An unparseable timestamp says nothing about whether the page predates the watermark,
        # so stopping on the rows we can read would skip everything behind it.
        paginator = CloseEventCursorPaginator(stop_when_older_than=datetime(2024, 6, 1, 12, 0, 0, tzinfo=UTC))
        rows: list[dict[str, Any]] = [
            {"id": "ev_1", "date_updated": "2024-05-01T00:00:00+00:00"},
            {"id": "ev_2", "date_updated": None},
        ]

        paginator.update_state(self._page(rows, "cursor_2"), rows)

        assert paginator.has_next_page is True

    def test_a_cursor_that_repeats_raises(self) -> None:
        # Following it again would re-request the same page for as long as the activity runs.
        paginator = CloseEventCursorPaginator()
        rows = [{"id": "ev_1", "date_updated": "2024-06-05T00:00:00+00:00"}]
        paginator.update_state(self._page(rows, "cursor_2"), rows)

        with pytest.raises(ValueError, match="same event cursor twice"):
            paginator.update_state(self._page(rows, "cursor_2"), rows)

    def test_no_resume_state_on_terminal_page(self) -> None:
        paginator = CloseEventCursorPaginator()
        rows = [{"id": "ev_1", "date_updated": "2024-06-05T00:00:00+00:00"}]
        paginator.update_state(self._page(rows, None), rows)
        assert paginator.get_resume_state() is None


class TestCloseOrganizationsSource:
    @pytest.mark.parametrize(
        ("me", "expected"),
        [
            ({"organizations": [{"id": "orga_1"}]}, ["orga_1"]),
            ({"memberships": [{"organization_id": "orga_1"}]}, ["orga_1"]),
            # `/me/` lists the same org under both keys, and each row must only be fetched once.
            ({"organizations": [{"id": "orga_1"}], "memberships": [{"organization_id": "orga_1"}]}, ["orga_1"]),
            (
                {"organizations": [{"id": "orga_1"}], "memberships": [{"organization_id": "orga_2"}]},
                ["orga_1", "orga_2"],
            ),
            ({}, []),
        ],
    )
    def test_organization_ids(self, me: dict[str, Any], expected: list[str]) -> None:
        assert _organization_ids(me) == expected

    def test_fetches_each_organization_named_by_me(self) -> None:
        # Close publishes no `/organization/` list endpoint, so a missed `/me/` hop syncs nothing.
        result = SourceDriver(CloseSource(), CloseSourceConfig(api_key="api_test")).run(
            "Organizations",
            [
                ScriptedResponse(json={"organizations": [{"id": "orga_1"}, {"id": "orga_2"}]}),
                ScriptedResponse(json={"id": "orga_1", "name": "First"}),
                ScriptedResponse(json={"id": "orga_2", "name": "Second"}),
            ],
        )

        assert result.raised is None
        assert result.paths == [
            "/api/v1/me/",
            "/api/v1/organization/orga_1/",
            "/api/v1/organization/orga_2/",
        ]
        assert result.items == [[{"id": "orga_1", "name": "First"}, {"id": "orga_2", "name": "Second"}]]
        assert result.response is not None
        assert result.response.primary_keys == ["id"]


class TestValidateCredentials:
    @pytest.mark.parametrize(
        ("status_code", "expected"),
        [
            (200, True),
        ],
    )
    def test_status_code_mapping(self, status_code: int, expected: bool) -> None:
        with scripted_network(always(ScriptedResponse(status=status_code))) as network:
            assert validate_credentials("api_test") is expected

        assert {request.path for request in network.requests_log} == {"/api/v1/me/"}

    def test_network_error_returns_false(self) -> None:
        with scripted_network(always(ConnectionError("boom"))) as network:
            assert validate_credentials("api_test") is False

        assert {request.path for request in network.requests_log} == {"/api/v1/me/"}
