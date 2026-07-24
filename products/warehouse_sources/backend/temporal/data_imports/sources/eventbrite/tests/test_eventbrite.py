import json
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest import mock

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.eventbrite.eventbrite import (
    EventbriteResumeConfig,
    _format_changed_since,
    eventbrite_source,
    validate_credentials,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the eventbrite module.
EB_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.eventbrite.eventbrite.make_tracked_session"
)


def _response(
    data_key: str, items: list[dict[str, Any]], *, has_more: bool = False, continuation: str | None = None
) -> Response:
    body: dict[str, Any] = {
        data_key: items,
        "pagination": {"has_more_items": has_more, "continuation": continuation},
    }
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(body).encode()
    return resp


def _make_manager(resume_state: EventbriteResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(
    session: mock.MagicMock, responses: list[Response] | Callable[[str], Response]
) -> list[tuple[str, dict[str, Any]]]:
    """Wire a mock session; return per-request (url, params) snapshots captured AT SEND TIME.

    ``responses`` is either a flat list (consumed in request order) or a router callable keyed on the
    resolved request URL — the latter is needed for fan-out, whose request order interleaves parents
    and children. ``request.params`` is one dict mutated in place across pages, so snapshot a copy.
    """
    session.headers = {}
    snapshots: list[tuple[str, dict[str, Any]]] = []
    iterator = iter(responses) if isinstance(responses, list) else None

    def _prepare(request: Any) -> mock.MagicMock:
        prepared = mock.MagicMock()
        prepared.url = request.url
        snapshots.append((request.url, dict(request.params or {})))
        return prepared

    def _send(prepared: Any, **_kwargs: Any) -> Response:
        if iterator is not None:
            return next(iterator)
        assert callable(responses)
        return responses(prepared.url)

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = _send
    return snapshots


def _rows(source_response: Any) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _run(endpoint: str, manager: mock.MagicMock, **kwargs: Any) -> Any:
    return eventbrite_source("token", endpoint, team_id=1, job_id="j", resumable_source_manager=manager, **kwargs)


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


class TestTopLevelPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_follows_continuation_until_has_more_false(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        snaps = _wire(
            session,
            [
                _response("organizations", [{"id": "1"}, {"id": "2"}], has_more=True, continuation="tok2"),
                _response("organizations", [{"id": "3"}], has_more=False, continuation=None),
            ],
        )

        manager = _make_manager()
        rows = _rows(_run("organizations", manager))

        assert [r["id"] for r in rows] == ["1", "2", "3"]
        assert "continuation" not in snaps[0][1]
        assert snaps[1][1]["continuation"] == "tok2"
        assert session.send.call_count == 2
        # Checkpoint saved after the first page (points at the next page's token); the last page ends it.
        manager.save_state.assert_called_once_with(EventbriteResumeConfig(continuation="tok2"))

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_stops_on_has_more_false_even_with_continuation_token(self, MockSession: mock.MagicMock) -> None:
        # Eventbrite can still return a continuation token on the final page; gate strictly on
        # has_more_items so a stale token does not trigger an extra (infinite) request.
        session = MockSession.return_value
        _wire(session, [_response("categories", [{"id": "1"}], has_more=False, continuation="stale-tok")])

        rows = _rows(_run("categories", _make_manager()))

        assert [r["id"] for r in rows] == ["1"]
        assert session.send.call_count == 1

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resume_seeds_continuation(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        snaps = _wire(session, [_response("organizations", [{"id": "9"}], has_more=False, continuation=None)])

        manager = _make_manager(EventbriteResumeConfig(continuation="resume-tok"))
        _rows(_run("organizations", manager))

        assert snaps[0][1]["continuation"] == "resume-tok"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_page_yields_no_rows(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        _wire(session, [_response("formats", [], has_more=False, continuation=None)])

        rows = _rows(_run("formats", _make_manager()))

        assert rows == []
        assert session.send.call_count == 1


class TestFanOut:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_org_fan_out_builds_child_urls_per_org(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value

        def router(url: str) -> Response:
            if url.endswith("/users/me/organizations/"):
                return _response("organizations", [{"id": "org1"}, {"id": "org2"}])
            if url.endswith("/organizations/org1/events/"):
                return _response("events", [{"id": "e1"}])
            if url.endswith("/organizations/org2/events/"):
                return _response("events", [{"id": "e2"}])
            raise AssertionError(f"unexpected url {url}")

        _wire(session, router)

        rows = _rows(_run("events", _make_manager()))

        # Child rows are yielded with their raw shape (no parent ids injected).
        assert rows == [{"id": "e1"}, {"id": "e2"}]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_event_fan_out_is_two_levels(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value

        def router(url: str) -> Response:
            if url.endswith("/users/me/organizations/"):
                return _response("organizations", [{"id": "org1"}])
            if url.endswith("/organizations/org1/events/"):
                return _response("events", [{"id": "e1"}, {"id": "e2"}])
            if url.endswith("/events/e1/attendees/"):
                return _response("attendees", [{"id": "a1"}])
            if url.endswith("/events/e2/attendees/"):
                return _response("attendees", [{"id": "a2"}])
            raise AssertionError(f"unexpected url {url}")

        _wire(session, router)

        rows = _rows(_run("attendees", _make_manager()))

        assert [r["id"] for r in rows] == ["a1", "a2"]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_child_endpoint_paginates_with_continuation(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        events_pages = iter(
            [
                _response("events", [{"id": "e1"}], has_more=True, continuation="p2"),
                _response("events", [{"id": "e2"}], has_more=False, continuation=None),
            ]
        )

        def router(url: str) -> Response:
            if url.endswith("/users/me/organizations/"):
                return _response("organizations", [{"id": "org1"}])
            if url.endswith("/organizations/org1/events/"):
                return next(events_pages)
            raise AssertionError(f"unexpected url {url}")

        _wire(session, router)

        rows = _rows(_run("events", _make_manager()))

        assert [r["id"] for r in rows] == ["e1", "e2"]


class TestIncrementalFilter:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_changed_since_applied_only_to_child_endpoint(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value

        def router(url: str) -> Response:
            if url.endswith("/users/me/organizations/"):
                return _response("organizations", [{"id": "org1"}])
            if url.endswith("/organizations/org1/orders/"):
                return _response("orders", [{"id": "ord1"}])
            raise AssertionError(f"unexpected url {url}")

        snaps = _wire(session, router)

        _rows(
            _run(
                "orders",
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value="2026-01-01T00:00:00Z",
                incremental_field="changed",
            )
        )

        org_params = next(p for u, p in snaps if u.endswith("/users/me/organizations/"))
        order_params = next(p for u, p in snaps if u.endswith("/organizations/org1/orders/"))
        assert "changed_since" not in org_params
        assert order_params["changed_since"] == "2026-01-01T00:00:00Z"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_changed_since_omitted_when_not_incremental(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value

        def router(url: str) -> Response:
            if url.endswith("/users/me/organizations/"):
                return _response("organizations", [{"id": "org1"}])
            if url.endswith("/organizations/org1/orders/"):
                return _response("orders", [{"id": "ord1"}])
            raise AssertionError(f"unexpected url {url}")

        snaps = _wire(session, router)

        _rows(
            _run(
                "orders",
                _make_manager(),
                should_use_incremental_field=False,
                db_incremental_field_last_value="2026-01-01T00:00:00Z",
                incremental_field="changed",
            )
        )

        order_params = next(p for u, p in snaps if u.endswith("/organizations/org1/orders/"))
        assert "changed_since" not in order_params

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_changed_since_omitted_for_unrelated_incremental_field(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value

        def router(url: str) -> Response:
            if url.endswith("/users/me/organizations/"):
                return _response("organizations", [{"id": "org1"}])
            if url.endswith("/organizations/org1/orders/"):
                return _response("orders", [{"id": "ord1"}])
            raise AssertionError(f"unexpected url {url}")

        snaps = _wire(session, router)

        _rows(
            _run(
                "orders",
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value="2026-01-01T00:00:00Z",
                incremental_field="some_other_field",
            )
        )

        order_params = next(p for u, p in snaps if u.endswith("/organizations/org1/orders/"))
        assert "changed_since" not in order_params


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected",
        [(200, True), (401, False), (403, False), (500, False)],
    )
    @mock.patch(EB_SESSION_PATCH)
    def test_validate_credentials_status_mapping(
        self, mock_session_factory: mock.MagicMock, status_code: int, expected: bool
    ) -> None:
        session = mock.MagicMock()
        session.get.return_value.status_code = status_code
        mock_session_factory.return_value = session

        assert validate_credentials("token") is expected

    @mock.patch(EB_SESSION_PATCH)
    def test_validate_credentials_swallows_exceptions(self, mock_session_factory: mock.MagicMock) -> None:
        session = mock.MagicMock()
        session.get.side_effect = Exception("network down")
        mock_session_factory.return_value = session

        assert validate_credentials("token") is False


class TestEventbriteSourceResponse:
    @pytest.mark.parametrize("endpoint", ["organizations", "events", "orders", "attendees"])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_partitioned_endpoints(self, MockSession: mock.MagicMock, endpoint: str) -> None:
        MockSession.return_value.headers = {}
        response = _run(endpoint, _make_manager())

        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        assert response.partition_mode == "datetime"
        assert response.partition_format == "week"
        assert response.partition_keys == ["created"]

    @pytest.mark.parametrize("endpoint", ["categories", "formats", "venues", "ticket_classes"])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_non_partitioned_endpoints(self, MockSession: mock.MagicMock, endpoint: str) -> None:
        MockSession.return_value.headers = {}
        response = _run(endpoint, _make_manager())

        assert response.partition_mode is None
        assert response.partition_keys is None
