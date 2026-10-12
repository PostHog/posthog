import json
from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest import mock

import requests
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.productboard.productboard import (
    ProductboardResumeConfig,
    _build_initial_params,
    _format_incremental_value,
    productboard_source,
    validate_credentials,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the productboard module.
PRODUCTBOARD_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.productboard.productboard.make_tracked_session"
)

NOTES_URL = "https://api.productboard.com/v2/notes"


def _response(body: dict[str, Any]) -> Response:
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(body).encode()
    return resp


def _make_manager(resume_state: ProductboardResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and capture each request's url + params AT SEND TIME.

    The paginator mutates the single ``Request`` in place across pages (rewriting ``url`` and
    clearing ``params`` as it follows ``links.next``), so inspecting it after the run shows only the
    final state — snapshot a copy when each request is prepared instead.
    """
    session.headers = {}
    snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        snapshots.append({"url": request.url, "params": dict(request.params or {})})
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return snapshots


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


class TestFormatIncrementalValue:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (datetime(2023, 10, 1, 10, 0, 0, tzinfo=UTC), "2023-10-01T10:00:00Z"),
            (datetime(2023, 10, 1, 10, 0, 0), "2023-10-01T10:00:00Z"),
            (date(2023, 10, 1), "2023-10-01T00:00:00Z"),
            ("2023-10-01T10:00:00Z", "2023-10-01T10:00:00Z"),
            (123, "123"),
        ],
    )
    def test_format(self, value, expected):
        assert _format_incremental_value(value) == expected


class TestBuildInitialParams:
    def test_entity_endpoint_adds_type_filter(self):
        assert _build_initial_params("features", False, None, None) == {"type[]": "feature"}


class TestValidateCredentials:
    @mock.patch(PRODUCTBOARD_SESSION_PATCH)
    def test_request_exception_returns_no_status(self, mock_session):
        # A probe must never raise out of validate_credentials; a transport error means "not validated".
        mock_session.return_value.get.side_effect = requests.exceptions.ConnectionError("boom")
        assert validate_credentials("token", "/notes") == (False, None)


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_state(self, MockSession):
        session = MockSession.return_value
        resume_url = f"{NOTES_URL}?pageCursor=resume"
        snaps = _wire(session, [_response({"data": [{"id": "9"}], "links": {}})])

        manager = _make_manager(ProductboardResumeConfig(next_url=resume_url))
        rows = _rows(productboard_source("token", "notes", team_id=1, job_id="j", resumable_source_manager=manager))

        assert [r["id"] for r in rows] == ["9"]
        # The seeded next_url drives the very first request, with no leftover base params.
        assert snaps[0]["url"] == resume_url
        assert snaps[0]["params"] == {}

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_checkpoints_next_url_after_each_page(self, MockSession):
        # Save state points at the page still to fetch (links.next), saved after the current page is
        # yielded; the final page (no next link) records no checkpoint.
        session = MockSession.return_value
        page2_url = f"{NOTES_URL}?pageCursor=c2"
        _wire(
            session,
            [
                _response({"data": [{"id": "1"}], "links": {"next": page2_url}}),
                _response({"data": [{"id": "2"}], "links": {}}),
            ],
        )

        manager = _make_manager()
        _rows(productboard_source("token", "notes", team_id=1, job_id="j", resumable_source_manager=manager))

        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == ProductboardResumeConfig(next_url=page2_url)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_notes_incremental_sends_server_filter(self, MockSession):
        session = MockSession.return_value
        snaps = _wire(session, [_response({"data": [{"id": "n1"}], "links": {}})])

        _rows(
            productboard_source(
                "token",
                "notes",
                team_id=1,
                job_id="j",
                resumable_source_manager=_make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2023, 10, 1, 10, 0, 0, tzinfo=UTC),
                incremental_field="updatedAt",
            )
        )

        assert snaps[0]["params"] == {"updatedFrom": "2023-10-01T10:00:00Z"}
