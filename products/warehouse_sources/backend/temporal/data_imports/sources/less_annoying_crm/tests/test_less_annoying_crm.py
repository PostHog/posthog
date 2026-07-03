from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.less_annoying_crm import less_annoying_crm
from products.warehouse_sources.backend.temporal.data_imports.sources.less_annoying_crm.less_annoying_crm import (
    PAGE_SIZE,
    LessAnnoyingCRMError,
    LessAnnoyingCRMResumeConfig,
    LessAnnoyingCRMRetryableError,
    _build_parameters,
    _extract_records,
    _is_error_body,
    get_rows,
    less_annoying_crm_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.less_annoying_crm.settings import (
    ENDPOINTS,
    LESS_ANNOYING_CRM_ENDPOINTS,
)

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.less_annoying_crm.less_annoying_crm"

LOGGER = MagicMock()


def _response(status_code: int = 200, body: Any = None) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.ok = 200 <= status_code < 300
    if body is None:
        response.json.side_effect = ValueError("no json")
    else:
        response.json.return_value = body
    return response


def _session_returning(*responses: MagicMock) -> MagicMock:
    session = MagicMock()
    session.post.side_effect = list(responses)
    return session


def _manager(resume: LessAnnoyingCRMResumeConfig | None = None) -> MagicMock:
    manager = MagicMock(spec=ResumableSourceManager)
    manager.can_resume.return_value = resume is not None
    manager.load_state.return_value = resume
    return manager


class TestExtractRecords:
    @pytest.mark.parametrize(
        ("data", "result_path", "expected"),
        [
            # Bare top-level array (users / teams).
            ([{"UserId": "1"}, {"UserId": "2"}], [], [{"UserId": "1"}, {"UserId": "2"}]),
            # Wrapped list (contacts / notes / events).
            ({"Results": [{"ContactId": "1"}]}, ["Results"], [{"ContactId": "1"}]),
            # Object keyed by id (GetTasks) — expand to values.
            (
                {"Results": {"a": {"TaskId": "a"}, "b": {"TaskId": "b"}}},
                ["Results"],
                [{"TaskId": "a"}, {"TaskId": "b"}],
            ),
            # Missing key yields nothing rather than raising.
            ({"Other": []}, ["Results"], []),
            # Empty results.
            ({"Results": []}, ["Results"], []),
            # Non-collection leaf.
            ({"Results": "nope"}, ["Results"], []),
        ],
    )
    def test_extract_records(self, data: Any, result_path: list[str], expected: list[dict[str, Any]]) -> None:
        assert _extract_records(data, result_path) == expected


class TestIsErrorBody:
    @pytest.mark.parametrize(
        ("data", "expected"),
        [
            ({"ErrorCode": "x", "ErrorDescription": "Invalid credentials."}, True),
            ({"ErrorDescription": "boom"}, True),
            ({"Results": []}, False),
            ([{"UserId": "1"}], False),
            (None, False),
        ],
    )
    def test_is_error_body(self, data: Any, expected: bool) -> None:
        assert _is_error_body(data) is expected


class TestBuildParameters:
    def test_paginated_endpoint_sends_page_and_size(self) -> None:
        params = _build_parameters(LESS_ANNOYING_CRM_ENDPOINTS["contacts"], page=3)
        assert params["Page"] == 3
        assert params["MaxNumberOfResults"] == PAGE_SIZE
        assert params["SortBy"] == "DateCreated"
        assert params["SortDirection"] == "Ascending"

    def test_non_paginated_endpoint_omits_pagination(self) -> None:
        params = _build_parameters(LESS_ANNOYING_CRM_ENDPOINTS["users"], page=1)
        assert "Page" not in params
        assert "MaxNumberOfResults" not in params

    def test_required_date_window_is_always_sent(self) -> None:
        params = _build_parameters(LESS_ANNOYING_CRM_ENDPOINTS["tasks"], page=1)
        assert "StartDate" in params
        assert "EndDate" in params
        # A wide window so a full refresh still returns every task.
        assert params["StartDate"] < params["EndDate"]


class TestCallFunction:
    def test_success_returns_json(self) -> None:
        session = _session_returning(_response(200, {"Results": [{"ContactId": "1"}]}))
        data = less_annoying_crm._call_function(session, "key", "GetContacts", {"Page": 1}, LOGGER)
        assert data == {"Results": [{"ContactId": "1"}]}

    @pytest.mark.parametrize("status", [429, 500, 502, 503])
    def test_retryable_statuses_raise_retryable(self, status: int) -> None:
        session = _session_returning(*[_response(status) for _ in range(5)])
        # Skip tenacity's real backoff sleeps so the test stays fast.
        with patch("time.sleep"), pytest.raises(LessAnnoyingCRMRetryableError):
            less_annoying_crm._call_function(session, "key", "GetContacts", {}, LOGGER)

    def test_error_body_surfaces_description(self) -> None:
        # LACRM returns credential failures as HTTP 400 with a JSON error body.
        session = _session_returning(
            _response(400, {"ErrorCode": "x", "ErrorDescription": "Invalid credentials. Please make sure."})
        )
        with pytest.raises(LessAnnoyingCRMError, match="Invalid credentials"):
            less_annoying_crm._call_function(session, "key", "GetUser", {}, LOGGER)

    def test_error_body_on_200_still_raises(self) -> None:
        session = _session_returning(_response(200, {"ErrorCode": "x", "ErrorDescription": "nope"}))
        with pytest.raises(LessAnnoyingCRMError):
            less_annoying_crm._call_function(session, "key", "GetUser", {}, LOGGER)


class TestValidateCredentials:
    def test_valid_key_returns_true(self) -> None:
        session = _session_returning(_response(200, {"UserId": "1", "Email": "a@b.co"}))
        with patch(f"{MODULE}.make_tracked_session", return_value=session):
            assert validate_credentials("good-key") is True

    def test_invalid_key_returns_false(self) -> None:
        session = _session_returning(_response(400, {"ErrorCode": "x", "ErrorDescription": "Invalid credentials."}))
        with patch(f"{MODULE}.make_tracked_session", return_value=session):
            assert validate_credentials("bad-key") is False

    def test_probe_redacts_the_api_key(self) -> None:
        session = _session_returning(_response(200, {"UserId": "1"}))
        with patch(f"{MODULE}.make_tracked_session", return_value=session) as make_session:
            validate_credentials("secret-key")
        assert make_session.call_args.kwargs["redact_values"] == ("secret-key",)


class TestGetRows:
    def test_sync_redacts_the_api_key(self) -> None:
        session = _session_returning(_response(200, [{"UserId": "1"}]))
        with patch(f"{MODULE}.make_tracked_session", return_value=session) as make_session:
            list(get_rows("secret-key", "users", LOGGER, _manager()))
        assert make_session.call_args.kwargs["redact_values"] == ("secret-key",)

    def test_non_paginated_single_call(self) -> None:
        session = _session_returning(_response(200, [{"UserId": "1"}, {"UserId": "2"}]))
        with patch(f"{MODULE}.make_tracked_session", return_value=session):
            pages = list(get_rows("key", "users", LOGGER, _manager()))
        assert pages == [[{"UserId": "1"}, {"UserId": "2"}]]
        assert session.post.call_count == 1

    def test_stops_when_no_more_results(self) -> None:
        session = _session_returning(_response(200, {"Results": [{"ContactId": "1"}], "HasMoreResults": False}))
        with patch(f"{MODULE}.make_tracked_session", return_value=session):
            pages = list(get_rows("key", "contacts", LOGGER, _manager()))
        assert pages == [[{"ContactId": "1"}]]
        assert session.post.call_count == 1

    def test_paginates_until_has_more_false(self) -> None:
        page1 = _response(200, {"Results": [{"ContactId": "1"}], "HasMoreResults": True})
        page2 = _response(200, {"Results": [{"ContactId": "2"}], "HasMoreResults": False})
        session = _session_returning(page1, page2)
        manager = _manager()
        with patch(f"{MODULE}.make_tracked_session", return_value=session):
            pages = list(get_rows("key", "contacts", LOGGER, manager))
        assert pages == [[{"ContactId": "1"}], [{"ContactId": "2"}]]
        # State saved after yielding the first page (more remained), pointing at page 2.
        assert manager.save_state.call_args_list[0].args[0] == LessAnnoyingCRMResumeConfig(page=2)

    def test_resumes_from_saved_page(self) -> None:
        session = _session_returning(_response(200, {"Results": [{"ContactId": "9"}], "HasMoreResults": False}))
        with patch(f"{MODULE}.make_tracked_session", return_value=session):
            list(get_rows("key", "contacts", LOGGER, _manager(LessAnnoyingCRMResumeConfig(page=4))))
        assert session.post.call_args.kwargs["json"]["Parameters"]["Page"] == 4

    def test_empty_first_page_yields_nothing(self) -> None:
        session = _session_returning(_response(200, {"Results": [], "HasMoreResults": False}))
        with patch(f"{MODULE}.make_tracked_session", return_value=session):
            pages = list(get_rows("key", "contacts", LOGGER, _manager()))
        assert pages == []


class TestSourceResponse:
    @pytest.mark.parametrize("endpoint", sorted(ENDPOINTS))
    def test_primary_keys_match_settings(self, endpoint: str) -> None:
        response = less_annoying_crm_source("key", endpoint, LOGGER, _manager())
        assert response.name == endpoint
        assert response.primary_keys == LESS_ANNOYING_CRM_ENDPOINTS[endpoint].primary_keys

    def test_partitioned_endpoint_uses_datetime_mode(self) -> None:
        response = less_annoying_crm_source("key", "contacts", LOGGER, _manager())
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["DateCreated"]

    def test_reference_table_is_not_partitioned(self) -> None:
        response = less_annoying_crm_source("key", "users", LOGGER, _manager())
        assert response.partition_mode is None
        assert response.partition_keys is None
