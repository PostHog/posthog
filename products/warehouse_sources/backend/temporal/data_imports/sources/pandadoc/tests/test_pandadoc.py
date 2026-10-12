import json
from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest import mock

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.pandadoc.pandadoc import (
    PAGE_SIZE,
    PandaDocResumeConfig,
    _build_query_params,
    _format_date_filter,
    pandadoc_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.pandadoc.settings import PANDADOC_ENDPOINTS

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the pandadoc module.
PANDADOC_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.pandadoc.pandadoc.make_tracked_session"
)


def _response(items: list[dict[str, Any]] | None, *, drop_results: bool = False) -> Response:
    body: dict[str, Any] = {}
    if not drop_results:
        body["results"] = items or []
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(body).encode()
    return resp


def _make_manager(resume_state: PandaDocResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> tuple[list[dict[str, Any]], list[Any]]:
    """Wire a mock session; capture each request's params AND auth AT SEND TIME.

    ``request.params`` is a single dict mutated in place across pages, so inspecting it after the
    run shows only the final state — snapshot a copy when each request is prepared instead.
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


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


class TestFormatDateFilter:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC), "2024-01-02T03:04:05.000000Z"),
            (datetime(2024, 1, 2, 3, 4, 5), "2024-01-02T03:04:05.000000Z"),
            (date(2024, 1, 2), "2024-01-02T00:00:00.000000Z"),
            ("2024-01-02T03:04:05.000000Z", "2024-01-02T03:04:05.000000Z"),
        ],
    )
    def test_format_values(self, value, expected):
        assert _format_date_filter(value) == expected


class TestBuildQueryParams:
    @pytest.mark.parametrize("endpoint", ["templates", "forms", "document_folders", "template_folders"])
    def test_paginated_non_incremental_endpoints_only_count(self, endpoint):
        params = _build_query_params(
            PANDADOC_ENDPOINTS[endpoint],
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
            incremental_field=None,
        )

        assert params == {"count": PAGE_SIZE}


class TestValidateCredentials:
    @mock.patch(PANDADOC_SESSION_PATCH)
    def test_validate_credentials_sends_api_key_header(self, mock_session):
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=200)

        validate_credentials("key")

        headers = mock_session.return_value.get.call_args.kwargs["headers"]
        assert headers["Authorization"] == "API-Key key"


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_until_short_page(self, MockSession):
        session = MockSession.return_value
        full_page = [{"id": str(i)} for i in range(PAGE_SIZE)]
        params, _auth = _wire(session, [_response(full_page), _response([{"id": "last"}])])

        manager = _make_manager()
        rows = _rows(pandadoc_source("key", "documents", team_id=1, job_id="j", resumable_source_manager=manager))

        assert rows[-1] == {"id": "last"}
        assert len(rows) == PAGE_SIZE + 1
        assert params[0]["page"] == 1
        assert params[1]["page"] == 2
        # State saved once, after the first (full) page, pointing at page 2.
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == PandaDocResumeConfig(page=2)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_page(self, MockSession):
        session = MockSession.return_value
        params, _auth = _wire(session, [_response([{"id": "9"}])])

        manager = _make_manager(PandaDocResumeConfig(page=5))
        _rows(pandadoc_source("key", "documents", team_id=1, job_id="j", resumable_source_manager=manager))

        assert params[0]["page"] == 5

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_request_includes_filter(self, MockSession):
        session = MockSession.return_value
        params, _auth = _wire(session, [_response([])])

        manager = _make_manager()
        _rows(
            pandadoc_source(
                "key",
                "documents",
                team_id=1,
                job_id="j",
                resumable_source_manager=manager,
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2024, 1, 1, tzinfo=UTC),
                incremental_field="date_modified",
            )
        )

        assert params[0]["modified_from"] == "2024-01-01T00:00:00.000000Z"
        assert params[0]["order_by"] == "date_modified"
