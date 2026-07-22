import json
from typing import Any

import pytest
from unittest import mock

from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.recruitee.recruitee import (
    PAGE_SIZE,
    RecruiteeResumeConfig,
    base_url,
    recruitee_source,
    validate_credentials,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the recruitee module.
RECRUITEE_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.recruitee.recruitee.make_tracked_session"
)
# Every request is pinned to this host, so mocked prepared requests must carry a valid URL.
PREPARED_URL = "https://api.recruitee.com/c/acme/candidates"


def _response(items: list[dict[str, Any]] | None, *, data_key: str = "candidates", body: Any = None) -> Response:
    payload: Any = body if body is not None else {data_key: items or []}
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(payload).encode()
    return resp


def _make_manager(resume_state: RecruiteeResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and return a list capturing each request's params AT SEND TIME.

    ``request.params`` is one dict mutated in place across pages, so snapshot a copy at
    prepare_request time. The prepared request must carry a real host URL because the client's
    host-pinning guard runs on every send.
    """
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        param_snapshots.append(dict(request.params or {}))
        return mock.MagicMock(url=PREPARED_URL)

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return param_snapshots


def _source(endpoint: str = "candidates", manager: mock.MagicMock | None = None):
    return recruitee_source(
        company_id="acme",
        api_token="rc-token",
        endpoint=endpoint,
        team_id=1,
        job_id="j",
        resumable_source_manager=manager if manager is not None else _make_manager(),
    )


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


class TestBaseUrl:
    def test_interpolates_company_id_into_path(self) -> None:
        assert base_url("mycompany") == "https://api.recruitee.com/c/mycompany"

    @parameterized.expand([("slash", "a/b"), ("dot", "evil.com"), ("space", "a b"), ("at", "user@host")])
    def test_rejects_unsafe_company_id(self, _name: str, company_id: str) -> None:
        with pytest.raises(ValueError):
            base_url(company_id)


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_and_progresses_offset(self, MockSession) -> None:
        session = MockSession.return_value
        full_page = [{"id": i} for i in range(PAGE_SIZE)]
        params = _wire(session, [_response(full_page), _response([{"id": 999}])])

        manager = _make_manager()
        rows = _rows(_source(manager=manager))

        assert [r["id"] for r in rows] == [*range(PAGE_SIZE), 999]
        assert params[0]["offset"] == 0
        assert params[0]["limit"] == PAGE_SIZE
        assert params[1]["offset"] == PAGE_SIZE
        # Checkpoint saved once after the first full page (points at the next page); short page ends it.
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == RecruiteeResumeConfig(offset=PAGE_SIZE)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_short_first_page_makes_one_request_and_no_checkpoint(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([{"id": 1}, {"id": 2}])])

        manager = _make_manager()
        rows = _rows(_source(manager=manager))

        assert [r["id"] for r in rows] == [1, 2]
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_first_page_yields_nothing(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([])])

        manager = _make_manager()
        rows = _rows(_source(manager=manager))

        assert rows == []
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_offset(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response([{"id": 5}])])

        manager = _make_manager(RecruiteeResumeConfig(offset=200))
        _rows(_source(manager=manager))

        # Offset 0 must never be fetched on resume — the first request starts at the saved offset.
        assert params[0]["offset"] == 200


class TestDataExtraction:
    @parameterized.expand([("candidates",), ("offers",), ("departments",), ("placements",)])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_extracts_rows_from_resource_named_key(self, endpoint: str, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([{"id": 1}, {"id": 2}], data_key=endpoint)])

        rows = _rows(_source(endpoint=endpoint))
        assert [r["id"] for r in rows] == [1, 2]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_accept_header_set_on_session(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([{"id": 1}])])

        _rows(_source())
        assert session.headers.get("Accept") == "application/json"

    @parameterized.expand(
        [
            ("non_dict_body", [{"id": 1}]),
            ("missing_data_key", {"offers": []}),
            ("value_not_a_list", {"candidates": {"id": 1}}),
        ]
    )
    @mock.patch("tenacity.nap.time.sleep", return_value=None)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_malformed_body_is_retried_then_raises(self, _name: str, malformed: Any, MockSession, _sleep) -> None:
        session = MockSession.return_value
        # A 200 whose body isn't the expected list-under-key shape is retried; after the attempts are
        # exhausted the retryable error propagates instead of syncing 0 rows or a garbage row.
        _wire(session, [_response(None, body=malformed) for _ in range(5)])

        with pytest.raises(RESTClientRetryableError):
            _rows(_source())


class TestValidateCredentials:
    def _patch_get(self, mock_session, *, status: int | None = None, raises: Exception | None = None) -> None:
        get = mock_session.return_value.get
        if raises is not None:
            get.side_effect = raises
        else:
            get.return_value = mock.MagicMock(status_code=status)

    @parameterized.expand(
        [
            ("ok", 200, True, None),
            ("unauthorized", 401, False, "Invalid Recruitee company ID or API token"),
            ("forbidden", 403, False, "Invalid Recruitee company ID or API token"),
            ("server_error", 500, False, "Recruitee returned HTTP 500"),
        ]
    )
    @mock.patch(RECRUITEE_SESSION_PATCH)
    def test_status_mapping(
        self, _name: str, status: int, expected_valid: bool, expected_message: str | None, mock_session
    ) -> None:
        self._patch_get(mock_session, status=status)
        assert validate_credentials("acme", "rc-token") == (expected_valid, expected_message)

    @mock.patch(RECRUITEE_SESSION_PATCH)
    def test_connection_error_is_not_validated(self, mock_session) -> None:
        self._patch_get(mock_session, raises=Exception("boom"))
        assert validate_credentials("acme", "rc-token") == (False, "Could not validate Recruitee credentials")
