from typing import Any, Optional

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.ashby.ashby import (
    ASHBY_BASE_URL,
    AUTH_ERROR_HINT,
    AshbyAPIError,
    AshbyResumeConfig,
    _classify_failure_message,
    _errors_from_payload,
    ashby_source,
    check_access,
    get_rows,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.ashby.settings import ENDPOINTS

SESSION_PATH = "products.warehouse_sources.backend.temporal.data_imports.sources.ashby.ashby.make_tracked_session"


class FakeResponse:
    def __init__(
        self, status_code: int = 200, json_data: Optional[dict[str, Any]] = None, raise_json: bool = False
    ) -> None:
        self.status_code = status_code
        self._json = json_data if json_data is not None else {}
        self.text = str(self._json)
        self._raise_json = raise_json

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 300

    def json(self) -> dict[str, Any]:
        if self._raise_json:
            raise ValueError("no json")
        return self._json

    def raise_for_status(self) -> None:
        if not self.ok:
            raise Exception(f"{self.status_code} Client Error")


class FakeSession:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def post(self, url: str, json: Any = None, auth: Any = None, headers: Any = None, timeout: Any = None):
        self.calls.append({"url": url, "json": json, "auth": auth, "headers": headers})
        return self._responses[0] if len(self._responses) == 1 else self._responses.pop(0)


def _manager(can_resume: bool = False, state: Optional[AshbyResumeConfig] = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = can_resume
    manager.load_state.return_value = state
    return manager


class TestClassifyFailureMessage:
    @pytest.mark.parametrize(
        "errors, expected_auth",
        [
            (["Invalid API key"], True),
            (["You are not authorized to perform this action"], True),
            (["Missing permission: candidatesRead"], True),
            (["Forbidden"], True),
            (["sync_token_expired"], False),
            (["Some random validation error"], False),
            ([], False),
        ],
    )
    def test_classify(self, errors: list[str], expected_auth: bool) -> None:
        is_auth, message = _classify_failure_message(errors)
        assert is_auth is expected_auth
        assert isinstance(message, str)


class TestErrorsFromPayload:
    @pytest.mark.parametrize(
        "payload, expected",
        [
            ({"errors": ["a", "b"]}, ["a", "b"]),
            ({"errors": "single"}, ["single"]),
            ({"error": "legacy"}, ["legacy"]),
            ({"success": False}, []),
        ],
    )
    def test_errors_from_payload(self, payload: dict[str, Any], expected: list[Any]) -> None:
        assert _errors_from_payload(payload) == expected


class TestGetRows:
    def test_paginates_until_no_more_data(self) -> None:
        responses = [
            FakeResponse(
                json_data={"success": True, "results": [{"id": "1"}], "moreDataAvailable": True, "nextCursor": "c1"}
            ),
            FakeResponse(json_data={"success": True, "results": [{"id": "2"}], "moreDataAvailable": False}),
        ]
        session = FakeSession(responses)
        manager = _manager()

        with mock.patch(SESSION_PATH, return_value=session):
            batches = list(get_rows("dummy-key", "candidates", mock.MagicMock(), manager))

        assert batches == [[{"id": "1"}], [{"id": "2"}]]
        # First call has no cursor, second forwards nextCursor.
        assert "cursor" not in session.calls[0]["json"]
        assert session.calls[1]["json"]["cursor"] == "c1"
        assert session.calls[0]["json"]["limit"] == 100
        assert session.calls[0]["auth"] == ("dummy-key", "")
        assert session.calls[0]["url"] == f"{ASHBY_BASE_URL}/candidate.list"

    def test_saves_state_after_yielding_each_page(self) -> None:
        responses = [
            FakeResponse(
                json_data={"success": True, "results": [{"id": "1"}], "moreDataAvailable": True, "nextCursor": "c1"}
            ),
            FakeResponse(json_data={"success": True, "results": [{"id": "2"}], "moreDataAvailable": False}),
        ]
        manager = _manager()

        with mock.patch(SESSION_PATH, return_value=FakeSession(responses)):
            list(get_rows("k", "candidates", mock.MagicMock(), manager))

        manager.save_state.assert_called_once_with(AshbyResumeConfig(cursor="c1"))

    def test_resumes_from_saved_cursor(self) -> None:
        responses = [FakeResponse(json_data={"success": True, "results": [{"id": "9"}], "moreDataAvailable": False})]
        session = FakeSession(responses)
        manager = _manager(can_resume=True, state=AshbyResumeConfig(cursor="resume-cursor"))

        with mock.patch(SESSION_PATH, return_value=session):
            batches = list(get_rows("k", "candidates", mock.MagicMock(), manager))

        assert batches == [[{"id": "9"}]]
        assert session.calls[0]["json"]["cursor"] == "resume-cursor"

    def test_empty_results_yield_nothing(self) -> None:
        responses = [FakeResponse(json_data={"success": True, "results": [], "moreDataAvailable": False})]

        with mock.patch(SESSION_PATH, return_value=FakeSession(responses)):
            batches = list(get_rows("k", "users", mock.MagicMock(), _manager()))

        assert batches == []

    @pytest.mark.parametrize(
        "response",
        [
            FakeResponse(status_code=401),
            FakeResponse(status_code=403),
        ],
    )
    def test_http_auth_errors_raise_matchable_api_error(self, response: FakeResponse) -> None:
        with mock.patch(SESSION_PATH, return_value=FakeSession([response])):
            with pytest.raises(AshbyAPIError) as exc:
                list(get_rows("k", "candidates", mock.MagicMock(), _manager()))
        assert f"{response.status_code} Client Error" in str(exc.value)

    def test_success_false_auth_error_raises_matchable_api_error(self) -> None:
        response = FakeResponse(json_data={"success": False, "errors": ["Missing permission: candidatesRead"]})
        with mock.patch(SESSION_PATH, return_value=FakeSession([response])):
            with pytest.raises(AshbyAPIError) as exc:
                list(get_rows("k", "candidates", mock.MagicMock(), _manager()))
        assert AUTH_ERROR_HINT in str(exc.value)


class TestCheckAccess:
    @pytest.mark.parametrize(
        "response, expected_status",
        [
            (FakeResponse(json_data={"success": True, "results": []}), 200),
            (FakeResponse(status_code=401), 401),
            (FakeResponse(status_code=403), 403),
            (FakeResponse(json_data={"success": False, "errors": ["Missing permission"]}), 403),
            (FakeResponse(json_data={"success": False, "errors": ["bad request"]}), 400),
            (FakeResponse(status_code=500), 500),
            (FakeResponse(raise_json=True), 0),
        ],
    )
    def test_status_mapping(self, response: FakeResponse, expected_status: int) -> None:
        with mock.patch(SESSION_PATH, return_value=FakeSession([response])):
            status, _message = check_access("k", "department.list")
        assert status == expected_status

    def test_connection_error_returns_zero(self) -> None:
        session = mock.MagicMock()
        session.post.side_effect = Exception("boom")
        with mock.patch(SESSION_PATH, return_value=session):
            status, message = check_access("k", "department.list")
        assert status == 0
        assert message is not None


class TestAshbySource:
    def test_candidates_partitioned_by_created_at(self) -> None:
        response = ashby_source("k", "candidates", mock.MagicMock(), _manager())
        assert response.name == "candidates"
        assert response.primary_keys == ["id"]
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["createdAt"]

    def test_reference_endpoint_is_unpartitioned(self) -> None:
        response = ashby_source("k", "users", mock.MagicMock(), _manager())
        assert response.partition_mode is None
        assert response.partition_keys is None
        assert response.primary_keys == ["id"]

    def test_all_endpoints_buildable(self) -> None:
        for endpoint in ENDPOINTS:
            response = ashby_source("k", endpoint, mock.MagicMock(), _manager())
            assert response.primary_keys == ["id"]
