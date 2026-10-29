import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.vimeo import VimeoSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.vimeo.settings import AUTH_ERROR, PERMISSION_ERROR
from products.warehouse_sources.backend.temporal.data_imports.sources.vimeo.source import VimeoSource


@pytest.mark.parametrize(
    "status,schema,path,expected",
    [
        (200, None, "/me", (True, None)),
        (401, None, "/me", (False, AUTH_ERROR)),
        (403, None, "/me", (True, None)),
        (200, "folders", "/me/projects", (True, None)),
        (401, "folders", "/me/projects", (False, AUTH_ERROR)),
        (403, "folders", "/me/projects", (False, PERMISSION_ERROR)),
        (200, "showcase_videos", "/me/albums", (True, None)),
        (403, "video_comment_replies", "/me/videos", (False, PERMISSION_ERROR)),
    ],
)
def test_credentials_probe(status: int, schema: str | None, path: str, expected: tuple[bool, str | None]) -> None:
    with scripted_network([ScriptedResponse(status=status, json={})]) as network:
        assert (
            VimeoSource().validate_credentials(VimeoSourceConfig(access_token="test-token"), 1, schema_name=schema)
            == expected
        )
    assert len(network.requests_log) == 1
    request = network.requests_log[0]
    assert request.path == path
    assert request.query == ({"per_page": ("1",)} if schema else {"fields": ("uri",)})
    assert request.headers["authorization"] == "Bearer test-token"
    assert request.headers["accept"] == "application/vnd.vimeo.*+json;version=3.4"


def test_service_error_is_not_reported_as_invalid_credentials() -> None:
    with scripted_network(always(ScriptedResponse(status=503, json={}))):
        assert VimeoSource().validate_credentials(VimeoSourceConfig(access_token="test-token"), 1) == (
            False,
            "Couldn't reach Vimeo to check your credentials. Try again in a few minutes.",
        )
