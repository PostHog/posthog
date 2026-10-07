import json
from urllib.parse import parse_qs, urlsplit

import pytest
from unittest.mock import MagicMock, patch

from requests import HTTPError, PreparedRequest, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.vimeo import VimeoSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.vimeo.settings import AUTH_ERROR, PERMISSION_ERROR
from products.warehouse_sources.backend.temporal.data_imports.sources.vimeo.source import VimeoSource
from products.warehouse_sources.backend.temporal.data_imports.sources.vimeo.vimeo import VimeoResumeConfig


def response(body: dict[str, object], status: int = 200) -> Response:
    result = Response()
    result.status_code = status
    result._content = json.dumps(body).encode()
    result.headers["Content-Type"] = "application/json"
    return result


def inputs(endpoint: str, incremental: bool = False) -> MagicMock:
    result = MagicMock(spec=SourceInputs)
    result.schema_name = endpoint
    result.team_id = 1
    result.job_id = "vimeo-test"
    result.api_version = None
    result.should_use_incremental_field = incremental
    result.db_incremental_field_last_value = "2025-01-01T00:00:00Z" if incremental else None
    return result


@pytest.mark.parametrize(
    "endpoint,path", [("videos", "/me/videos"), ("folders", "/me/projects"), ("showcases", "/me/albums")]
)
@pytest.mark.parametrize("incremental", [False, True])
def test_pagination_and_full_refresh_params(endpoint: str, path: str, incremental: bool) -> None:
    manager = MagicMock(spec=ResumableSourceManager)
    manager.can_resume.return_value = False
    next_url = f"{path}?page=2&per_page=100&sort=date&direction=asc"
    pages = iter(
        [
            response({"data": [{"uri": "/resource/1"}], "paging": {"next": next_url}}),
            response({"data": [{"uri": "/resource/2"}], "paging": {"next": None}}),
        ]
    )
    requests: list[PreparedRequest] = []

    def send(request: PreparedRequest, **kwargs: object) -> Response:
        requests.append(request)
        result = next(pages)
        assert request.url is not None
        result.url = request.url
        return result

    with patch("requests.Session.send", side_effect=send):
        result = VimeoSource().source_for_pipeline(
            VimeoSourceConfig(access_token="test-token"), manager, inputs(endpoint, incremental)
        )
        rows = [row for page in result.items() for row in page]

    assert rows == [{"uri": "/resource/1"}, {"uri": "/resource/2"}]
    assert len(requests) == 2
    for index, request in enumerate(requests, start=1):
        url = urlsplit(request.url)
        assert url.netloc == "api.vimeo.com"
        assert url.path == path
        assert parse_qs(url.query) == {
            "page": [str(index)],
            "per_page": ["100"],
            "sort": ["date"],
            "direction": ["asc"],
        }
        assert request.headers["Authorization"] == "Bearer test-token"
        assert request.headers["Accept"] == "application/vnd.vimeo.*+json;version=3.4"
    manager.save_state.assert_called_once_with(VimeoResumeConfig(next_url=f"https://api.vimeo.com{next_url}"))
    assert result.primary_keys == ["uri"]


@pytest.mark.parametrize("resume", [None, "https://api.vimeo.com/me/videos?page=4&per_page=100"])
def test_resume_and_empty_terminal_page(resume: str | None) -> None:
    manager = MagicMock(spec=ResumableSourceManager)
    manager.can_resume.return_value = True
    manager.load_state.return_value = VimeoResumeConfig(next_url=resume) if resume else None
    with patch("requests.Session.send", return_value=response({"data": [], "paging": {"next": None}})) as send:
        result = VimeoSource().source_for_pipeline(
            VimeoSourceConfig(access_token="test-token"), manager, inputs("videos")
        )
        assert [row for page in result.items() for row in page] == []
    request = send.call_args.args[0]
    assert parse_qs(urlsplit(request.url).query)["page"] == (["4"] if resume else ["1"])
    send.assert_called_once()
    manager.save_state.assert_not_called()


@pytest.mark.parametrize("status,message", [(401, AUTH_ERROR), (403, PERMISSION_ERROR)])
def test_sync_error_mapping(status: int, message: str) -> None:
    manager = MagicMock(spec=ResumableSourceManager)
    manager.can_resume.return_value = False
    source = VimeoSource()
    with patch("requests.Session.send", return_value=response({"error": "Access denied"}, status)) as send:
        result = source.source_for_pipeline(VimeoSourceConfig(access_token="test-token"), manager, inputs("videos"))
        with pytest.raises(HTTPError) as error:
            list(result.items())
    assert any(key in str(error.value) and value == message for key, value in source.get_non_retryable_errors().items())
    send.assert_called_once()


@pytest.mark.parametrize("resume_url", ["https://example.com/videos?page=2", "http://api.vimeo.com/me/videos?page=2"])
def test_resume_cannot_send_token_to_another_origin(resume_url: str) -> None:
    manager = MagicMock(spec=ResumableSourceManager)
    manager.can_resume.return_value = True
    manager.load_state.return_value = VimeoResumeConfig(next_url=resume_url)
    with patch("requests.Session.send") as send:
        result = VimeoSource().source_for_pipeline(
            VimeoSourceConfig(access_token="test-token"), manager, inputs("videos")
        )
        with pytest.raises(ValueError, match="Refusing to send request"):
            list(result.items())
    send.assert_not_called()
