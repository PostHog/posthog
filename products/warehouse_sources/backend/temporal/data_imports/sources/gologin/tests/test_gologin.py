import json
from collections.abc import Iterator
from typing import cast
from urllib.parse import parse_qs, urlsplit

import pytest
from unittest.mock import MagicMock, patch

from requests import Response, Session
from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.gologin import (
    GoLoginSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.gologin.gologin import (
    GoLoginResumeConfig,
    gologin_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.gologin.settings import REQUEST_TIMEOUT
from products.warehouse_sources.backend.temporal.data_imports.sources.gologin.source import GoLoginSource


@pytest.fixture
def send() -> Iterator[MagicMock]:
    with (
        patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session",
            return_value=Session(),
        ),
        patch.object(Session, "send") as mock_send,
    ):
        yield mock_send


def response(body: object, status: int = 200) -> Response:
    result = Response()
    result.status_code = status
    result.url = "https://api.gologin.com/user"
    result.reason = {200: "OK", 401: "Unauthorized", 403: "Forbidden", 404: "Not Found"}[status]
    result.headers["Content-Type"] = "application/json"
    result._content = json.dumps(body).encode()
    return result


class TestGoLoginTransport:
    @pytest.mark.parametrize("resume_page", [None, 4])
    @pytest.mark.parametrize("incremental", [False, True])
    def test_profiles_page_requests_and_checkpoints(
        self, send: MagicMock, resume_page: int | None, incremental: bool
    ) -> None:
        rows = [{"id": f"profile-{index}", "createdAt": "2026-01-01T00:00:00Z"} for index in range(31)]
        send.side_effect = [
            response({"profiles": rows[:30], "allProfilesCount": 31}),
            response({"profiles": rows[30:], "allProfilesCount": 31}),
            response({"profiles": [], "allProfilesCount": 31}),
        ]
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = resume_page is not None
        manager.load_state.return_value = GoLoginResumeConfig(page=resume_page) if resume_page is not None else None
        inputs = MagicMock(spec=SourceInputs)
        inputs.schema_name = "profiles"
        inputs.team_id = 1
        inputs.job_id = "test-job"
        inputs.should_use_incremental_field = incremental
        inputs.db_incremental_field_last_value = "2026-01-02T00:00:00Z"
        source_response = GoLoginSource().source_for_pipeline(
            GoLoginSourceConfig(api_key="test-token"), manager, inputs
        )
        resource = cast(Resource, source_response.items())
        pages = iter(resource)
        assert next(pages) == rows[:30]
        first_page = resume_page or 1
        assert next(pages) == rows[30:]
        manager.save_state.assert_called_once_with(GoLoginResumeConfig(page=first_page + 1))
        assert list(pages) == []
        assert [call.args[0].page for call in manager.save_state.call_args_list] == [first_page + 1, first_page + 2]
        assert send.call_count == 3
        for index, call in enumerate(send.call_args_list):
            request = call.args[0]
            url = urlsplit(request.url)
            assert request.method == "GET"
            assert url.netloc == "api.gologin.com"
            assert url.path == "/browser/v2"
            assert parse_qs(url.query) == {
                "page": [str(first_page + index)],
                "sorterField": ["createdAt"],
                "sorterOrder": ["ascend"],
            }
            assert request.headers["Authorization"] == "Bearer test-token"
            assert call.kwargs["allow_redirects"] is False
            assert call.kwargs["timeout"] == REQUEST_TIMEOUT

    @pytest.mark.parametrize(
        ("endpoint", "path", "body", "expected"),
        [
            ("profiles", "/browser/v2", {"profiles": [], "allProfilesCount": 0}, []),
            ("workspaces", "/workspaces", [{"id": "workspace-1"}], [[{"id": "workspace-1"}]]),
            ("workspaces", "/workspaces", [], []),
            ("proxy_devices", "/proxy-devices", {"devices": [{"id": "device-1"}]}, [[{"id": "device-1"}]]),
            ("proxy_devices", "/proxy-devices", {"devices": []}, []),
        ],
    )
    def test_response_selection_and_terminal_page(
        self, send: MagicMock, endpoint: str, path: str, body: object, expected: list[list[dict[str, str]]]
    ) -> None:
        send.return_value = response(body)
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False
        result = gologin_source("test-token", endpoint, 1, "test-job", manager)
        assert list(cast(Resource, result.items())) == expected
        send.assert_called_once()
        request = send.call_args.args[0]
        assert urlsplit(request.url).path == path
        assert request.headers["Authorization"] == "Bearer test-token"
        assert send.call_args.kwargs["allow_redirects"] is False
        assert send.call_args.kwargs["timeout"] == REQUEST_TIMEOUT
        if endpoint != "profiles":
            assert urlsplit(request.url).query == ""
        manager.save_state.assert_not_called()

    @pytest.mark.parametrize("status", [401, 403])
    def test_pipeline_errors_match_user_messages(self, send: MagicMock, status: int) -> None:
        send.return_value = response({"statusCode": status}, status)
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False
        result = gologin_source("test-token", "profiles", 1, "test-job", manager)
        with pytest.raises(HTTPError) as raised:
            list(cast(Resource, result.items()))
        errors = GoLoginSource().get_non_retryable_errors()
        assert any(key in str(raised.value) and message for key, message in errors.items())
        send.assert_called_once()

    @pytest.mark.parametrize("status", [200, 401, 403, 404])
    def test_validation_uses_one_request(self, send: MagicMock, status: int) -> None:
        send.return_value = response({"id": "user-1"} if status == 200 else {"statusCode": status}, status)
        if status == 404:
            with pytest.raises(HTTPError):
                validate_credentials("test-token")
        else:
            valid, error = validate_credentials("test-token")
            assert valid is (status == 200)
            assert (error is None) is (status == 200)
            if error is not None:
                assert "API key" in error
        send.assert_called_once()
        request = send.call_args.args[0]
        assert request.url == "https://api.gologin.com/user"
        assert request.headers["Authorization"] == "Bearer test-token"
        assert send.call_args.kwargs["allow_redirects"] is False
        assert send.call_args.kwargs["timeout"] == REQUEST_TIMEOUT
