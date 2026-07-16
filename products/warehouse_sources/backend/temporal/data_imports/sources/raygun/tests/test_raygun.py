import json
from typing import Any
from urllib.parse import parse_qs, urlparse

from unittest.mock import MagicMock, patch

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.raygun.raygun import (
    RaygunResumeConfig,
    get_rows,
    raygun_source,
    validate_token,
)

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.raygun.raygun"


def _response(body: Any, status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    resp.headers["Content-Type"] = "application/json"
    return resp


def _offset_of(url: str) -> int | None:
    params = parse_qs(urlparse(url).query)
    return int(params["offset"][0]) if "offset" in params else None


def _path_of(url: str) -> str:
    return urlparse(url).path


class _FakeSession:
    """Session stub returning responses from a URL handler; records requested URLs."""

    def __init__(self, handler) -> None:
        self.handler = handler
        self.urls: list[str] = []
        self.headers: dict[str, str] = {}

    def get(self, url: str, headers: dict[str, str] | None = None, timeout: int | None = None) -> Response:
        self.urls.append(url)
        return self.handler(url)


class TestValidateToken:
    @patch(f"{MODULE}.make_tracked_session")
    def test_status_mapping(self, mock_session: MagicMock) -> None:
        for status, expected in [(200, True), (401, False), (403, False), (500, False)]:
            mock_session.return_value.get.return_value = _response([], status_code=status)
            assert validate_token("tok") == (expected, status)

    @patch(f"{MODULE}.make_tracked_session")
    def test_network_error_returns_none_status(self, mock_session: MagicMock) -> None:
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_token("tok") == (False, None)


class TestTopLevelPagination:
    @patch(f"{MODULE}.PAGE_SIZE", 2)
    @patch(f"{MODULE}.make_tracked_session")
    def test_offset_advances_and_saves_between_pages(self, mock_session: MagicMock) -> None:
        # Two full pages then a short terminal page for /applications.
        pages = {
            0: [{"identifier": "app-1"}, {"identifier": "app-2"}],
            2: [{"identifier": "app-3"}, {"identifier": "app-4"}],
            4: [{"identifier": "app-5"}],
        }

        def handler(url: str) -> Response:
            return _response(pages[_offset_of(url) or 0])

        session = _FakeSession(handler)
        mock_session.return_value = session

        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        yielded = list(get_rows("tok", "applications", MagicMock(), manager))

        assert [_offset_of(u) for u in session.urls] == [0, 2, 4]
        assert sum(len(page) for page in yielded) == 5
        # State is saved pointing at the next unfetched offset after each non-terminal page only.
        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [RaygunResumeConfig(offset=2), RaygunResumeConfig(offset=4)]

    @patch(f"{MODULE}.PAGE_SIZE", 2)
    @patch(f"{MODULE}.make_tracked_session")
    def test_single_short_page_saves_no_state(self, mock_session: MagicMock) -> None:
        session = _FakeSession(lambda url: _response([{"identifier": "app-1"}]))
        mock_session.return_value = session

        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        list(get_rows("tok", "applications", MagicMock(), manager))

        manager.save_state.assert_not_called()

    @patch(f"{MODULE}.PAGE_SIZE", 2)
    @patch(f"{MODULE}.make_tracked_session")
    def test_resume_starts_from_saved_offset(self, mock_session: MagicMock) -> None:
        session = _FakeSession(lambda url: _response([{"identifier": "app-9"}]))
        mock_session.return_value = session

        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = True
        manager.load_state.return_value = RaygunResumeConfig(offset=4)

        list(get_rows("tok", "applications", MagicMock(), manager))

        assert _offset_of(session.urls[0]) == 4


class TestFanOutPagination:
    def _fan_out_handler(self, apps: list[str], child_rows: dict[str, list[dict[str, Any]]]):
        def handler(url: str) -> Response:
            path = _path_of(url)
            offset = _offset_of(url) or 0
            if path.endswith("/applications"):
                # One full page of apps then a terminal empty page.
                return _response([{"identifier": a} for a in apps] if offset == 0 else [])
            for app in apps:
                if f"/applications/{app}/" in path:
                    return _response(child_rows.get(app, []) if offset == 0 else [])
            return _response([])

        return handler

    @patch(f"{MODULE}.PAGE_SIZE", 2)
    @patch(f"{MODULE}.make_tracked_session")
    def test_fans_out_over_apps_and_bookmarks_next_app(self, mock_session: MagicMock) -> None:
        apps = ["app-1", "app-2"]
        child_rows = {
            "app-1": [{"identifier": "eg-1", "applicationIdentifier": "app-1"}],
            "app-2": [{"identifier": "eg-2", "applicationIdentifier": "app-2"}],
        }
        session = _FakeSession(self._fan_out_handler(apps, child_rows))
        mock_session.return_value = session

        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        yielded = list(get_rows("tok", "error_groups", MagicMock(), manager))

        rows = [row for page in yielded for row in page]
        assert {r["applicationIdentifier"] for r in rows} == {"app-1", "app-2"}
        # After finishing app-1 the bookmark advances to app-2 at offset 0.
        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert RaygunResumeConfig(offset=0, application_identifier="app-2") in saved

    @patch(f"{MODULE}.PAGE_SIZE", 2)
    @patch(f"{MODULE}.make_tracked_session")
    def test_resume_skips_to_bookmarked_app_and_offset(self, mock_session: MagicMock) -> None:
        apps = ["app-1", "app-2"]
        child_rows = {"app-2": [{"identifier": "eg-2", "applicationIdentifier": "app-2"}]}
        session = _FakeSession(self._fan_out_handler(apps, child_rows))
        mock_session.return_value = session

        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = True
        manager.load_state.return_value = RaygunResumeConfig(offset=6, application_identifier="app-2")

        list(get_rows("tok", "error_groups", MagicMock(), manager))

        child_urls = [u for u in session.urls if "/applications/app-1/" in u or "/applications/app-2/" in u]
        # app-1 is skipped entirely; the first child fetch targets app-2 at the saved offset.
        assert all("/applications/app-2/" in u for u in child_urls)
        assert _offset_of(child_urls[0]) == 6


class TestRaygunSource:
    def test_primary_keys_and_partitioning_per_endpoint(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)

        applications = raygun_source("tok", "applications", MagicMock(), manager)
        assert applications.primary_keys == ["identifier"]
        assert applications.partition_mode is None

        error_groups = raygun_source("tok", "error_groups", MagicMock(), manager)
        assert error_groups.primary_keys == ["applicationIdentifier", "identifier"]
        assert error_groups.partition_mode == "datetime"
        assert error_groups.partition_keys == ["createdAt"]

        sessions = raygun_source("tok", "sessions", MagicMock(), manager)
        assert sessions.partition_keys == ["startedAt"]

        # A fan-out endpoint without a guaranteed create-time field is left unpartitioned.
        deployments = raygun_source("tok", "deployments", MagicMock(), manager)
        assert deployments.primary_keys == ["applicationIdentifier", "identifier"]
        assert deployments.partition_mode is None
