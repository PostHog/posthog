import json
from datetime import UTC, date, datetime
from typing import Any, cast

import pytest
from unittest import mock

from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.aha.aha import (
    AhaResumeConfig,
    _build_initial_params,
    _format_updated_since,
    _incremental_window,
    aha_source,
    normalize_subdomain,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aha.settings import AHA_ENDPOINTS, PER_PAGE

FANOUT_REST_RESOURCES_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout.rest_api_resources"
)

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
    def test_missing_metadata_full_page_continues(self, MockSession) -> None:
        # No pagination metadata + a full page -> there may be more pages.
        session = MockSession.return_value
        full_page = [{"id": str(i)} for i in range(PER_PAGE)]
        _wire(session, [_response("features", full_page), _response("features", [{"id": "last"}])])

        rows = _rows(_source("features", _make_manager()))

        assert len(rows) == PER_PAGE + 1
        assert session.send.call_count == 2


class TestIncrementalWindow:
    def test_binds_cursor_field_to_updated_since(self) -> None:
        window = _incremental_window("updated_at")
        assert window["cursor_path"] == "updated_at"
        assert window["start_param"] == "updated_since"
        convert = window["convert"]
        assert convert is not None
        # The convert hook must emit the trailing-Z UTC form Aha! accepts, not an isoformat offset.
        assert convert(datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC)) == "2026-03-04T02:58:14Z"


class _FakeDltResource:
    """Stand-in for a DltResource returned by ``rest_api_resources``."""

    def __init__(self, name: str, rows: list[dict[str, Any]]) -> None:
        self.name = name
        self._rows = rows

    def add_map(self, mapper: Any) -> "_FakeDltResource":
        self._rows = [mapper(dict(row)) for row in self._rows]
        return self

    def __iter__(self) -> Any:
        return iter(self._rows)


class TestAhaFanout:
    @mock.patch(FANOUT_REST_RESOURCES_PATCH)
    def test_releases_injects_product_id_from_parent(self, mock_rest_api_resources) -> None:
        mock_rest_api_resources.return_value = [
            _FakeDltResource("products", [{"id": "1000"}]),
            _FakeDltResource("releases", [{"id": "R1", "_products_id": "1000"}]),
        ]

        resp = _source("releases", _make_manager())

        rows = list(cast(Any, resp.items()))
        assert rows == [{"id": "R1", "product_id": "1000"}]


class TestValidateCredentials:
    @mock.patch(AHA_SESSION_PATCH)
    def test_ok(self, mock_session) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=200)
        assert validate_credentials("acme", "key") == (True, 200)

    @mock.patch(AHA_SESSION_PATCH)
    def test_bad_subdomain_raises_before_probe(self, mock_session) -> None:
        with pytest.raises(ValueError, match="Invalid Aha! account domain"):
            validate_credentials("acme/../evil", "key")
        mock_session.assert_not_called()
