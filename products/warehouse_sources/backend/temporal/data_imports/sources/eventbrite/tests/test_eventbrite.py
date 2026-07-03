from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.eventbrite import eventbrite as eb
from products.warehouse_sources.backend.temporal.data_imports.sources.eventbrite.eventbrite import (
    EventbriteResumeConfig,
    _format_changed_since,
    _iter_pages,
    _iter_records,
    eventbrite_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.eventbrite.settings import EVENTBRITE_ENDPOINTS

LOGGER = mock.MagicMock()
SESSION = mock.MagicMock()


def _page(data_key: str, items: list[dict[str, Any]], continuation: str | None) -> dict[str, Any]:
    return {
        data_key: items,
        "pagination": {"has_more_items": continuation is not None, "continuation": continuation},
    }


class TestFormatChangedSince:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14Z"),
            (datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14Z"),
            (date(2026, 3, 4), "2026-03-04T00:00:00Z"),
            ("already-a-cursor", "already-a-cursor"),
        ],
    )
    def test_format_changed_since(self, value: object, expected: str) -> None:
        assert _format_changed_since(value) == expected

    def test_no_plus_offset_in_output(self) -> None:
        result = _format_changed_since(datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC))
        assert "+00:00" not in result
        assert result.endswith("Z")


class TestIterPages:
    @mock.patch.object(eb, "_fetch_page")
    def test_follows_continuation_until_exhausted(self, mock_fetch: mock.MagicMock) -> None:
        mock_fetch.side_effect = [
            _page("events", [{"id": "1"}, {"id": "2"}], "tok2"),
            _page("events", [{"id": "3"}], None),
        ]

        results = list(_iter_pages(SESSION, "https://x/events/", {}, "events", LOGGER))

        assert [record["id"] for record, _ in results] == ["1", "2", "3"]
        # Resume token: mid-page items carry the current page's token (None for the first page, which
        # restarts from the start); only the last item of a page advances to the next page's token.
        assert [token for _, token in results] == [None, "tok2", None]
        assert mock_fetch.call_count == 2

    @mock.patch.object(eb, "_fetch_page")
    def test_starts_from_resume_continuation(self, mock_fetch: mock.MagicMock) -> None:
        mock_fetch.side_effect = [_page("events", [{"id": "9"}], None)]

        list(_iter_pages(SESSION, "https://x/events/", {}, "events", LOGGER, start_continuation="resume-tok"))

        _, _, params, _ = mock_fetch.call_args[0]
        assert params["continuation"] == "resume-tok"

    @mock.patch.object(eb, "_fetch_page")
    def test_mid_page_records_carry_current_page_token(self, mock_fetch: mock.MagicMock) -> None:
        # Resuming from a mid-page record must re-fetch the page it came from, not the next one,
        # otherwise the rest of that page is skipped. Non-final items therefore carry the token that
        # fetched their own (here second) page rather than the next page's token.
        mock_fetch.side_effect = [
            _page("events", [{"id": "1"}], "tok2"),
            _page("events", [{"id": "2"}, {"id": "3"}], "tok3"),
            _page("events", [{"id": "4"}], None),
        ]

        results = list(_iter_pages(SESSION, "https://x/events/", {}, "events", LOGGER))

        assert [record["id"] for record, _ in results] == ["1", "2", "3", "4"]
        assert [token for _, token in results] == ["tok2", "tok2", "tok3", None]

    @mock.patch.object(eb, "_fetch_page")
    def test_handles_empty_page(self, mock_fetch: mock.MagicMock) -> None:
        mock_fetch.side_effect = [_page("events", [], None)]

        assert list(_iter_pages(SESSION, "https://x/events/", {}, "events", LOGGER)) == []


class TestIterRecords:
    @mock.patch.object(eb, "_fetch_page")
    def test_top_level_uses_resume_continuation(self, mock_fetch: mock.MagicMock) -> None:
        mock_fetch.side_effect = [_page("organizations", [{"id": "o1"}], None)]
        config = EVENTBRITE_ENDPOINTS["organizations"]

        list(_iter_records(SESSION, config, LOGGER, None, EventbriteResumeConfig(continuation="resume-tok")))

        _, url, params, _ = mock_fetch.call_args[0]
        assert url.endswith("/users/me/organizations/")
        assert params["continuation"] == "resume-tok"

    @mock.patch.object(eb, "_fetch_page")
    def test_org_fan_out_builds_child_urls_and_no_resume_token(self, mock_fetch: mock.MagicMock) -> None:
        def router(_session: Any, url: str, _params: dict[str, Any], _logger: Any) -> dict[str, Any]:
            if url.endswith("/users/me/organizations/"):
                return _page("organizations", [{"id": "org1"}, {"id": "org2"}], None)
            if url.endswith("/organizations/org1/events/"):
                return _page("events", [{"id": "e1"}], None)
            if url.endswith("/organizations/org2/events/"):
                return _page("events", [{"id": "e2"}], None)
            raise AssertionError(f"unexpected url {url}")

        mock_fetch.side_effect = router
        config = EVENTBRITE_ENDPOINTS["events"]

        results = list(_iter_records(SESSION, config, LOGGER, None, None))

        assert [record["id"] for record, _ in results] == ["e1", "e2"]
        assert all(token is None for _, token in results)

    @mock.patch.object(eb, "_fetch_page")
    def test_event_fan_out_is_two_levels(self, mock_fetch: mock.MagicMock) -> None:
        def router(_session: Any, url: str, _params: dict[str, Any], _logger: Any) -> dict[str, Any]:
            if url.endswith("/users/me/organizations/"):
                return _page("organizations", [{"id": "org1"}], None)
            if url.endswith("/organizations/org1/events/"):
                return _page("events", [{"id": "e1"}, {"id": "e2"}], None)
            if url.endswith("/events/e1/attendees/"):
                return _page("attendees", [{"id": "a1"}], None)
            if url.endswith("/events/e2/attendees/"):
                return _page("attendees", [{"id": "a2"}], None)
            raise AssertionError(f"unexpected url {url}")

        mock_fetch.side_effect = router
        config = EVENTBRITE_ENDPOINTS["attendees"]

        results = list(_iter_records(SESSION, config, LOGGER, None, None))

        assert [record["id"] for record, _ in results] == ["a1", "a2"]

    @mock.patch.object(eb, "_fetch_page")
    def test_changed_since_applied_only_to_child_endpoint(self, mock_fetch: mock.MagicMock) -> None:
        seen_params: dict[str, dict[str, Any]] = {}

        def router(_session: Any, url: str, params: dict[str, Any], _logger: Any) -> dict[str, Any]:
            seen_params[url] = params
            if url.endswith("/users/me/organizations/"):
                return _page("organizations", [{"id": "org1"}], None)
            if url.endswith("/organizations/org1/orders/"):
                return _page("orders", [{"id": "ord1"}], None)
            raise AssertionError(f"unexpected url {url}")

        mock_fetch.side_effect = router
        config = EVENTBRITE_ENDPOINTS["orders"]

        list(_iter_records(SESSION, config, LOGGER, "2026-01-01T00:00:00Z", None))

        # The parent organizations listing must not be narrowed by the child's incremental filter.
        org_url = next(u for u in seen_params if u.endswith("/users/me/organizations/"))
        order_url = next(u for u in seen_params if u.endswith("/organizations/org1/orders/"))
        assert "changed_since" not in seen_params[org_url]
        assert seen_params[order_url]["changed_since"] == "2026-01-01T00:00:00Z"


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected",
        [(200, True), (401, False), (403, False), (500, False)],
    )
    @mock.patch.object(eb, "make_tracked_session")
    def test_validate_credentials_status_mapping(
        self, mock_session_factory: mock.MagicMock, status_code: int, expected: bool
    ) -> None:
        session = mock.MagicMock()
        session.get.return_value.status_code = status_code
        mock_session_factory.return_value = session

        assert validate_credentials("token") is expected

    @mock.patch.object(eb, "make_tracked_session")
    def test_validate_credentials_swallows_exceptions(self, mock_session_factory: mock.MagicMock) -> None:
        session = mock.MagicMock()
        session.get.side_effect = Exception("network down")
        mock_session_factory.return_value = session

        assert validate_credentials("token") is False


class TestEventbriteSourceResponse:
    @pytest.mark.parametrize("endpoint", ["organizations", "events", "orders", "attendees"])
    def test_partitioned_endpoints(self, endpoint: str) -> None:
        response = eventbrite_source(
            api_token="token", endpoint=endpoint, logger=LOGGER, resumable_source_manager=mock.MagicMock()
        )

        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        assert response.partition_mode == "datetime"
        assert response.partition_format == "week"
        assert response.partition_keys == ["created"]

    @pytest.mark.parametrize("endpoint", ["categories", "formats", "venues", "ticket_classes"])
    def test_non_partitioned_endpoints(self, endpoint: str) -> None:
        response = eventbrite_source(
            api_token="token", endpoint=endpoint, logger=LOGGER, resumable_source_manager=mock.MagicMock()
        )

        assert response.partition_mode is None
        assert response.partition_keys is None
