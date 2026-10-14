import pytest

from requests import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.vimeo import VimeoSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.vimeo.settings import AUTH_ERROR, PERMISSION_ERROR
from products.warehouse_sources.backend.temporal.data_imports.sources.vimeo.source import VimeoSource
from products.warehouse_sources.backend.temporal.data_imports.sources.vimeo.vimeo import VimeoResumeConfig


def driver() -> SourceDriver:
    return SourceDriver(VimeoSource(), VimeoSourceConfig(access_token="test-token"))


@pytest.mark.parametrize(
    "endpoint,path", [("videos", "/me/videos"), ("folders", "/me/projects"), ("showcases", "/me/albums")]
)
@pytest.mark.parametrize("incremental", [False, True])
def test_pagination_and_full_refresh_params(endpoint: str, path: str, incremental: bool) -> None:
    next_url = f"{path}?page=2&per_page=100&sort=date&direction=asc"
    result = driver().run(
        endpoint,
        [
            ScriptedResponse(json={"data": [{"uri": "/resource/1"}], "paging": {"next": next_url}}),
            ScriptedResponse(json={"data": [{"uri": "/resource/2"}], "paging": {"next": None}}),
        ],
        incremental_field="date_modified" if incremental else None,
        db_incremental_field_last_value="2025-01-01T00:00:00Z" if incremental else None,
    )

    assert result.rows == [{"uri": "/resource/1"}, {"uri": "/resource/2"}]
    assert len(result.requests) == 2
    for index, request in enumerate(result.requests, start=1):
        assert request.url.startswith(f"https://api.vimeo.com{path}?")
        assert request.path == path
        assert request.query == {
            "page": (str(index),),
            "per_page": ("100",),
            "sort": ("date",),
            "direction": ("asc",),
        }
        assert request.headers["authorization"] == "Bearer test-token"
        assert request.headers["accept"] == "application/vnd.vimeo.*+json;version=3.4"
    assert result.saved_states == [VimeoResumeConfig(next_url=f"https://api.vimeo.com{next_url}")]
    assert result.response is not None
    assert result.response.primary_keys == ["uri"]


@pytest.mark.parametrize("resume", [None, "https://api.vimeo.com/me/videos?page=4&per_page=100"])
def test_resume_and_empty_terminal_page(resume: str | None) -> None:
    result = driver().run(
        "videos",
        [ScriptedResponse(json={"data": [], "paging": {"next": None}})],
        resume_state=VimeoResumeConfig(next_url=resume) if resume else None,
    )

    assert result.rows == []
    assert result.params("page") == (["4"] if resume else ["1"])
    assert len(result.requests) == 1
    assert result.saved_states == []


@pytest.mark.parametrize("status,message", [(401, AUTH_ERROR), (403, PERMISSION_ERROR)])
def test_sync_error_mapping(status: int, message: str) -> None:
    result = driver().run("videos", always(ScriptedResponse(status=status, json={"error": "Access denied"})))

    assert isinstance(result.raised, HTTPError)
    assert any(
        key in str(result.raised) and value == message
        for key, value in VimeoSource().get_non_retryable_errors().items()
    )
    assert len(result.requests) == 1


@pytest.mark.parametrize("resume_url", ["https://example.com/videos?page=2", "http://api.vimeo.com/me/videos?page=2"])
def test_resume_cannot_send_token_to_another_origin(resume_url: str) -> None:
    result = driver().run("videos", [], resume_state=VimeoResumeConfig(next_url=resume_url))

    assert isinstance(result.raised, ValueError)
    assert "Refusing to send request" in str(result.raised)
    assert result.requests == []
