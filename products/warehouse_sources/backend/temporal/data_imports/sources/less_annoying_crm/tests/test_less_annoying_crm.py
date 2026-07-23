import json
from typing import Any

import pytest
from unittest import mock

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.less_annoying_crm.less_annoying_crm import (
    PAGE_SIZE,
    LessAnnoyingCRMResumeConfig,
    less_annoying_crm_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.less_annoying_crm.settings import (
    ENDPOINTS,
    LESS_ANNOYING_CRM_ENDPOINTS,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the less_annoying_crm module.
LACRM_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.less_annoying_crm.less_annoying_crm.make_tracked_session"
# tenacity sleeps between client retries; patch its clock so the retry test stays fast.
SLEEP_PATCH = "tenacity.nap.time.sleep"


def _response(body: Any, status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    return resp


def _make_manager(resume_state: LessAnnoyingCRMResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and return a list that captures each request's JSON body AT SEND TIME.

    ``request.json`` is a single dict mutated in place across pages (the paginator writes ``Page`` into
    its nested ``Parameters``), so inspecting it after the run shows only the final state — snapshot a
    deep copy when each request is prepared instead.
    """
    session.headers = {}
    body_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        body_snapshots.append(json.loads(json.dumps(request.json or {})))
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return body_snapshots


def _source(endpoint: str, manager: mock.MagicMock):
    return less_annoying_crm_source("secret-key", endpoint, team_id=1, job_id="j", resumable_source_manager=manager)


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_non_paginated_single_call_reads_bare_array(self, MockSession) -> None:
        session = MockSession.return_value
        bodies = _wire(session, [_response([{"UserId": "1"}, {"UserId": "2"}])])

        rows = _rows(_source("users", _make_manager()))

        assert rows == [{"UserId": "1"}, {"UserId": "2"}]
        assert session.send.call_count == 1
        # Reference tables send no pagination params.
        assert bodies[0]["Function"] == "GetUsers"
        assert bodies[0]["Parameters"] == {}

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_stops_when_has_more_results_false(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response({"Results": [{"ContactId": "1"}], "HasMoreResults": False})])

        manager = _make_manager()
        rows = _rows(_source("contacts", manager))

        assert rows == [{"ContactId": "1"}]
        assert session.send.call_count == 1
        # A single terminal page never checkpoints.
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_until_has_more_false_and_progresses_page(self, MockSession) -> None:
        session = MockSession.return_value
        bodies = _wire(
            session,
            [
                _response({"Results": [{"ContactId": "1"}], "HasMoreResults": True}),
                _response({"Results": [{"ContactId": "2"}], "HasMoreResults": False}),
            ],
        )

        manager = _make_manager()
        rows = _rows(_source("contacts", manager))

        assert rows == [{"ContactId": "1"}, {"ContactId": "2"}]
        assert bodies[0]["Parameters"]["Page"] == 1
        assert bodies[1]["Parameters"]["Page"] == 2
        # Checkpoint saved after the first page (more remained), pointing at page 2.
        manager.save_state.assert_called_once_with(LessAnnoyingCRMResumeConfig(page=2))

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_short_page_without_flag_terminates(self, MockSession) -> None:
        session = MockSession.return_value
        # No HasMoreResults flag and a page shorter than PAGE_SIZE ends pagination via the heuristic.
        _wire(session, [_response({"Results": [{"ContactId": "1"}]})])

        rows = _rows(_source("contacts", _make_manager()))

        assert rows == [{"ContactId": "1"}]
        assert session.send.call_count == 1

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_page(self, MockSession) -> None:
        session = MockSession.return_value
        bodies = _wire(session, [_response({"Results": [{"ContactId": "9"}], "HasMoreResults": False})])

        _rows(_source("contacts", _make_manager(LessAnnoyingCRMResumeConfig(page=4))))

        assert bodies[0]["Parameters"]["Page"] == 4

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_first_page_yields_nothing(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response({"Results": [], "HasMoreResults": False})])

        assert _rows(_source("contacts", _make_manager())) == []


class TestRequestBody:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_contacts_send_page_size_and_sort(self, MockSession) -> None:
        session = MockSession.return_value
        bodies = _wire(session, [_response({"Results": [{"ContactId": "1"}], "HasMoreResults": False})])

        _rows(_source("contacts", _make_manager()))

        params = bodies[0]["Parameters"]
        assert params["Page"] == 1
        assert params["MaxNumberOfResults"] == PAGE_SIZE
        assert params["SortBy"] == "DateCreated"
        assert params["SortDirection"] == "Ascending"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_tasks_send_required_date_window_and_expand_dict_results(self, MockSession) -> None:
        session = MockSession.return_value
        # GetTasks nests results as an object keyed by id — every value must become its own row.
        bodies = _wire(
            session,
            [_response({"Results": {"a": {"TaskId": "a"}, "b": {"TaskId": "b"}}, "HasMoreResults": False})],
        )

        rows = _rows(_source("tasks", _make_manager()))

        assert rows == [{"TaskId": "a"}, {"TaskId": "b"}]
        params = bodies[0]["Parameters"]
        assert params["StartDate"] < params["EndDate"]
        assert params["SortDirection"] == "Ascending"
        assert "SortBy" not in params


class TestErrors:
    @mock.patch(SLEEP_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    @pytest.mark.parametrize("status", [429, 500, 502, 503])
    def test_retryable_statuses_raise_retryable(self, MockSession, _sleep, status: int) -> None:
        session = MockSession.return_value
        _wire(session, [_response({"Results": []}, status_code=status) for _ in range(5)])

        with pytest.raises(RESTClientRetryableError):
            _rows(_source("contacts", _make_manager()))

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_invalid_credentials_body_raises_matchable_error(self, MockSession) -> None:
        session = MockSession.return_value
        # LACRM returns a bad key as HTTP 400 with an error envelope. The raised message must contain
        # "Invalid credentials" so the source's non-retryable map disables the sync with friendly copy.
        _wire(
            session,
            [_response({"ErrorCode": "x", "ErrorDescription": "Invalid credentials. Please check."}, status_code=400)],
        )

        with pytest.raises(ValueError, match="Invalid credentials"):
            _rows(_source("contacts", _make_manager()))

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_error_envelope_fails_loud(self, MockSession) -> None:
        session = MockSession.return_value
        # A success-status body carrying an error envelope must raise, not silently sync 0 rows.
        _wire(session, [_response({"ErrorCode": "x", "ErrorDescription": "nope"})])

        with pytest.raises(ValueError):
            _rows(_source("contacts", _make_manager()))

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_sync_redacts_the_api_key(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([{"UserId": "1"}])])

        _rows(_source("users", _make_manager()))

        assert MockSession.call_args.kwargs["redact_values"] == ("secret-key",)


class TestValidateCredentials:
    @mock.patch(LACRM_SESSION_PATCH)
    def test_valid_key_returns_true(self, mock_session) -> None:
        mock_session.return_value.post.return_value = _response({"UserId": "1", "Email": "a@b.co"})
        assert validate_credentials("good-key") is True

    @mock.patch(LACRM_SESSION_PATCH)
    def test_invalid_key_status_returns_false(self, mock_session) -> None:
        mock_session.return_value.post.return_value = _response(
            {"ErrorCode": "x", "ErrorDescription": "Invalid credentials."}, status_code=400
        )
        assert validate_credentials("bad-key") is False

    @mock.patch(LACRM_SESSION_PATCH)
    def test_error_body_on_200_returns_false(self, mock_session) -> None:
        mock_session.return_value.post.return_value = _response({"ErrorCode": "x", "ErrorDescription": "boom"})
        assert validate_credentials("bad-key") is False

    @mock.patch(LACRM_SESSION_PATCH)
    def test_swallows_exceptions(self, mock_session) -> None:
        mock_session.return_value.post.side_effect = Exception("boom")
        assert validate_credentials("key") is False

    @mock.patch(LACRM_SESSION_PATCH)
    def test_probe_redacts_the_api_key(self, mock_session) -> None:
        mock_session.return_value.post.return_value = _response({"UserId": "1"})
        validate_credentials("secret-key")
        assert mock_session.call_args.kwargs["redact_values"] == ("secret-key",)


class TestSourceResponse:
    @pytest.mark.parametrize("endpoint", sorted(ENDPOINTS))
    def test_primary_keys_match_settings(self, endpoint: str) -> None:
        response = _source(endpoint, _make_manager())
        assert response.name == endpoint
        assert response.primary_keys == LESS_ANNOYING_CRM_ENDPOINTS[endpoint].primary_keys

    def test_partitioned_endpoint_uses_datetime_mode(self) -> None:
        response = _source("contacts", _make_manager())
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["DateCreated"]

    def test_reference_table_is_not_partitioned(self) -> None:
        response = _source("users", _make_manager())
        assert response.partition_mode is None
        assert response.partition_keys is None
