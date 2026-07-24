import json
from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest import mock

from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.uservoice.settings import PER_PAGE
from products.warehouse_sources.backend.temporal.data_imports.sources.uservoice.uservoice import (
    UservoiceResumeConfig,
    _format_updated_after,
    normalize_subdomain,
    uservoice_source,
    validate_credentials,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the uservoice module.
USERVOICE_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.uservoice.uservoice.make_tracked_session"
)


def _response(response_key: str, items: list[dict[str, Any]], pagination: dict[str, Any]) -> Response:
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps({response_key: items, "pagination": pagination}).encode()
    return resp


def _make_manager(resume_state: UservoiceResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and capture each request's params AT SEND TIME.

    ``request.params`` is one dict mutated in place across pages, so snapshot a copy per prepare.
    """
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        param_snapshots.append(dict(request.params or {}))
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return param_snapshots


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _source(manager: mock.MagicMock, endpoint: str = "suggestions", **kwargs: Any):
    return uservoice_source(
        subdomain="acme",
        api_key="token",
        endpoint=endpoint,
        team_id=1,
        job_id="j",
        resumable_source_manager=manager,
        **kwargs,
    )


class TestNormalizeSubdomain:
    @parameterized.expand(
        [
            ("bare", "acme", "acme"),
            ("full_host", "acme.uservoice.com", "acme"),
            ("https_url", "https://acme.uservoice.com", "acme"),
            ("trailing_slash", "acme.uservoice.com/", "acme"),
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


class TestFormatUpdatedAfter:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14Z"),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14Z"),
            ("date_value", date(2026, 3, 4), "2026-03-04T00:00:00Z"),
            ("string_passthrough", "2026-03-04T02:58:14Z", "2026-03-04T02:58:14Z"),
        ]
    )
    def test_format(self, _name: str, value: Any, expected: str) -> None:
        result = _format_updated_after(value)
        assert result == expected
        assert "+00:00" not in result


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_by_page_number(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(
            session,
            [
                _response("suggestions", [{"id": 1}, {"id": 2}], {"page": 1, "total_pages": 2}),
                _response("suggestions", [{"id": 3}], {"page": 2, "total_pages": 2}),
            ],
        )

        manager = _make_manager()
        rows = _rows(_source(manager))

        assert [r["id"] for r in rows] == [1, 2, 3]
        assert params[0]["per_page"] == PER_PAGE
        assert "page" not in params[0]
        assert params[1]["page"] == 2
        # Checkpoint saved once after the first page (points at page 2); the last page ends it.
        manager.save_state.assert_called_once_with(UservoiceResumeConfig(cursor=None, page=2))

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_by_cursor(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(
            session,
            [
                _response("suggestions", [{"id": 1}], {"cursor": "CUR2"}),
                _response("suggestions", [{"id": 2}], {}),
            ],
        )

        manager = _make_manager()
        rows = _rows(_source(manager))

        assert [r["id"] for r in rows] == [1, 2]
        assert "cursor" not in params[0]
        assert params[1]["cursor"] == "CUR2"
        manager.save_state.assert_called_once_with(UservoiceResumeConfig(cursor="CUR2", page=None))

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_stops_on_non_advancing_cursor(self, MockSession) -> None:
        # A cursor that repeats itself must not loop forever, but both yielded pages are kept.
        session = MockSession.return_value
        _wire(
            session,
            [
                _response("suggestions", [{"id": 1}], {"cursor": "SAME"}),
                _response("suggestions", [{"id": 2}], {"cursor": "SAME"}),
            ],
        )

        rows = _rows(_source(_make_manager()))
        assert [r["id"] for r in rows] == [1, 2]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_missing_meta_full_page_keeps_going(self, MockSession) -> None:
        session = MockSession.return_value
        full_page = [{"id": i} for i in range(PER_PAGE)]
        params = _wire(
            session,
            [
                _response("suggestions", full_page, {}),
                _response("suggestions", [{"id": 999}], {}),
            ],
        )

        rows = _rows(_source(_make_manager()))
        assert len(rows) == PER_PAGE + 1
        assert params[1]["page"] == 2

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_page(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response("suggestions", [{"id": 2}], {"page": 2, "total_pages": 2})])

        rows = _rows(_source(_make_manager(UservoiceResumeConfig(page=2))))
        assert [r["id"] for r in rows] == [2]
        assert params[0]["page"] == 2

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_cursor(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response("suggestions", [{"id": 9}], {})])

        rows = _rows(_source(_make_manager(UservoiceResumeConfig(cursor="CUR9"))))
        assert [r["id"] for r in rows] == [9]
        assert params[0]["cursor"] == "CUR9"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_filter_added_to_request(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response("suggestions", [{"id": 1}], {"page": 1, "total_pages": 1})])

        _rows(
            _source(
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
            )
        )
        assert params[0]["updated_after"] == "2026-03-04T02:58:14Z"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_full_refresh_endpoint_never_filters(self, MockSession) -> None:
        # labels has no server-side `updated_after`; a cursor value must not leak into the request.
        session = MockSession.return_value
        params = _wire(session, [_response("labels", [{"id": 1}], {"page": 1, "total_pages": 1})])

        _rows(
            _source(
                _make_manager(),
                endpoint="labels",
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
            )
        )
        assert "updated_after" not in params[0]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_stops_on_empty_response(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response("labels", [], {"page": 1, "total_pages": 1})])

        manager = _make_manager()
        rows = _rows(_source(manager, endpoint="labels"))
        assert rows == []
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_bearer_token_not_placed_in_plain_header(self, MockSession) -> None:
        # The token rides the framework Bearer auth (redacted from logs), so only the non-secret
        # Accept header is set directly on the session.
        session = MockSession.return_value
        _wire(session, [_response("suggestions", [{"id": 1}], {"page": 1, "total_pages": 1})])

        _rows(_source(_make_manager()))
        assert session.headers.get("Accept") == "application/json"
        assert "Authorization" not in session.headers


class TestSourceResponse:
    @parameterized.expand(
        [
            # Incremental endpoints defer the watermark write to job end via "desc" (order is unverified).
            ("suggestions", "desc", "created_at"),
            ("tickets", "desc", "created_at"),
            # Full-refresh endpoints don't checkpoint a watermark, so they stay on the default "asc".
            ("labels", "asc", "created_at"),
        ]
    )
    def test_sort_mode_and_partitioning(self, endpoint: str, expected_sort: str, partition_key: str) -> None:
        response = _source(_make_manager(), endpoint=endpoint)
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        assert response.sort_mode == expected_sort
        assert response.partition_mode == "datetime"
        assert response.partition_keys == [partition_key]


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True, 200),
            ("unauthorized", 401, False, 401),
            ("forbidden", 403, False, 403),
        ]
    )
    @mock.patch(USERVOICE_SESSION_PATCH)
    def test_maps_status(self, _name, status, expected_ok, expected_status, mock_session) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status)
        ok, code = validate_credentials("acme", "token")
        assert ok is expected_ok
        assert code == expected_status

    @mock.patch(USERVOICE_SESSION_PATCH)
    def test_transport_error_maps_to_none(self, mock_session) -> None:
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("acme", "token") == (False, None)

    def test_bad_subdomain_raises(self) -> None:
        # A malformed subdomain must surface as ValueError so the caller can show a precise message.
        with pytest.raises(ValueError):
            validate_credentials("acme/../evil", "token")
