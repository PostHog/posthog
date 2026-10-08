from datetime import UTC, datetime
from typing import Any, Optional, Union

import pytest
from unittest import mock

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.sharepoint.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.sharepoint.settings import (
    ENDPOINTS,
    GRAPH_BASE_URL,
    SHAREPOINT_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.sharepoint.sharepoint import (
    INVALID_SITE_URL_ERROR,
    SITES_DENIED_ERROR,
    SharePointResumeConfig,
    SharePointSiteURLError,
    _get_rows,
    parse_site_urls,
    validate_credentials,
)

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.sharepoint.sharepoint"

TENANT_ID = "11111111-1111-1111-1111-111111111111"
CLIENT_ID = "22222222-2222-2222-2222-222222222222"
CLIENT_SECRET = "super-secret"

SITE_A = "contoso.sharepoint.com,aaaa,1111"
SITE_B = "contoso.sharepoint.com,bbbb,2222"

Route = Union[dict[str, Any], int]


def _response(status: int = 200, json_body: Any = None) -> mock.MagicMock:
    response = mock.MagicMock(spec=requests.Response)
    response.status_code = status
    response.ok = 200 <= status < 300
    response.text = ""
    response.json.return_value = json_body if json_body is not None else {}
    if not response.ok:
        response.raise_for_status.side_effect = requests.HTTPError(f"{status} Client Error", response=response)
    else:
        response.raise_for_status.return_value = None
    return response


def _token_response() -> mock.MagicMock:
    return _response(200, {"access_token": "token-1", "expires_in": 3599})


def _session(routes: dict[str, Route], post_responses: Optional[list[mock.MagicMock]] = None) -> Any:
    session = mock.MagicMock(spec=requests.Session)

    def _get(url: str, **kwargs: Any) -> mock.MagicMock:
        route = routes[url]
        if isinstance(route, int):
            return _response(route)
        return _response(200, route)

    session.get.side_effect = _get
    session.post.side_effect = post_responses if post_responses is not None else [_token_response()]
    return session


def _manager(resume_state: Optional[SharePointResumeConfig] = None) -> Any:
    manager = mock.MagicMock(spec=ResumableSourceManager)
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _rows(
    endpoint: str, session: Any, manager: Optional[Any] = None, site_urls: Optional[str] = None
) -> list[dict[str, Any]]:
    with mock.patch(f"{MODULE}.make_tracked_session", return_value=session):
        pages = list(
            _get_rows(
                tenant_id=TENANT_ID,
                client_id=CLIENT_ID,
                client_secret=CLIENT_SECRET,
                site_urls=site_urls,
                endpoint=endpoint,
                logger=mock.MagicMock(),
                resumable_source_manager=manager if manager is not None else _manager(),
            )
        )
    return [row for page in pages for row in page]


def _g(path: str) -> str:
    return f"{GRAPH_BASE_URL}{path}"


ALL_SITES_ROUTES: dict[str, Route] = {
    _g("/sites/getAllSites"): {
        "value": [
            {"id": SITE_A, "webUrl": "https://contoso.sharepoint.com/sites/a", "isPersonalSite": False},
            {"id": "personal-1", "webUrl": "https://contoso-my.sharepoint.com/personal/x", "isPersonalSite": True},
        ],
        "@odata.nextLink": _g("/sites/getAllSites?$skiptoken=page2"),
    },
    _g("/sites/getAllSites?$skiptoken=page2"): {
        "value": [
            # Older tenants can omit `isPersonalSite`, so the -my host alone must exclude OneDrive.
            {"id": "personal-2", "webUrl": "https://contoso-my.sharepoint.com/personal/y"},
            {"id": SITE_B, "webUrl": "https://contoso.sharepoint.com/sites/b"},
        ],
    },
}


class TestParseSiteUrls:
    @parameterized.expand(
        [
            ("empty", None, []),
            ("blank_lines", "\n  \n", []),
            ("root_site", "https://contoso.sharepoint.com", ["/sites/contoso.sharepoint.com"]),
            (
                "site_path_with_trailing_slash",
                "https://contoso.sharepoint.com/sites/marketing/",
                ["/sites/contoso.sharepoint.com:/sites/marketing:"],
            ),
            (
                "space_in_path_is_encoded",
                "https://contoso.sharepoint.com/sites/Sales Team",
                ["/sites/contoso.sharepoint.com:/sites/Sales%20Team:"],
            ),
            (
                "newline_and_comma_separated",
                "https://contoso.sharepoint.com/sites/a\nhttps://contoso.sharepoint.com/sites/b, https://contoso.sharepoint.com",
                [
                    "/sites/contoso.sharepoint.com:/sites/a:",
                    "/sites/contoso.sharepoint.com:/sites/b:",
                    "/sites/contoso.sharepoint.com",
                ],
            ),
        ]
    )
    def test_builds_graph_site_paths(self, _name: str, raw: Optional[str], expected: list[str]) -> None:
        assert parse_site_urls(raw) == expected

    @parameterized.expand([("http", "http://contoso.sharepoint.com/sites/a"), ("no_scheme", "contoso.sharepoint.com")])
    def test_rejects_non_https_urls(self, _name: str, raw: str) -> None:
        with pytest.raises(SharePointSiteURLError, match=INVALID_SITE_URL_ERROR):
            parse_site_urls(raw)


class TestSharePointRows:
    @pytest.mark.parametrize("endpoint", ["sites", "drives"])
    def test_explicit_personal_site_is_skipped(self, endpoint: str) -> None:
        site_url = "https://contoso-my.sharepoint.com/personal/user"
        routes: dict[str, Route] = {
            _g("/sites/contoso-my.sharepoint.com:/personal/user:"): {
                "id": "personal-1",
                "webUrl": site_url,
                "isPersonalSite": True,
            }
        }

        assert _rows(endpoint, _session(routes), site_urls=site_url) == []

    def test_next_link_outside_graph_is_refused(self) -> None:
        routes: dict[str, Route] = {
            _g("/sites/getAllSites"): {"value": [{"id": SITE_A}], "@odata.nextLink": "https://evil.example.com/next"}
        }

        with pytest.raises(ValueError, match="non-Graph URL"):
            _rows("sites", _session(routes))

    def test_list_items_skip_hidden_lists_and_carry_parent_ids(self) -> None:
        routes: dict[str, Route] = {
            _g(f"/sites/contoso.sharepoint.com:/sites/a:"): {"id": SITE_A},
            _g(f"/sites/{SITE_A}/lists"): {
                "value": [
                    {"id": "list-1", "list": {"hidden": False}},
                    {"id": "hidden-list", "list": {"hidden": True}},
                    {"id": "deleted-list"},
                ]
            },
            _g(f"/sites/{SITE_A}/lists/list-1/items"): {
                "value": [{"id": "1", "createdDateTime": "2026-01-02T03:04:05Z", "fields": {"Title": "Widget"}}],
            },
            _g(f"/sites/{SITE_A}/lists/deleted-list/items"): 404,
        }
        session = _session(routes)

        rows = _rows("list_items", session, site_urls="https://contoso.sharepoint.com/sites/a")

        assert rows == [
            {
                "id": "1",
                "createdDateTime": datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
                "fields": {"Title": "Widget"},
                "site_id": SITE_A,
                "list_id": "list-1",
            }
        ]
        item_calls = [c for c in session.get.call_args_list if c.args[0].endswith("/list-1/items")]
        assert item_calls[0].kwargs["params"] == {"expand": "fields"}
        assert all("hidden-list" not in c.args[0] for c in session.get.call_args_list)

    def test_drive_items_drop_deleted_and_repeated_items(self) -> None:
        routes: dict[str, Route] = {
            **ALL_SITES_ROUTES,
            _g(f"/sites/{SITE_A}/drives"): {"value": [{"id": "b!drive-a"}]},
            _g(f"/sites/{SITE_B}/drives"): {"value": []},
            _g("/drives/b!drive-a/root/delta"): {
                "value": [
                    {"id": "root", "root": {}},
                    {"id": "f1", "file": {}, "@microsoft.graph.downloadUrl": "https://temporary.example.com/file"},
                    {"id": "gone", "deleted": {}},
                ],
                "@odata.nextLink": _g("/drives/b!drive-a/root/delta?token=2"),
            },
            _g("/drives/b!drive-a/root/delta?token=2"): {"value": [{"id": "f1", "file": {}}, {"id": "f2", "file": {}}]},
        }

        rows = _rows("drive_items", _session(routes))

        assert [(row["drive_id"], row["id"]) for row in rows] == [
            ("b!drive-a", "root"),
            ("b!drive-a", "f1"),
            ("b!drive-a", "f2"),
        ]
        assert all(row["site_id"] == SITE_A for row in rows)
        assert all("@microsoft.graph.downloadUrl" not in row for row in rows)

    def test_expired_token_is_reminted_once(self) -> None:
        session = _session({}, post_responses=[_token_response(), _token_response()])
        session.get.side_effect = [_response(401), _response(200, {"value": [{"id": SITE_A}]})]

        rows = _rows("sites", session)

        assert [row["id"] for row in rows] == [SITE_A]
        assert session.post.call_count == 2


class TestSharePointResume:
    def test_resume_on_a_site_that_is_gone_restarts_from_the_first_site(self) -> None:
        routes: dict[str, Route] = {
            **ALL_SITES_ROUTES,
            _g(f"/sites/{SITE_A}/lists"): {"value": [{"id": "list-a"}]},
            _g(f"/sites/{SITE_B}/lists"): {"value": [{"id": "list-b"}]},
        }
        manager = _manager(SharePointResumeConfig(site_id="deleted-site", next_url=_g("/stale")))

        rows = _rows("lists", _session(routes), manager=manager)

        assert [(row["site_id"], row["id"]) for row in rows] == [(SITE_A, "list-a"), (SITE_B, "list-b")]


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("token_rejected", 401, None, None, "Entra ID rejected the app registration"),
            ("token_bad_request", 400, None, None, "Entra ID rejected the app registration"),
            ("graph_forbidden", 200, 403, None, SITES_DENIED_ERROR),
            ("site_not_found", 200, 404, "https://contoso.sharepoint.com/sites/a", "couldn't find the site"),
            ("ok", 200, 200, None, None),
        ]
    )
    def test_maps_status_to_message(
        self,
        _name: str,
        token_status: int,
        graph_status: Optional[int],
        site_urls: Optional[str],
        expected_error: Optional[str],
    ) -> None:
        token = _token_response() if token_status == 200 else _response(token_status)
        session = _session({}, post_responses=[token])
        session.get.side_effect = [_response(graph_status or 200, {"value": []})]

        with mock.patch(f"{MODULE}.make_tracked_session", return_value=session):
            ok, error = validate_credentials(TENANT_ID, CLIENT_ID, CLIENT_SECRET, site_urls)

        assert ok is (expected_error is None)
        if expected_error is None:
            assert error is None
        else:
            assert error is not None and expected_error in error

    def test_invalid_site_url_fails_before_any_request(self) -> None:
        session = _session({})

        with mock.patch(f"{MODULE}.make_tracked_session", return_value=session):
            ok, error = validate_credentials(TENANT_ID, CLIENT_ID, CLIENT_SECRET, "contoso.sharepoint.com/sites/a")

        assert not ok
        assert error is not None and error.startswith(INVALID_SITE_URL_ERROR)
        session.post.assert_not_called()


def test_canonical_descriptions_document_every_primary_key() -> None:
    assert set(CANONICAL_DESCRIPTIONS) == set(ENDPOINTS)
    for name, entry in CANONICAL_DESCRIPTIONS.items():
        assert set(SHAREPOINT_ENDPOINTS[name].primary_keys) <= set(entry["columns"])
