import json
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

from unittest.mock import MagicMock, patch

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.raygun.raygun import (
    RaygunResumeConfig,
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


def _wire_handler(session: MagicMock, handler: Any) -> list[str]:
    """Route a mock session through a URL handler, recording each request's fully-qualified URL.

    ``paginate`` builds a ``requests.Request`` whose ``params`` dict is mutated in place across
    pages, so the paginator's ``offset`` only shows on the URL if we fold params in at prepare time
    (mirroring real ``prepare_request``). Returns the list of URLs actually sent, in order.
    """
    session.headers = {}
    requested: list[str] = []

    def _prepare(request: Any) -> MagicMock:
        params = {key: value for key, value in (request.params or {}).items() if value is not None}
        url = request.url
        if params:
            url = f"{url}?{urlencode(params)}"
        prepared = MagicMock()
        prepared.url = url
        prepared.is_redirect = False
        return prepared

    def _send(prepared: Any, **_kwargs: Any) -> Response:
        requested.append(prepared.url)
        return handler(prepared.url)

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = _send
    return requested


def _rows(source_response: Any) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _make_manager(resume_state: RaygunResumeConfig | None = None) -> MagicMock:
    manager = MagicMock(spec=ResumableSourceManager)
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


class TestValidateToken:
    @patch(f"{MODULE}.make_tracked_session")
    def test_status_mapping(self, mock_session: MagicMock) -> None:
        for status, expected in [(200, True), (401, False), (403, False), (500, False)]:
            mock_session.return_value.get.return_value = _response([], status_code=status)
            assert validate_token("tok") == (expected, status)
        # Response bodies stay out of HTTP sample storage and the token is value-redacted.
        assert mock_session.call_args.kwargs["capture"] is False
        assert "tok" in mock_session.call_args.kwargs["redact_values"]

    @patch(f"{MODULE}.make_tracked_session")
    def test_network_error_returns_none_status(self, mock_session: MagicMock) -> None:
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_token("tok") == (False, None)


class TestTopLevelPagination:
    @patch(f"{MODULE}.PAGE_SIZE", 2)
    @patch(f"{MODULE}.make_tracked_session")
    def test_offset_advances_and_saves_between_pages(self, mock_make_session: MagicMock) -> None:
        # Two full pages then a short terminal page for /applications.
        pages = {
            0: [{"identifier": "app-1"}, {"identifier": "app-2"}],
            2: [{"identifier": "app-3"}, {"identifier": "app-4"}],
            4: [{"identifier": "app-5"}],
        }
        session = mock_make_session.return_value
        requested = _wire_handler(session, lambda url: _response(pages[_offset_of(url) or 0]))

        manager = _make_manager()

        yielded = _rows(raygun_source("tok", "applications", team_id=1, job_id="j", resumable_source_manager=manager))

        assert [_offset_of(u) for u in requested] == [0, 2, 4]
        assert len(yielded) == 5
        # Sync sessions carry PII-bearing bodies, so sample capture must stay off.
        assert mock_make_session.call_args.kwargs["capture"] is False
        assert "tok" in mock_make_session.call_args.kwargs["redact_values"]
        # State is saved pointing at the next unfetched offset after each non-terminal page only.
        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [RaygunResumeConfig(offset=2), RaygunResumeConfig(offset=4)]

    @patch(f"{MODULE}.PAGE_SIZE", 2)
    @patch(f"{MODULE}.make_tracked_session")
    def test_single_short_page_saves_no_state(self, mock_make_session: MagicMock) -> None:
        session = mock_make_session.return_value
        _wire_handler(session, lambda url: _response([{"identifier": "app-1"}]))

        manager = _make_manager()

        _rows(raygun_source("tok", "applications", team_id=1, job_id="j", resumable_source_manager=manager))

        manager.save_state.assert_not_called()

    @patch(f"{MODULE}.PAGE_SIZE", 2)
    @patch(f"{MODULE}.make_tracked_session")
    def test_application_api_key_is_stripped(self, mock_make_session: MagicMock) -> None:
        # `apiKey` is an ingestion credential and must never reach the warehouse table.
        session = mock_make_session.return_value
        _wire_handler(session, lambda url: _response([{"identifier": "app-1", "name": "App", "apiKey": "secret"}]))

        manager = _make_manager()

        rows = _rows(raygun_source("tok", "applications", team_id=1, job_id="j", resumable_source_manager=manager))

        assert rows == [{"identifier": "app-1", "name": "App"}]

    @patch(f"{MODULE}.PAGE_SIZE", 2)
    @patch(f"{MODULE}.make_tracked_session")
    def test_resume_starts_from_saved_offset(self, mock_make_session: MagicMock) -> None:
        session = mock_make_session.return_value
        requested = _wire_handler(session, lambda url: _response([{"identifier": "app-9"}]))

        manager = _make_manager(RaygunResumeConfig(offset=4))

        _rows(raygun_source("tok", "applications", team_id=1, job_id="j", resumable_source_manager=manager))

        assert _offset_of(requested[0]) == 4


class TestFanOutPagination:
    def _fan_out_handler(self, apps: list[str], child_rows: dict[str, list[dict[str, Any]]]) -> Any:
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
    def test_fans_out_over_apps_and_marks_finished_app_complete(self, mock_make_session: MagicMock) -> None:
        apps = ["app-1", "app-2"]
        child_rows = {
            "app-1": [{"identifier": "eg-1", "applicationIdentifier": "app-1"}],
            "app-2": [{"identifier": "eg-2", "applicationIdentifier": "app-2"}],
        }
        session = mock_make_session.return_value
        _wire_handler(session, self._fan_out_handler(apps, child_rows))

        manager = _make_manager()

        rows = _rows(raygun_source("tok", "error_groups", team_id=1, job_id="j", resumable_source_manager=manager))

        assert {r["applicationIdentifier"] for r in rows} == {"app-1", "app-2"}
        # After finishing app-1 its child path is checkpointed as completed so a restart skips it
        # (the fan-out equivalent of the old per-application bookmark advancing to the next app).
        completed = [
            call.args[0].fanout_state.get("completed")
            for call in manager.save_state.call_args_list
            if call.args[0].fanout_state
        ]
        assert any("/applications/app-1/error-groups" in (c or []) for c in completed)

    @patch(f"{MODULE}.PAGE_SIZE", 2)
    @patch(f"{MODULE}.make_tracked_session")
    def test_resume_skips_completed_app_and_starts_bookmarked_app_at_offset(self, mock_make_session: MagicMock) -> None:
        apps = ["app-1", "app-2"]
        child_rows = {"app-2": [{"identifier": "eg-2", "applicationIdentifier": "app-2"}]}
        session = mock_make_session.return_value
        requested = _wire_handler(session, self._fan_out_handler(apps, child_rows))

        manager = _make_manager(
            RaygunResumeConfig(
                fanout_state={
                    "completed": ["/applications/app-1/error-groups"],
                    "current": "/applications/app-2/error-groups",
                    "child_state": {"offset": 6},
                }
            )
        )

        _rows(raygun_source("tok", "error_groups", team_id=1, job_id="j", resumable_source_manager=manager))

        child_urls = [u for u in requested if "/applications/app-1/" in u or "/applications/app-2/" in u]
        # app-1 is skipped entirely; the first child fetch targets app-2 at the saved offset.
        assert all("/applications/app-2/" in u for u in child_urls)
        assert _offset_of(child_urls[0]) == 6


class TestRaygunSource:
    @patch(f"{MODULE}.make_tracked_session")
    def test_primary_keys_and_partitioning_per_endpoint(self, _mock_make_session: MagicMock) -> None:
        manager = _make_manager()

        applications = raygun_source("tok", "applications", team_id=1, job_id="j", resumable_source_manager=manager)
        assert applications.primary_keys == ["identifier"]
        assert applications.partition_mode is None

        error_groups = raygun_source("tok", "error_groups", team_id=1, job_id="j", resumable_source_manager=manager)
        assert error_groups.primary_keys == ["applicationIdentifier", "identifier"]
        assert error_groups.partition_mode == "datetime"
        assert error_groups.partition_keys == ["createdAt"]

        sessions = raygun_source("tok", "sessions", team_id=1, job_id="j", resumable_source_manager=manager)
        assert sessions.partition_keys == ["startedAt"]

        # A fan-out endpoint without a guaranteed create-time field is left unpartitioned.
        deployments = raygun_source("tok", "deployments", team_id=1, job_id="j", resumable_source_manager=manager)
        assert deployments.primary_keys == ["applicationIdentifier", "identifier"]
        assert deployments.partition_mode is None
