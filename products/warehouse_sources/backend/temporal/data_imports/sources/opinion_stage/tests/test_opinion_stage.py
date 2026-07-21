import json
from typing import Any

import pytest
from unittest import mock

import requests
from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.opinion_stage.opinion_stage import (
    OPINION_STAGE_BASE_URL,
    PAGE_SIZE,
    OpinionStageResumeConfig,
    opinion_stage_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.opinion_stage.settings import ENDPOINTS

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the opinion_stage module.
OPINION_STAGE_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.opinion_stage.opinion_stage.make_tracked_session"
)
# Backoff sleeps happen inside tenacity; patch its clock so retry tests don't actually wait.
SLEEP_PATCH = "tenacity.nap.time.sleep"


def _page(
    items: list[dict[str, Any]] | None, next_link: str | None, *, status: int = 200, reason: str = "OK"
) -> Response:
    # JSON:API collection envelope: rows under `data`, pagination via `links.next`.
    body: dict[str, Any] = {
        "data": items if items is not None else [],
        "meta": {},
        "links": {"self": "s", "next": next_link},
    }
    return _raw(body, status=status, reason=reason)


def _raw(body: Any, *, status: int = 200, reason: str = "OK") -> Response:
    resp = Response()
    resp.status_code = status
    resp.reason = reason
    resp.url = f"{OPINION_STAGE_BASE_URL}/api/v2/items"
    resp.headers["Content-Type"] = "application/vnd.api+json"
    resp._content = b"" if body is None else json.dumps(body).encode()
    return resp


def _wire(session: mock.MagicMock, responses: list[Response]) -> tuple[list[dict[str, Any]], list[Any]]:
    """Wire a mock session, snapshotting each request's params and auth AT PREPARE TIME.

    ``request.params`` is a single dict mutated in place across pages, so a copy is taken per page.
    """
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []
    auth_snapshots: list[Any] = []

    def _prepare(request: Any) -> mock.MagicMock:
        param_snapshots.append(dict(request.params or {}))
        auth_snapshots.append(request.auth)
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return param_snapshots, auth_snapshots


def _make_manager(resume_state: OpinionStageResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _rows(source_response: Any) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


class TestOpinionStage:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_single_page_yields_items_and_stops(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        _wire(session, [_page([{"id": "1"}, {"id": "2"}], next_link=None)])

        manager = _make_manager()
        rows = _rows(opinion_stage_source("os-key", "items", team_id=1, job_id="j", resumable_source_manager=manager))

        assert rows == [{"id": "1"}, {"id": "2"}]
        assert session.send.call_count == 1
        # No next link, so no resume state is persisted.
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_follows_pagination_until_next_link_is_null(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        params, _auths = _wire(
            session,
            [
                _page([{"id": "1"}], next_link="p2"),
                _page([{"id": "2"}], next_link="p3"),
                _page([{"id": "3"}], next_link=None),
            ],
        )

        manager = _make_manager()
        rows = _rows(opinion_stage_source("os-key", "items", team_id=1, job_id="j", resumable_source_manager=manager))

        assert [r["id"] for r in rows] == ["1", "2", "3"]
        assert session.send.call_count == 3
        # Page number increments (1-indexed) with a constant page size on every request.
        assert [p["page[number]"] for p in params] == [1, 2, 3]
        assert all(p["page[size]"] == PAGE_SIZE for p in params)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_saves_next_page_after_yielding_each_batch(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        _wire(session, [_page([{"id": "1"}], next_link="p2"), _page([{"id": "2"}], next_link=None)])

        manager = _make_manager()
        _rows(opinion_stage_source("os-key", "items", team_id=1, job_id="j", resumable_source_manager=manager))

        # State is saved AFTER page 1 is yielded (pointing at page 2), and never for the final page.
        assert [c.args[0].next_page for c in manager.save_state.call_args_list] == [2]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_page(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        params, _auths = _wire(session, [_page([{"id": "2"}], next_link="p3"), _page([{"id": "3"}], next_link=None)])

        manager = _make_manager(OpinionStageResumeConfig(next_page=2))
        rows = _rows(opinion_stage_source("os-key", "items", team_id=1, job_id="j", resumable_source_manager=manager))

        assert [r["id"] for r in rows] == ["2", "3"]
        # Page 1 is never fetched on resume — the first request targets page 2.
        assert params[0]["page[number]"] == 2

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_data_yields_no_rows(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        _wire(session, [_page([], next_link=None)])

        manager = _make_manager()
        rows = _rows(opinion_stage_source("os-key", "items", team_id=1, job_id="j", resumable_source_manager=manager))

        assert rows == []
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_stops_when_page_is_empty_even_with_next_link(self, MockSession: mock.MagicMock) -> None:
        # A defensive guard: an empty page terminates the sync even if the API keeps advertising a
        # next link, so we never loop forever on a stale cursor.
        session = MockSession.return_value
        _wire(session, [_page([], next_link="p2")])

        manager = _make_manager()
        rows = _rows(opinion_stage_source("os-key", "items", team_id=1, job_id="j", resumable_source_manager=manager))

        assert rows == []
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_basic_auth_uses_api_key_as_username_with_blank_password(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        _params, auths = _wire(session, [_page([{"id": "1"}], next_link=None)])

        _rows(
            opinion_stage_source("secret-key", "items", team_id=1, job_id="j", resumable_source_manager=_make_manager())
        )

        # HTTP Basic on the framework auth: the API key is the username, the password is blank.
        assert auths[0].username == "secret-key"
        assert auths[0].password == ""

    @mock.patch(SLEEP_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_missing_data_key_is_retried_then_reraises(
        self, MockSession: mock.MagicMock, _sleep: mock.MagicMock
    ) -> None:
        # A 200 body without a top-level `data` list is malformed for JSON:API; treat it as transient
        # and reissue rather than silently yielding nothing.
        session = MockSession.return_value
        _wire(session, [_raw({"errors": [{"detail": "nope"}]})] * 5)

        with pytest.raises(RESTClientRetryableError):
            _rows(
                opinion_stage_source("os-key", "items", team_id=1, job_id="j", resumable_source_manager=_make_manager())
            )
        assert session.send.call_count == 5

    @mock.patch(SLEEP_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_non_list_data_is_retried_then_reraises(self, MockSession: mock.MagicMock, _sleep: mock.MagicMock) -> None:
        session = MockSession.return_value
        _wire(session, [_raw({"data": {"unexpected": "object"}})] * 5)

        with pytest.raises(RESTClientRetryableError):
            _rows(
                opinion_stage_source("os-key", "items", team_id=1, job_id="j", resumable_source_manager=_make_manager())
            )
        assert session.send.call_count == 5

    @mock.patch(SLEEP_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_malformed_body_then_valid_recovers(self, MockSession: mock.MagicMock, _sleep: mock.MagicMock) -> None:
        session = MockSession.return_value
        _wire(session, [_raw({"errors": ["glitch"]}), _page([{"id": "1"}], next_link=None)])

        rows = _rows(
            opinion_stage_source("os-key", "items", team_id=1, job_id="j", resumable_source_manager=_make_manager())
        )

        assert [r["id"] for r in rows] == ["1"]
        assert session.send.call_count == 2

    @parameterized.expand(
        [
            ("rate_limited", 429, "Too Many Requests"),
            ("server_error", 500, "Internal Server Error"),
            ("bad_gateway", 503, "Service Unavailable"),
        ]
    )
    @mock.patch(SLEEP_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_retryable_status_retries_then_raises(
        self, _name: str, status: int, reason: str, MockSession: mock.MagicMock, _sleep: mock.MagicMock
    ) -> None:
        session = MockSession.return_value
        _wire(session, [_raw({}, status=status, reason=reason)] * 5)

        with pytest.raises(RESTClientRetryableError):
            _rows(
                opinion_stage_source("os-key", "items", team_id=1, job_id="j", resumable_source_manager=_make_manager())
            )
        assert session.send.call_count == 5

    @parameterized.expand(
        [("unauthorized", 401, "Unauthorized"), ("forbidden", 403, "Forbidden"), ("not_found", 404, "Not Found")]
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_client_error_raises_http_error_without_retry(
        self, _name: str, status: int, reason: str, MockSession: mock.MagicMock
    ) -> None:
        # 4xx are credential/permission/shape failures — never retried, surfaced as an HTTPError whose
        # message carries the stable status text that get_non_retryable_errors matches on.
        session = MockSession.return_value
        _wire(session, [_raw({"errors": ["denied"]}, status=status, reason=reason)])

        with pytest.raises(requests.HTTPError) as exc_info:
            _rows(
                opinion_stage_source("os-key", "items", team_id=1, job_id="j", resumable_source_manager=_make_manager())
            )
        assert f"{status} Client Error" in str(exc_info.value)
        assert "https://api.opinionstage.com" in str(exc_info.value)
        assert session.send.call_count == 1

    @parameterized.expand([(e,) for e in ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        # No network: SourceResponse metadata is built eagerly, rows only on iteration.
        response = opinion_stage_source(
            "os-key", endpoint, team_id=1, job_id="j", resumable_source_manager=_make_manager()
        )
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        # JSON:API items carry no guaranteed stable creation timestamp column, so we don't partition.
        assert response.partition_mode is None


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("valid", 200, True, 200),
            ("unauthorized", 401, False, 401),
            ("forbidden", 403, False, 403),
            ("server_error", 500, False, 500),
        ]
    )
    def test_status_mapping(self, _name: str, status: int, expected_ok: bool, expected_status: int | None) -> None:
        session = mock.MagicMock()
        session.get.return_value = mock.MagicMock(status_code=status)
        with mock.patch(OPINION_STAGE_SESSION_PATCH, return_value=session):
            ok, returned_status = validate_credentials("os-key")
        assert ok is expected_ok
        assert returned_status == expected_status

    def test_transport_error_maps_to_none(self) -> None:
        session = mock.MagicMock()
        session.get.side_effect = requests.ConnectionError("boom")
        with mock.patch(OPINION_STAGE_SESSION_PATCH, return_value=session):
            ok, status = validate_credentials("os-key")
        assert ok is False
        assert status is None
