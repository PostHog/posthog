import json
from typing import Any

import pytest
from unittest import mock

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.apify_dataset import apify_dataset
from products.warehouse_sources.backend.temporal.data_imports.sources.apify_dataset.apify_dataset import (
    ApifyResumeConfig,
    apify_dataset_source,
    validate_credentials,
)

CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
APIFY_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.apify_dataset.apify_dataset.make_tracked_session"
)


def _response(body: Any, *, total: int | None = None) -> Response:
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(body).encode()
    if total is not None:
        resp.headers["X-Apify-Pagination-Total"] = str(total)
    return resp


def _make_manager(resume_state: ApifyResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    session.headers = {}
    params: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        params.append(dict(request.params or {}))
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return params


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _run(manager, responses):
    return apify_dataset_source(
        api_token="tok",
        dataset_id="ds1",
        endpoint="dataset_items",
        team_id=1,
        job_id="j",
        resumable_source_manager=manager,
    )


class TestPagination:
    @mock.patch.object(apify_dataset, "PAGE_SIZE", 2)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_progresses_offset_and_terminates_on_header_total(self, MockSession) -> None:
        session = MockSession.return_value
        # total=3: page 1 (2 rows, full) -> continue; page 2 (offset 2, 1 row) -> offset 4 >= 3 -> stop.
        params = _wire(session, [_response([{"i": 0}, {"i": 1}], total=3), _response([{"i": 2}], total=3)])

        manager = _make_manager()
        rows = _rows(_run(manager, None))

        assert [r["i"] for r in rows] == [0, 1, 2]
        assert params[0]["offset"] == 0
        assert params[0]["limit"] == 2
        assert params[0]["format"] == "json"
        assert params[1]["offset"] == 2
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == ApifyResumeConfig(offset=2)

    @mock.patch.object(apify_dataset, "PAGE_SIZE", 2)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_short_page_terminates(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([{"i": 0}], total=1)])

        manager = _make_manager()
        rows = _rows(_run(manager, None))

        assert [r["i"] for r in rows] == [0]
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch.object(apify_dataset, "PAGE_SIZE", 2)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_offset(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response([{"i": 200}], total=201)])

        manager = _make_manager(ApifyResumeConfig(offset=200))
        _rows(_run(manager, None))

        assert params[0]["offset"] == 200

    @mock.patch.object(apify_dataset, "PAGE_SIZE", 2)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_non_list_body_raises_loudly(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response({"error": "wrong shape"}, total=0)])

        # A misrouted request returning an error object (not a list) must fail loud, not sync it as a row.
        with pytest.raises(ValueError, match="list response body"):
            _rows(_run(_make_manager(), None))


class TestValidateCredentials:
    @mock.patch(APIFY_SESSION_PATCH)
    def test_ok(self, mock_session) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=200)
        assert validate_credentials("tok", "ds1") == (True, None)

    @mock.patch(APIFY_SESSION_PATCH)
    def test_unauthorized_message(self, mock_session) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=401)
        ok, msg = validate_credentials("tok", "ds1")
        assert ok is False
        assert "token" in (msg or "")

    @mock.patch(APIFY_SESSION_PATCH)
    def test_not_found_message(self, mock_session) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=404)
        ok, msg = validate_credentials("tok", "ds1")
        assert ok is False
        assert "Dataset not found" in (msg or "")

    @mock.patch(APIFY_SESSION_PATCH)
    def test_network_error_message(self, mock_session) -> None:
        mock_session.return_value.get.side_effect = Exception("boom")
        ok, msg = validate_credentials("tok", "ds1")
        assert ok is False
        assert "reach the Apify API" in (msg or "")
