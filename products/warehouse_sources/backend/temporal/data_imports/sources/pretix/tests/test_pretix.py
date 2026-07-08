from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import parse_qs, urlparse

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.pretix import pretix as px
from products.warehouse_sources.backend.temporal.data_imports.sources.pretix.pretix import (
    HOST_NOT_ALLOWED_ERROR,
    INVALID_ORGANIZER_ERROR,
    PretixHostNotAllowedError,
    PretixResumeConfig,
    PretixRetryableError,
    _fetch_page,
    _format_modified_since,
    _parse_retry_after,
    _quote_organizer,
    get_rows,
    normalize_base_url,
    pretix_source,
    validate_credentials,
)

LOGGER = mock.MagicMock()


def _no_resume_manager() -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = False
    return manager


def _response(
    status_code: int = 200,
    json_data: Any = None,
    headers: dict[str, str] | None = None,
    is_redirect: bool = False,
) -> mock.MagicMock:
    response = mock.MagicMock()
    response.status_code = status_code
    response.headers = headers or {}
    response.is_redirect = is_redirect
    response.is_permanent_redirect = False
    response.ok = status_code < 400
    response.json.return_value = json_data
    return response


def _page(items: list[dict[str, Any]], next_url: Optional[str]) -> dict[str, Any]:
    return {"count": len(items), "next": next_url, "previous": None, "results": items}


class TestNormalizeBaseUrl:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            (None, "https://pretix.eu/api/v1"),
            ("", "https://pretix.eu/api/v1"),
            ("  ", "https://pretix.eu/api/v1"),
            ("tickets.example.com", "https://tickets.example.com/api/v1"),
            ("https://tickets.example.com", "https://tickets.example.com/api/v1"),
            ("https://tickets.example.com/", "https://tickets.example.com/api/v1"),
            ("https://tickets.example.com/api/v1", "https://tickets.example.com/api/v1"),
            ("http://tickets.example.com", "http://tickets.example.com/api/v1"),
        ],
    )
    def test_normalize_base_url(self, raw: Optional[str], expected: str) -> None:
        assert normalize_base_url(raw) == expected


class TestFormatModifiedSince:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14Z"),
            (datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14Z"),
            (date(2026, 3, 4), "2026-03-04T00:00:00Z"),
            ("2026-03-04T02:58:14Z", "2026-03-04T02:58:14Z"),
        ],
    )
    def test_format_modified_since(self, value: object, expected: str) -> None:
        assert _format_modified_since(value) == expected


class TestQuoteOrganizer:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("my-organizer", "my-organizer"),
            (" my-organizer ", "my-organizer"),
            ("/my-organizer/", "my-organizer"),
            ("a/../b", "a%2F..%2Fb"),
        ],
    )
    def test_quotes_path_segments(self, raw: str, expected: str) -> None:
        assert _quote_organizer(raw) == expected

    @pytest.mark.parametrize("raw", ["", "  ", "/"])
    def test_rejects_empty(self, raw: str) -> None:
        with pytest.raises(ValueError, match=INVALID_ORGANIZER_ERROR):
            _quote_organizer(raw)


class TestFetchPage:
    # `_fetch_page.__wrapped__` bypasses the tenacity retry loop so failures don't sleep.

    def test_returns_items_and_next_url(self) -> None:
        session = mock.MagicMock()
        session.get.return_value = _response(json_data=_page([{"id": 1}], "https://pretix.eu/api/v1/x/?page=2"))

        items, next_url = _fetch_page.__wrapped__(session, "https://pretix.eu/api/v1/x/", LOGGER)

        assert items == [{"id": 1}]
        assert next_url == "https://pretix.eu/api/v1/x/?page=2"

    def test_null_next_terminates(self) -> None:
        session = mock.MagicMock()
        session.get.return_value = _response(json_data=_page([{"id": 1}], None))

        _, next_url = _fetch_page.__wrapped__(session, "https://pretix.eu/api/v1/x/", LOGGER)

        assert next_url is None

    def test_429_raises_retryable_with_retry_after(self) -> None:
        session = mock.MagicMock()
        session.get.return_value = _response(status_code=429, headers={"Retry-After": "7"})

        with pytest.raises(PretixRetryableError) as exc_info:
            _fetch_page.__wrapped__(session, "https://pretix.eu/api/v1/x/", LOGGER)

        assert exc_info.value.retry_after == 7.0

    def test_5xx_raises_retryable(self) -> None:
        session = mock.MagicMock()
        session.get.return_value = _response(status_code=503)

        with pytest.raises(PretixRetryableError):
            _fetch_page.__wrapped__(session, "https://pretix.eu/api/v1/x/", LOGGER)

    def test_redirect_is_rejected(self) -> None:
        session = mock.MagicMock()
        session.get.return_value = _response(status_code=302, is_redirect=True)

        with pytest.raises(PretixHostNotAllowedError):
            _fetch_page.__wrapped__(session, "https://pretix.eu/api/v1/x/", LOGGER)

    def test_unexpected_payload_raises_retryable(self) -> None:
        session = mock.MagicMock()
        session.get.return_value = _response(json_data=[{"id": 1}])

        with pytest.raises(PretixRetryableError):
            _fetch_page.__wrapped__(session, "https://pretix.eu/api/v1/x/", LOGGER)

    @pytest.mark.parametrize(
        "headers, expected",
        [
            ({"Retry-After": "7"}, 7.0),
            ({"Retry-After": "999"}, 60.0),
            ({"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"}, None),
            ({}, None),
        ],
    )
    def test_parse_retry_after(self, headers: dict[str, str], expected: float | None) -> None:
        assert _parse_retry_after(_response(status_code=429, headers=headers)) == expected


@mock.patch.object(px, "_is_host_safe", return_value=(True, None))
@mock.patch.object(px, "make_tracked_session", return_value=mock.MagicMock())
class TestGetRowsOrganizerScope:
    @mock.patch.object(px, "_fetch_page")
    def test_orders_incremental_url_has_filter_and_stable_ordering(
        self, mock_fetch: mock.MagicMock, _session: mock.MagicMock, _host: mock.MagicMock
    ) -> None:
        mock_fetch.return_value = ([{"code": "A1", "event": "conf"}], None)

        list(
            get_rows(
                api_token="tok",
                organizer="acme",
                base_url=None,
                endpoint="orders",
                team_id=1,
                logger=LOGGER,
                resumable_source_manager=_no_resume_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
                incremental_field="last_modified",
            )
        )

        url = mock_fetch.call_args[0][1]
        parsed = urlparse(url)
        assert parsed.path == "/api/v1/organizers/acme/orders/"
        query = parse_qs(parsed.query)
        assert query["modified_since"] == ["2026-01-01T00:00:00Z"]
        assert query["ordering"] == ["last_modified"]

    @pytest.mark.parametrize(
        "should_use, incremental_field",
        [
            (False, "last_modified"),
            # A user-selected cursor the server filter doesn't target must not be silently rewritten
            # into a `modified_since` filter.
            (True, "datetime"),
        ],
    )
    @mock.patch.object(px, "_fetch_page")
    def test_no_modified_since_when_not_applicable(
        self,
        mock_fetch: mock.MagicMock,
        _session: mock.MagicMock,
        _host: mock.MagicMock,
        should_use: bool,
        incremental_field: str,
    ) -> None:
        mock_fetch.return_value = ([], None)

        list(
            get_rows(
                api_token="tok",
                organizer="acme",
                base_url=None,
                endpoint="orders",
                team_id=1,
                logger=LOGGER,
                resumable_source_manager=_no_resume_manager(),
                should_use_incremental_field=should_use,
                db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
                incremental_field=incremental_field,
            )
        )

        url = mock_fetch.call_args[0][1]
        assert "modified_since" not in url

    @mock.patch.object(px, "_fetch_page")
    def test_state_saved_only_after_page_is_yielded(
        self, mock_fetch: mock.MagicMock, _session: mock.MagicMock, _host: mock.MagicMock
    ) -> None:
        next_url = "https://pretix.eu/api/v1/organizers/acme/orders/?page=2"
        mock_fetch.side_effect = [
            ([{"code": "A1"}], next_url),
            ([{"code": "A2"}], None),
        ]
        manager = _no_resume_manager()

        rows = get_rows(
            api_token="tok",
            organizer="acme",
            base_url=None,
            endpoint="orders",
            team_id=1,
            logger=LOGGER,
            resumable_source_manager=manager,
        )

        assert next(rows) == [{"code": "A1"}]
        # A crash here must re-fetch page 1 (nothing persisted yet), not skip it.
        manager.save_state.assert_not_called()

        assert next(rows) == [{"code": "A2"}]
        manager.save_state.assert_called_once_with(PretixResumeConfig(next_url=next_url))

    @mock.patch.object(px, "_fetch_page")
    def test_resumes_from_saved_next_url(
        self, mock_fetch: mock.MagicMock, _session: mock.MagicMock, _host: mock.MagicMock
    ) -> None:
        saved_url = "https://pretix.eu/api/v1/organizers/acme/orders/?page=5"
        manager = mock.MagicMock()
        manager.can_resume.return_value = True
        manager.load_state.return_value = PretixResumeConfig(next_url=saved_url)
        mock_fetch.return_value = ([{"code": "A9"}], None)

        list(
            get_rows(
                api_token="tok",
                organizer="acme",
                base_url=None,
                endpoint="orders",
                team_id=1,
                logger=LOGGER,
                resumable_source_manager=manager,
            )
        )

        assert mock_fetch.call_args[0][1] == saved_url

    def test_unsafe_host_raises_before_any_request(
        self, session_factory: mock.MagicMock, mock_host: mock.MagicMock
    ) -> None:
        mock_host.return_value = (False, HOST_NOT_ALLOWED_ERROR)

        with pytest.raises(PretixHostNotAllowedError):
            list(
                get_rows(
                    api_token="tok",
                    organizer="acme",
                    base_url="https://internal.example.com",
                    endpoint="orders",
                    team_id=1,
                    logger=LOGGER,
                    resumable_source_manager=_no_resume_manager(),
                )
            )

        session_factory.return_value.get.assert_not_called()

    def test_http_base_url_raises(self, session_factory: mock.MagicMock, _host: mock.MagicMock) -> None:
        with pytest.raises(PretixHostNotAllowedError):
            list(
                get_rows(
                    api_token="tok",
                    organizer="acme",
                    base_url="http://tickets.example.com",
                    endpoint="orders",
                    team_id=1,
                    logger=LOGGER,
                    resumable_source_manager=_no_resume_manager(),
                )
            )

        session_factory.return_value.get.assert_not_called()


@mock.patch.object(px, "_is_host_safe", return_value=(True, None))
@mock.patch.object(px, "make_tracked_session", return_value=mock.MagicMock())
class TestGetRowsEventFanOut:
    @mock.patch.object(px, "_fetch_page")
    def test_fans_out_per_event_and_stamps_event_slug(
        self, mock_fetch: mock.MagicMock, _session: mock.MagicMock, _host: mock.MagicMock
    ) -> None:
        def router(_session: Any, url: str, _logger: Any) -> tuple[list[dict[str, Any]], Optional[str]]:
            path = urlparse(url).path
            if path == "/api/v1/organizers/acme/events/":
                return [{"slug": "conf-a"}, {"slug": "conf-b"}], None
            if path == "/api/v1/organizers/acme/events/conf-a/items/":
                return [{"id": 1}], None
            if path == "/api/v1/organizers/acme/events/conf-b/items/":
                return [{"id": 1}, {"id": 2}], None
            raise AssertionError(f"unexpected url {url}")

        mock_fetch.side_effect = router
        manager = _no_resume_manager()

        pages = list(
            get_rows(
                api_token="tok",
                organizer="acme",
                base_url=None,
                endpoint="items",
                team_id=1,
                logger=LOGGER,
                resumable_source_manager=manager,
            )
        )

        rows = [row for page in pages for row in page]
        # The composite primary key (event_slug, id) must stay unique even though both events reuse id=1.
        assert [(row["event_slug"], row["id"]) for row in rows] == [("conf-a", 1), ("conf-b", 1), ("conf-b", 2)]
        # Fan-out endpoints restart from the first event on resume; no partial state may be persisted.
        manager.save_state.assert_not_called()

    @mock.patch.object(px, "_fetch_page")
    def test_event_slug_is_url_quoted_in_child_path(
        self, mock_fetch: mock.MagicMock, _session: mock.MagicMock, _host: mock.MagicMock
    ) -> None:
        seen_urls: list[str] = []

        def router(_session: Any, url: str, _logger: Any) -> tuple[list[dict[str, Any]], Optional[str]]:
            seen_urls.append(url)
            if urlparse(url).path == "/api/v1/organizers/acme/events/":
                return [{"slug": "a/b"}], None
            return [], None

        mock_fetch.side_effect = router

        list(
            get_rows(
                api_token="tok",
                organizer="acme",
                base_url=None,
                endpoint="items",
                team_id=1,
                logger=LOGGER,
                resumable_source_manager=_no_resume_manager(),
            )
        )

        assert any("/events/a%2Fb/items/" in url for url in seen_urls)


@mock.patch.object(px, "_is_host_safe", return_value=(True, None))
class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected_valid, message_fragment",
        [
            (200, True, None),
            (401, False, "Invalid pretix API token"),
            (403, False, "does not have access to this organizer"),
            (500, False, "HTTP 500"),
        ],
    )
    @mock.patch.object(px, "make_tracked_session")
    def test_status_mapping(
        self,
        session_factory: mock.MagicMock,
        _host: mock.MagicMock,
        status_code: int,
        expected_valid: bool,
        message_fragment: str | None,
    ) -> None:
        session = mock.MagicMock()
        session.get.return_value = _response(status_code=status_code)
        session_factory.return_value = session

        is_valid, message = validate_credentials("tok", "acme", None, team_id=1)

        assert is_valid is expected_valid
        if message_fragment is None:
            assert message is None
        else:
            assert message is not None and message_fragment in message

    @mock.patch.object(px, "make_tracked_session")
    def test_redirect_is_rejected(self, session_factory: mock.MagicMock, _host: mock.MagicMock) -> None:
        session = mock.MagicMock()
        session.get.return_value = _response(status_code=302, is_redirect=True)
        session_factory.return_value = session

        is_valid, message = validate_credentials("tok", "acme", None, team_id=1)

        assert is_valid is False
        assert message == HOST_NOT_ALLOWED_ERROR

    @mock.patch.object(px, "make_tracked_session")
    def test_connection_error_returns_message(self, session_factory: mock.MagicMock, _host: mock.MagicMock) -> None:
        session = mock.MagicMock()
        session.get.side_effect = Exception("network down")
        session_factory.return_value = session

        is_valid, message = validate_credentials("tok", "acme", None, team_id=1)

        assert is_valid is False
        assert message is not None and "Could not connect to pretix" in message

    @mock.patch.object(px, "make_tracked_session")
    def test_invalid_organizer_rejected_without_request(
        self, session_factory: mock.MagicMock, _host: mock.MagicMock
    ) -> None:
        is_valid, message = validate_credentials("tok", "  ", None, team_id=1)

        assert is_valid is False
        assert message == INVALID_ORGANIZER_ERROR
        session_factory.assert_not_called()

    @mock.patch.object(px, "make_tracked_session")
    def test_http_base_url_rejected_without_request(
        self, session_factory: mock.MagicMock, _host: mock.MagicMock
    ) -> None:
        is_valid, message = validate_credentials("tok", "acme", "http://tickets.example.com", team_id=1)

        assert is_valid is False
        assert message is not None and "HTTPS" in message
        session_factory.assert_not_called()


class TestPretixSourceResponse:
    def _source(self, endpoint: str):
        return pretix_source(
            api_token="tok",
            organizer="acme",
            base_url=None,
            endpoint=endpoint,
            team_id=1,
            logger=LOGGER,
            resumable_source_manager=mock.MagicMock(),
        )

    def test_orders_partitioned_on_stable_creation_datetime(self) -> None:
        response = self._source("orders")

        assert response.name == "orders"
        assert response.primary_keys == ["event", "code"]
        assert response.partition_mode == "datetime"
        assert response.partition_format == "month"
        assert response.partition_keys == ["datetime"]
        assert response.sort_mode == "asc"

    @pytest.mark.parametrize(
        "endpoint, primary_keys",
        [
            ("events", ["slug"]),
            ("invoices", ["event", "number"]),
            ("customers", ["identifier"]),
            ("gift_cards", ["id"]),
            ("items", ["event_slug", "id"]),
            ("vouchers", ["event_slug", "id"]),
        ],
    )
    def test_primary_keys_per_endpoint(self, endpoint: str, primary_keys: list[str]) -> None:
        response = self._source(endpoint)

        assert response.primary_keys == primary_keys
        assert response.partition_mode is None
