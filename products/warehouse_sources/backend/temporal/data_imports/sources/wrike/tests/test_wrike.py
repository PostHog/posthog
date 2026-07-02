from typing import Any

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.wrike.settings import WRIKE_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.wrike.wrike import (
    WrikeResumeConfig,
    _build_url,
    get_rows,
    is_host_valid,
    validate_credentials,
    wrike_source,
)


def _mock_response(status_code: int = 200, json_body: dict[str, Any] | None = None) -> mock.MagicMock:
    response = mock.MagicMock()
    response.status_code = status_code
    response.ok = 200 <= status_code < 300
    response.json.return_value = json_body or {}
    response.text = ""
    return response


def _mock_session_returning(responses: list[mock.MagicMock]) -> mock.MagicMock:
    session = mock.MagicMock()
    session.get.side_effect = responses
    return session


class TestIsHostValid:
    @pytest.mark.parametrize(
        "host, expected",
        [
            ("www.wrike.com", True),
            ("app-us2.wrike.com", True),
            ("app-eu.wrike.com", True),
            ("https://www.wrike.com/", True),
            ("WWW.WRIKE.COM", True),
            ("www.wrike.com:443", True),
            ("evil.com", False),
            ("wrike.com.evil.com", False),
            ("notwrike.com", False),
            ("localhost", False),
            ("169.254.169.254", False),
            ("", False),
            # SSRF bypass attempts: a path/query/credentials must not smuggle a non-Wrike
            # netloc past the suffix check.
            ("evil.com?.wrike.com", False),
            ("evil.com/.wrike.com", False),
            ("internal.service/path.wrike.com", False),
            ("evil.com#.wrike.com", False),
            ("user:pass@evil.com", False),
            ("user@evil.com:443", False),
        ],
    )
    def test_is_host_valid(self, host: str, expected: bool) -> None:
        assert is_host_valid(host) is expected

    @pytest.mark.parametrize(
        "host",
        ["evil.com?.wrike.com", "internal.service/path.wrike.com", "user:pass@evil.com.attacker.net"],
    )
    def test_build_url_target_never_diverges_from_validation(self, host: str) -> None:
        # The connection target is built from the same normalized hostname is_host_valid checks,
        # so a host that fails validation can never resolve to a Wrike URL.
        assert is_host_valid(host) is False
        assert "wrike.com/api/v4" not in _build_url(host, "/tasks", {})


class TestBuildUrl:
    def test_no_params(self) -> None:
        assert _build_url("www.wrike.com", "/tasks", {}) == "https://www.wrike.com/api/v4/tasks"

    def test_with_params(self) -> None:
        url = _build_url("www.wrike.com", "/tasks", {"pageSize": 1000})
        assert url == "https://www.wrike.com/api/v4/tasks?pageSize=1000"

    def test_drops_none_values(self) -> None:
        url = _build_url("app-us2.wrike.com", "/tasks", {"pageSize": 1000, "nextPageToken": None})
        assert url == "https://app-us2.wrike.com/api/v4/tasks?pageSize=1000"

    def test_normalizes_scheme_and_trailing_slash(self) -> None:
        assert _build_url("https://www.wrike.com/", "/contacts", {}) == "https://www.wrike.com/api/v4/contacts"


class TestValidateCredentials:
    def test_rejects_non_wrike_host_without_request(self) -> None:
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.wrike.wrike.make_tracked_session"
        ) as make_session:
            is_valid, error = validate_credentials("token", "evil.com")
        assert is_valid is False
        assert error is not None and "Wrike domain" in error
        make_session.assert_not_called()

    @pytest.mark.parametrize(
        "status_code, expected_valid, expected_error",
        [
            (200, True, None),
            (401, False, "Invalid Wrike access token"),
            (403, False, "Wrike access token is missing the required permissions"),
            (500, False, "Wrike API error: status=500"),
        ],
    )
    def test_status_mapping(self, status_code: int, expected_valid: bool, expected_error: str | None) -> None:
        session = _mock_session_returning([_mock_response(status_code)])
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.wrike.wrike.make_tracked_session",
            return_value=session,
        ):
            is_valid, error = validate_credentials("token", "www.wrike.com")
        assert is_valid is expected_valid
        assert error == expected_error

    def test_probes_current_user_endpoint(self) -> None:
        session = _mock_session_returning([_mock_response(200)])
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.wrike.wrike.make_tracked_session",
            return_value=session,
        ):
            validate_credentials("token", "www.wrike.com")
        called_url = session.get.call_args.args[0]
        assert called_url == "https://www.wrike.com/api/v4/contacts?me=true"


class TestGetRows:
    def _manager(self, can_resume: bool = False, resume_state: WrikeResumeConfig | None = None) -> mock.MagicMock:
        manager = mock.MagicMock()
        manager.can_resume.return_value = can_resume
        manager.load_state.return_value = resume_state
        return manager

    def test_non_paginated_endpoint_single_page(self) -> None:
        session = _mock_session_returning(
            [_mock_response(200, {"kind": "contacts", "data": [{"id": "a"}, {"id": "b"}]})]
        )
        manager = self._manager()
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.wrike.wrike.make_tracked_session",
            return_value=session,
        ):
            batches = list(get_rows("token", "www.wrike.com", "contacts", mock.MagicMock(), manager))

        assert batches == [[{"id": "a"}, {"id": "b"}]]
        assert session.get.call_count == 1
        manager.save_state.assert_not_called()

    def test_paginated_endpoint_follows_next_page_token(self) -> None:
        session = _mock_session_returning(
            [
                _mock_response(200, {"data": [{"id": 1}], "nextPageToken": "tok2"}),
                _mock_response(200, {"data": [{"id": 2}]}),
            ]
        )
        manager = self._manager()
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.wrike.wrike.make_tracked_session",
            return_value=session,
        ):
            batches = list(get_rows("token", "www.wrike.com", "tasks", mock.MagicMock(), manager))

        assert batches == [[{"id": 1}], [{"id": 2}]]
        # First request carries pageSize; second carries only the token.
        first_url, second_url = session.get.call_args_list[0].args[0], session.get.call_args_list[1].args[0]
        assert "pageSize=1000" in first_url
        assert "nextPageToken=tok2" in second_url
        # State saved once, after yielding the first page, before fetching the next.
        manager.save_state.assert_called_once_with(WrikeResumeConfig(next_page_token="tok2"))

    def test_resumes_from_saved_state(self) -> None:
        session = _mock_session_returning([_mock_response(200, {"data": [{"id": 3}]})])
        manager = self._manager(can_resume=True, resume_state=WrikeResumeConfig(next_page_token="resume_tok"))
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.wrike.wrike.make_tracked_session",
            return_value=session,
        ):
            batches = list(get_rows("token", "www.wrike.com", "tasks", mock.MagicMock(), manager))

        assert batches == [[{"id": 3}]]
        assert "nextPageToken=resume_tok" in session.get.call_args.args[0]

    def test_rejects_non_wrike_host_before_any_request(self) -> None:
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.wrike.wrike.make_tracked_session"
        ) as make_session:
            with pytest.raises(ValueError, match="non-Wrike host"):
                list(get_rows("token", "evil.com", "tasks", mock.MagicMock(), self._manager()))
        make_session.assert_not_called()

    def test_empty_data_yields_nothing(self) -> None:
        session = _mock_session_returning([_mock_response(200, {"data": []})])
        manager = self._manager()
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.wrike.wrike.make_tracked_session",
            return_value=session,
        ):
            batches = list(get_rows("token", "www.wrike.com", "tasks", mock.MagicMock(), manager))
        assert batches == []


class TestWrikeSource:
    def test_tasks_partition_on_created_date(self) -> None:
        response = wrike_source("token", "www.wrike.com", "tasks", mock.MagicMock(), mock.MagicMock())
        assert response.name == "tasks"
        assert response.primary_keys == ["id"]
        assert response.sort_mode == "asc"
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["createdDate"]

    @pytest.mark.parametrize("endpoint", [name for name, cfg in WRIKE_ENDPOINTS.items() if cfg.partition_key is None])
    def test_unpartitioned_endpoints(self, endpoint: str) -> None:
        response = wrike_source("token", "www.wrike.com", endpoint, mock.MagicMock(), mock.MagicMock())
        assert response.primary_keys == ["id"]
        assert response.partition_mode is None
        assert response.partition_keys is None
