import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.googletagmanager import (
    GoogleTagManagerSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.google_tag_manager import (
    google_tag_manager as gtm,
)

BASE = gtm.GTM_API_BASE


class FakeSession:
    """Maps a request URL to a list of page bodies, served in order per URL."""

    def __init__(self, pages: dict[str, list[dict]]):
        self._pages = {url: list(bodies) for url, bodies in pages.items()}
        self.calls: list[tuple[str, dict]] = []

    def get(self, url: str, params: dict | None = None):
        self.calls.append((url, params or {}))
        body = self._pages[url].pop(0)
        response = mock.Mock()
        response.json.return_value = body
        response.raise_for_status.return_value = None
        return response


def test_paginate_follows_next_page_token():
    session = FakeSession(
        {
            f"{BASE}/accounts/123/containers": [
                {"container": [{"path": "a"}], "nextPageToken": "tok"},
                {"container": [{"path": "b"}]},
            ]
        }
    )

    rows = list(gtm._paginate(session, f"{BASE}/accounts/123/containers", "container"))

    assert [r["path"] for r in rows] == ["a", "b"]
    # Second request must carry the page token returned by the first.
    assert session.calls[1][1].get("pageToken") == "tok"


def test_paginate_empty_response_key():
    session = FakeSession({f"{BASE}/accounts/123/containers": [{}]})

    assert list(gtm._paginate(session, f"{BASE}/accounts/123/containers", "container")) == []


def test_get_account_returns_single_object():
    session = FakeSession({f"{BASE}/accounts/123": [{"path": "accounts/123", "name": "Acme"}]})

    assert gtm.get_account(session, "123") == {"path": "accounts/123", "name": "Acme"}


def test_iter_rows_account_grain_single_object():
    session = FakeSession({f"{BASE}/accounts/123": [{"path": "accounts/123"}]})

    rows = list(gtm._iter_rows(session, "123", "accounts"))

    assert rows == [{"path": "accounts/123"}]


def test_iter_rows_container_grain_fans_out_per_container():
    session = FakeSession(
        {
            f"{BASE}/accounts/123/containers": [
                {"container": [{"path": "accounts/123/containers/1"}, {"path": "accounts/123/containers/2"}]}
            ],
            f"{BASE}/accounts/123/containers/1/version_headers": [
                {"containerVersionHeader": [{"path": "accounts/123/containers/1/versions/10"}]}
            ],
            f"{BASE}/accounts/123/containers/2/version_headers": [
                {"containerVersionHeader": [{"path": "accounts/123/containers/2/versions/20"}]}
            ],
        }
    )

    rows = list(gtm._iter_rows(session, "123", "container_versions"))

    assert {r["path"] for r in rows} == {
        "accounts/123/containers/1/versions/10",
        "accounts/123/containers/2/versions/20",
    }


def test_iter_rows_workspace_grain_fans_out_two_levels():
    session = FakeSession(
        {
            f"{BASE}/accounts/123/containers": [{"container": [{"path": "accounts/123/containers/1"}]}],
            f"{BASE}/accounts/123/containers/1/workspaces": [
                {"workspace": [{"path": "accounts/123/containers/1/workspaces/2"}]}
            ],
            f"{BASE}/accounts/123/containers/1/workspaces/2/tags": [
                {"tag": [{"path": "accounts/123/containers/1/workspaces/2/tags/9", "name": "t"}]}
            ],
        }
    )

    rows = list(gtm._iter_rows(session, "123", "tags"))

    assert [r["path"] for r in rows] == ["accounts/123/containers/1/workspaces/2/tags/9"]


def _config() -> GoogleTagManagerSourceConfig:
    return GoogleTagManagerSourceConfig(account_id="123", google_tag_manager_integration_id=1)


def test_source_response_shape():
    session = FakeSession({f"{BASE}/accounts/123": [{"path": "accounts/123"}]})
    with mock.patch.object(gtm, "google_tag_manager_session", return_value=session):
        response = gtm.google_tag_manager_source(_config(), "accounts", team_id=1)

        assert response.name == "accounts"
        assert response.primary_keys == ["path"]
        # Snapshot tables have no ordering guarantee, so no sort mode is declared.
        assert response.sort_mode is None
        assert list(response.items()) == [[{"path": "accounts/123"}]]


def test_source_unknown_schema_raises():
    with pytest.raises(ValueError):
        gtm.google_tag_manager_source(_config(), "not_a_schema", team_id=1)
