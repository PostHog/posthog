import json
from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest import mock

from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.aha.aha import (
    AhaResumeConfig,
    _build_initial_params,
    _format_updated_since,
    aha_source,
    normalize_subdomain,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aha.settings import AHA_ENDPOINTS, PER_PAGE
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import BearerTokenAuth

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the aha module.
AHA_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.aha.aha.make_tracked_session"


class TestNormalizeSubdomain:
    @parameterized.expand(
        [
            ("bare", "acme", "acme"),
            ("full_host", "acme.aha.io", "acme"),
            ("https_url", "https://acme.aha.io", "acme"),
            ("trailing_slash", "acme.aha.io/", "acme"),
            ("with_hyphen", "acme-corp", "acme-corp"),
            ("whitespace", "  acme  ", "acme"),
        ]
    )
    def test_valid_subdomains(self, _name: str, value: str, expected: str) -> None:
        assert normalize_subdomain(value) == expected

    @parameterized.expand(
        [
            ("path_injection", "acme/../evil"),
            ("host_injection", "acme.evil.com"),
            ("userinfo_injection", "acme@evil.com"),
            ("empty", ""),
            ("space_inside", "ac me"),
            ("trailing_hyphen", "acme-"),
        ]
    )
    def test_invalid_subdomains_raise(self, _name: str, value: str) -> None:
        with pytest.raises(ValueError):
            normalize_subdomain(value)


class TestFormatUpdatedSince:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14Z"),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14Z"),
            ("date_value", date(2026, 3, 4), "2026-03-04T00:00:00Z"),
            ("string_passthrough", "2026-03-04T02:58:14Z", "2026-03-04T02:58:14Z"),
        ]
    )
    def test_format(self, _name: str, value: Any, expected: str) -> None:
        result = _format_updated_since(value)
        assert result == expected
        assert "+00:00" not in result


class TestBuildInitialParams:
    def test_incremental_endpoint_with_cursor_adds_updated_since(self) -> None:
        params = _build_initial_params(
            AHA_ENDPOINTS["features"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
        )
        assert params == {"per_page": PER_PAGE, "updated_since": "2026-03-04T02:58:14Z"}

    def test_incremental_endpoint_without_cursor_omits_updated_since(self) -> None:
        params = _build_initial_params(
            AHA_ENDPOINTS["features"], should_use_incremental_field=True, db_incremental_field_last_value=None
        )
        assert params == {"per_page": PER_PAGE}

    def test_full_refresh_endpoint_never_filters(self) -> None:
        # goals has no server-side `updated_since`; a cursor must not leak into the request.
        params = _build_initial_params(
            AHA_ENDPOINTS["goals"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
        )
        assert params == {"per_page": PER_PAGE}


def _response(
    response_key: str,
    items: list[dict[str, Any]] | None,
    *,
    current_page: int | None = None,
    total_pages: int | None = None,
    drop_key: bool = False,
) -> Response:
    body: dict[str, Any] = {}
    if not drop_key:
        body[response_key] = items or []
    if total_pages is not None:
        body["pagination"] = {"current_page": current_page or 1, "total_pages": total_pages}
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(body).encode()
    return resp


def _make_manager(resume_state: AhaResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and return a list that captures each request AT SEND TIME.

    ``request.params`` is a single dict mutated in place across pages, so inspecting it after the
    run shows only the final state — snapshot a copy when each request is prepared instead.
    """
    session.headers = {}
    snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        snapshots.append({"url": request.url, "params": dict(request.params or {}), "auth": request.auth})
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return snapshots


def _source(endpoint: str, manager: mock.MagicMock, **kwargs: Any):
    return aha_source(
        subdomain="acme",
        api_key="key",
        endpoint=endpoint,
        team_id=1,
        job_id="j",
        resumable_source_manager=manager,
        **kwargs,
    )


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


class TestAhaSource:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_until_total_pages(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(
            session,
            [
                _response("features", [{"id": "1"}, {"id": "2"}], current_page=1, total_pages=2),
                _response("features", [{"id": "3"}], current_page=2, total_pages=2),
            ],
        )

        rows = _rows(_source("features", _make_manager()))

        assert [r["id"] for r in rows] == ["1", "2", "3"]
        # total_pages=2 terminates after the last page — no extra empty-page request.
        assert session.send.call_count == 2
        assert snapshots[0]["url"] == "https://acme.aha.io/api/v1/features"
        assert snapshots[0]["params"] == {"per_page": PER_PAGE, "page": 1}
        assert snapshots[1]["params"] == {"per_page": PER_PAGE, "page": 2}

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_auth_is_framework_bearer(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_response("features", [{"id": "1"}], total_pages=1)])

        _rows(_source("features", _make_manager()))

        auth = snapshots[0]["auth"]
        assert isinstance(auth, BearerTokenAuth)
        assert auth.token == "key"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_saves_resume_state_only_while_pages_remain(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [
                _response("features", [{"id": "1"}], current_page=1, total_pages=2),
                _response("features", [{"id": "2"}], current_page=2, total_pages=2),
            ],
        )

        manager = _make_manager()
        _rows(_source("features", manager))

        # State is saved only while more pages remain (page 1 -> next_page 2), never on the last page.
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == AhaResumeConfig(next_page=2)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_page(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_response("features", [{"id": "2"}], current_page=2, total_pages=2)])

        rows = _rows(_source("features", _make_manager(AhaResumeConfig(next_page=2))))

        assert [r["id"] for r in rows] == ["2"]
        assert session.send.call_count == 1
        assert snapshots[0]["params"]["page"] == 2

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_cursor_added_to_request(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_response("features", [{"id": "1"}], total_pages=1)])

        _rows(
            _source(
                "features",
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
            )
        )

        assert snapshots[0]["params"]["updated_since"] == "2026-03-04T02:58:14Z"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_uses_response_key_for_todos(self, MockSession) -> None:
        # to-dos live at /tasks with a `tasks` root key.
        session = MockSession.return_value
        snapshots = _wire(session, [_response("tasks", [{"id": "t1"}], total_pages=1)])

        rows = _rows(_source("todos", _make_manager()))

        assert [r["id"] for r in rows] == ["t1"]
        assert snapshots[0]["url"] == "https://acme.aha.io/api/v1/tasks"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_stops_on_empty_page(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response("goals", [], total_pages=1)])

        manager = _make_manager()
        rows = _rows(_source("goals", manager))

        assert rows == []
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_missing_response_key_stops_quietly(self, MockSession) -> None:
        # A body without the root key is treated as an empty page (old `data.get(key, []) -> stop`).
        session = MockSession.return_value
        _wire(session, [_response("goals", None, drop_key=True)])

        rows = _rows(_source("goals", _make_manager()))

        assert rows == []
        assert session.send.call_count == 1

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_missing_metadata_partial_page_stops(self, MockSession) -> None:
        # No pagination metadata + a short page -> no more pages (full-page fallback heuristic).
        session = MockSession.return_value
        _wire(session, [_response("features", [{"id": "1"}, {"id": "2"}])])

        rows = _rows(_source("features", _make_manager()))

        assert [r["id"] for r in rows] == ["1", "2"]
        assert session.send.call_count == 1

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_missing_metadata_full_page_continues(self, MockSession) -> None:
        # No pagination metadata + a full page -> there may be more pages.
        session = MockSession.return_value
        full_page = [{"id": str(i)} for i in range(PER_PAGE)]
        _wire(session, [_response("features", full_page), _response("features", [{"id": "last"}])])

        rows = _rows(_source("features", _make_manager()))

        assert len(rows) == PER_PAGE + 1
        assert session.send.call_count == 2


class TestValidateCredentials:
    @mock.patch(AHA_SESSION_PATCH)
    def test_ok(self, mock_session) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=200)
        assert validate_credentials("acme", "key") == (True, 200)

    @mock.patch(AHA_SESSION_PATCH)
    def test_unauthorized(self, mock_session) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=401)
        assert validate_credentials("acme", "key") == (False, 401)

    @mock.patch(AHA_SESSION_PATCH)
    def test_swallows_transport_errors(self, mock_session) -> None:
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("acme", "key") == (False, None)

    @mock.patch(AHA_SESSION_PATCH)
    def test_probes_me_endpoint_with_bearer_header(self, mock_session) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=200)
        validate_credentials("acme", "key")

        call = mock_session.return_value.get.call_args
        assert call.args[0] == "https://acme.aha.io/api/v1/me"
        assert call.kwargs["headers"]["Authorization"] == "Bearer key"

    @mock.patch(AHA_SESSION_PATCH)
    def test_bad_subdomain_raises_before_probe(self, mock_session) -> None:
        with pytest.raises(ValueError, match="Invalid Aha! account domain"):
            validate_credentials("acme/../evil", "key")
        mock_session.assert_not_called()
