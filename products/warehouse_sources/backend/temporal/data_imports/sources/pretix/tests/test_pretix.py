import json
from datetime import UTC, date, datetime
from typing import Any, Optional

import pytest
from unittest import mock

from parameterized import parameterized
from requests import Response
from requests.structures import CaseInsensitiveDict

from products.warehouse_sources.backend.temporal.data_imports.sources.pretix import pretix as px
from products.warehouse_sources.backend.temporal.data_imports.sources.pretix.pretix import (
    HOST_NOT_ALLOWED_ERROR,
    INVALID_ORGANIZER_ERROR,
    PretixHostNotAllowedError,
    PretixResumeConfig,
    _format_modified_since,
    _quote_organizer,
    normalize_base_url,
    pretix_source,
    validate_credentials,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# tenacity sleeps between the client's own retries — patch it so retry tests don't actually wait.
SLEEP_PATCH = "tenacity.nap.time.sleep"


def _envelope(items: list[dict[str, Any]], next_url: Optional[str]) -> Response:
    body = {"count": len(items), "next": next_url, "previous": None, "results": items}
    return _json_response(body)


def _json_response(body: Any, status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    return resp


def _status_response(status_code: int, headers: Optional[dict[str, str]] = None) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = b"{}"
    if headers:
        resp.headers = CaseInsensitiveDict(headers)
    return resp


def _make_manager(resume_state: PretixResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> tuple[list[str], list[dict[str, Any]]]:
    """Wire a mock session and capture each request's URL and params AT SEND TIME.

    ``request.url``/``request.params`` are mutated in place across pages (the paginator rewrites the
    URL to the next-page link), so snapshot a copy when each request is prepared. ``prepared.url`` must
    be the real string so the client's ``allowed_hosts`` check can parse a host from it.
    """
    session.headers = {}
    url_snapshots: list[str] = []
    param_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        url_snapshots.append(request.url)
        param_snapshots.append(dict(request.params or {}))
        prepared = mock.MagicMock()
        prepared.url = request.url
        return prepared

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return url_snapshots, param_snapshots


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _pages(source_response):
    """Yield pages (not flattened) so a test can drive pagination one page at a time."""
    yield from source_response.items()


def _source(endpoint: str, manager: mock.MagicMock | None = None, base_url: str | None = None, **kwargs: Any):
    return pretix_source(
        api_token="tok",
        organizer="acme",
        base_url=base_url,
        endpoint=endpoint,
        team_id=1,
        job_id="j",
        resumable_source_manager=manager or _make_manager(),
        **kwargs,
    )


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


@mock.patch.object(px, "_is_host_safe", return_value=(True, None))
class TestOrganizerScopePagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_follows_next_link_and_terminates_on_null(self, MockSession, _host) -> None:
        session = MockSession.return_value
        page2 = "https://pretix.eu/api/v1/organizers/acme/orders/?page=2"
        urls, _params = _wire(
            session,
            [_envelope([{"code": "A1"}], page2), _envelope([{"code": "A2"}], None)],
        )

        rows = _rows(_source("orders"))

        assert [r["code"] for r in rows] == ["A1", "A2"]
        # The self-contained next link is followed verbatim; a null next ends pagination.
        assert urls[0].endswith("/organizers/acme/orders/")
        assert urls[1] == page2
        assert session.send.call_count == 2

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_orders_incremental_url_has_filter_and_stable_ordering(self, MockSession, _host) -> None:
        session = MockSession.return_value
        _urls, params = _wire(session, [_envelope([{"code": "A1", "event": "conf"}], None)])

        _rows(
            _source(
                "orders",
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
                incremental_field="last_modified",
            )
        )

        assert params[0]["modified_since"] == "2026-01-01T00:00:00Z"
        assert params[0]["ordering"] == "last_modified"

    @parameterized.expand(
        [
            (False, "last_modified"),
            # A user-selected cursor the server filter doesn't target must not be silently rewritten
            # into a `modified_since` filter.
            (True, "datetime"),
        ]
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_no_modified_since_when_not_applicable(
        self, should_use: bool, incremental_field: str, MockSession, _host
    ) -> None:
        session = MockSession.return_value
        _urls, params = _wire(session, [_envelope([], None)])

        _rows(
            _source(
                "orders",
                should_use_incremental_field=should_use,
                db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
                incremental_field=incremental_field,
            )
        )

        assert "modified_since" not in params[0]
        # `ordering` is always requested for orders regardless of the incremental filter.
        assert params[0]["ordering"] == "last_modified"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_state_saved_only_after_page_is_yielded(self, MockSession, _host) -> None:
        session = MockSession.return_value
        page2 = "https://pretix.eu/api/v1/organizers/acme/orders/?page=2"
        _wire(session, [_envelope([{"code": "A1"}], page2), _envelope([{"code": "A2"}], None)])
        manager = _make_manager()

        rows = iter(_pages(_source("orders", manager)))

        assert next(rows) == [{"code": "A1"}]
        # A crash here must re-fetch page 1 (nothing persisted yet), not skip it.
        manager.save_state.assert_not_called()

        assert next(rows) == [{"code": "A2"}]
        # After page 1 is yielded the checkpoint points at page 2 (the verbatim next link).
        manager.save_state.assert_called_once_with(PretixResumeConfig(next_url=page2))

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_next_url(self, MockSession, _host) -> None:
        session = MockSession.return_value
        saved_url = "https://pretix.eu/api/v1/organizers/acme/orders/?page=5"
        urls, _params = _wire(session, [_envelope([{"code": "A9"}], None)])

        _rows(_source("orders", _make_manager(PretixResumeConfig(next_url=saved_url))))

        assert urls[0] == saved_url

    @mock.patch(SLEEP_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_retries_then_succeeds_on_429(self, MockSession, _sleep, _host) -> None:
        session = MockSession.return_value
        _wire(session, [_status_response(429, {"Retry-After": "1"}), _envelope([{"code": "A1"}], None)])

        rows = _rows(_source("orders"))

        assert [r["code"] for r in rows] == ["A1"]
        assert session.send.call_count == 2

    @mock.patch(SLEEP_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_unexpected_payload_shape_is_retried(self, MockSession, _sleep, _host) -> None:
        session = MockSession.return_value
        # A 200 whose body isn't the `{results: [...]}` envelope is treated as transient and reissued,
        # not failed loud or ingested as a garbage row.
        _wire(session, [_json_response([{"code": "A1"}]), _envelope([{"code": "A2"}], None)])

        rows = _rows(_source("orders"))

        assert [r["code"] for r in rows] == ["A2"]
        assert session.send.call_count == 2

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_redirect_is_rejected(self, MockSession, _host) -> None:
        session = MockSession.return_value
        _wire(session, [_status_response(302, {"Location": "https://pretix.eu/login"})])

        # A 3xx is not followed (allow_redirects=False) — it must not be silently parsed as data.
        with pytest.raises(ValueError, match="[Rr]edirect"):
            _rows(_source("orders"))


@mock.patch.object(px, "_is_host_safe", return_value=(True, None))
class TestHostPinning:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_off_host_next_url_is_not_fetched(self, MockSession, _host) -> None:
        session = MockSession.return_value
        # A malicious server handing out an off-host `next` link must never be fetched — the
        # Authorization header would otherwise be sent to an attacker-controlled origin.
        _wire(session, [_envelope([{"code": "A1"}], "https://evil.example.com/steal?page=2")])

        with pytest.raises(ValueError, match="disallowed host"):
            _rows(_source("orders"))

        # Only the first (on-host) page was ever sent.
        assert session.send.call_count == 1

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_off_host_resume_url_is_rejected_before_any_request(self, MockSession, _host) -> None:
        session = MockSession.return_value
        _wire(session, [])
        manager = _make_manager(PretixResumeConfig(next_url="https://evil.example.com/steal?page=5"))

        with pytest.raises(ValueError, match="disallowed host"):
            _rows(_source("orders", manager))

        session.send.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_unsafe_host_raises_before_building_the_source(self, MockSession, mock_host) -> None:
        mock_host.return_value = (False, HOST_NOT_ALLOWED_ERROR)

        with pytest.raises(PretixHostNotAllowedError):
            _source("orders", base_url="https://internal.example.com")

        MockSession.return_value.send.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_http_base_url_raises_before_building_the_source(self, MockSession, _host) -> None:
        with pytest.raises(PretixHostNotAllowedError):
            pretix_source(
                api_token="tok",
                organizer="acme",
                base_url="http://tickets.example.com",
                endpoint="orders",
                team_id=1,
                job_id="j",
                resumable_source_manager=_make_manager(),
            )

        MockSession.return_value.send.assert_not_called()


@mock.patch.object(px, "_is_host_safe", return_value=(True, None))
class TestEventFanOut:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_fans_out_per_event_and_stamps_event_slug(self, MockSession, _host) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [
                _envelope([{"slug": "conf-a"}, {"slug": "conf-b"}], None),  # events discovery
                _envelope([{"id": 1}], None),  # conf-a items
                _envelope([{"id": 1}, {"id": 2}], None),  # conf-b items
            ],
        )
        manager = _make_manager()

        rows = _rows(_source("items", manager))

        # The composite primary key (event_slug, id) stays unique even though both events reuse id=1.
        assert [(r["event_slug"], r["id"]) for r in rows] == [("conf-a", 1), ("conf-b", 1), ("conf-b", 2)]
        # The single-hop fan-out is resumable — a per-event checkpoint is persisted.
        assert manager.save_state.called
        assert manager.save_state.call_args.args[0].fanout_state is not None

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_event_slug_is_url_quoted_in_child_path(self, MockSession, _host) -> None:
        session = MockSession.return_value
        urls, _params = _wire(
            session,
            [_envelope([{"slug": "a/b"}], None), _envelope([], None)],
        )

        rows = _rows(_source("items", _make_manager()))

        # The slug is percent-encoded in the child URL so it can't inject an extra path segment...
        assert any("/events/a%2Fb/items/" in url for url in urls)
        # ...while the raw slug is stamped into rows unchanged (there are no rows here, so just the URL).
        assert rows == []

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_ordering_param_sent_for_sortable_child_endpoint(self, MockSession, _host) -> None:
        session = MockSession.return_value
        _urls, params = _wire(
            session,
            [_envelope([{"slug": "conf-a"}], None), _envelope([{"id": 1}], None)],
        )

        _rows(_source("items", _make_manager()))

        # `items` requests an explicit stable `ordering=id`; the child (leaf) request carries it.
        assert params[-1].get("ordering") == "id"


@mock.patch.object(px, "_is_host_safe", return_value=(True, None))
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
    @mock.patch.object(px, "make_tracked_session")
    def test_status_mapping(
        self, status_code: int, expected_valid: bool, message_fragment: str | None, session_factory, _host
    ) -> None:
        session = mock.MagicMock()
        session.get.return_value = mock.MagicMock(status_code=status_code)
        session_factory.return_value = session

        is_valid, message = validate_credentials("tok", "acme", None, team_id=1)

        assert is_valid is expected_valid
        if message_fragment is None:
            assert message is None
        else:
            assert message is not None and message_fragment in message

    @mock.patch.object(px, "make_tracked_session")
    def test_connection_error_returns_message(self, session_factory, _host) -> None:
        session = mock.MagicMock()
        session.get.side_effect = Exception("network down")
        session_factory.return_value = session

        is_valid, message = validate_credentials("tok", "acme", None, team_id=1)

        assert is_valid is False
        assert message is not None and "Could not connect to pretix" in message

    @mock.patch.object(px, "make_tracked_session")
    def test_invalid_organizer_rejected_without_request(self, session_factory, _host) -> None:
        is_valid, message = validate_credentials("tok", "  ", None, team_id=1)

        assert is_valid is False
        assert message == INVALID_ORGANIZER_ERROR
        session_factory.assert_not_called()

    @mock.patch.object(px, "make_tracked_session")
    def test_http_base_url_rejected_without_request(self, session_factory, _host) -> None:
        is_valid, message = validate_credentials("tok", "acme", "http://tickets.example.com", team_id=1)

        assert is_valid is False
        assert message is not None and "HTTPS" in message
        session_factory.assert_not_called()


class TestPretixSourceResponse:
    # No host patch needed — `is_cloud()` is False in tests, so `_check_host` short-circuits to safe.
    def test_orders_partitioned_on_stable_creation_datetime(self) -> None:
        response = _source("orders")

        assert response.name == "orders"
        assert response.primary_keys == ["event", "code"]
        assert response.partition_mode == "datetime"
        assert response.partition_format == "month"
        assert response.partition_keys == ["datetime"]
        assert response.sort_mode == "asc"

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
        response = _source(endpoint)

        assert response.primary_keys == primary_keys
        assert response.partition_mode is None
