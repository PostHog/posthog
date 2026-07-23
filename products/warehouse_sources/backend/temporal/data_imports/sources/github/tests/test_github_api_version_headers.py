from collections.abc import Callable
from typing import Any

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.github import (
    GithubAuthMethodConfig,
    GithubSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.github import github
from products.warehouse_sources.backend.temporal.data_imports.sources.github.source import GithubSource

_CONFIG = GithubSourceConfig(
    auth_method=GithubAuthMethodConfig(github_integration_id=None, selection="pat", personal_access_token="t"),
    repository="acme/widgets",
    repositories=None,
)
_TEAM_ID = 123
_WEBHOOK_URL = "https://ph.example/webhook"


def _response() -> mock.Mock:
    response = mock.Mock(status_code=200, ok=True, headers={}, text="[]")
    response.json.return_value = []
    return response


def _run(surface: Callable[[GithubSource, str | None], object], api_version: str | None) -> list[dict[str, str]]:
    """Drive one non-sync surface and return the headers of every outgoing GitHub request."""
    headers: list[dict[str, str]] = []

    def record(*args: Any, **kwargs: Any) -> mock.Mock:
        headers.append(kwargs["headers"])
        return _response()

    session = mock.Mock()
    session.get.side_effect = record
    session.post.side_effect = record
    session.delete.side_effect = record
    with mock.patch.object(github, "make_tracked_session", return_value=session):
        with mock.patch.object(github, "github_request", side_effect=record):
            surface(GithubSource(), api_version)
    assert headers, "surface made no GitHub request"
    return headers


_SURFACES: dict[str, Callable[[GithubSource, str | None], object]] = {
    "validate_credentials": lambda source, version: source.validate_credentials(_CONFIG, _TEAM_ID, api_version=version),
    "get_endpoint_permissions": lambda source, version: source.get_endpoint_permissions(
        _CONFIG, _TEAM_ID, ["teams"], api_version=version
    ),
    "create_webhook": lambda source, version: source.create_webhook(
        _CONFIG, _WEBHOOK_URL, _TEAM_ID, api_version=version
    ),
    "sync_webhook_events": lambda source, version: source.sync_webhook_events(
        _CONFIG, _WEBHOOK_URL, _TEAM_ID, ["workflow_runs"], api_version=version
    ),
    "delete_webhook": lambda source, version: source.delete_webhook(
        _CONFIG, _WEBHOOK_URL, _TEAM_ID, api_version=version
    ),
    "get_external_webhook_info": lambda source, version: source.get_external_webhook_info(
        _CONFIG, _WEBHOOK_URL, _TEAM_ID, api_version=version
    ),
}


@pytest.mark.parametrize("surface", list(_SURFACES))
@pytest.mark.parametrize(
    "api_version,expected_header",
    [
        ("2022-11-28", "2022-11-28"),
        ("2026-03-10", "2026-03-10"),
        # No pin (pre-creation) resolves to the source's default_version, not the module constant.
        (None, "2026-03-10"),
    ],
)
def test_non_sync_surfaces_send_resolved_api_version(
    surface: str, api_version: str | None, expected_header: str
) -> None:
    for headers in _run(_SURFACES[surface], api_version):
        assert headers["X-GitHub-Api-Version"] == expected_header
