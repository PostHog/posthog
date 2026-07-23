import json
import base64
from datetime import UTC, date, datetime
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from unittest import mock

import requests
from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.teamwork.settings import TEAMWORK_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.teamwork.teamwork import (
    MAX_PAGES,
    PAGE_SIZE,
    TeamworkResumeConfig,
    _format_updated_after,
    base_url,
    normalize_host,
    teamwork_source,
    validate_credentials,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the teamwork module.
TEAMWORK_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.teamwork.teamwork.make_tracked_session"
)


def _page(data_key: str, items: list[dict[str, Any]], *, has_more: bool, status: int = 200) -> Response:
    resp = Response()
    resp.status_code = status
    resp._content = json.dumps({data_key: items, "meta": {"page": {"hasMore": has_more}}}).encode()
    return resp


def _redirect(status: int = 301) -> Response:
    resp = Response()
    resp.status_code = status
    resp.headers["Location"] = "https://attacker.example.com/"
    resp._content = b""
    return resp


def _make_manager(resume_state: TeamworkResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


class _Capture:
    def __init__(self) -> None:
        self.query_params: list[dict[str, Any]] = []
        self.auth_headers: list[str | None] = []
        self.urls: list[str] = []


def _wire(session: mock.MagicMock, responses: list[Response]) -> _Capture:
    """Wire a mock client session, running requests through a REAL ``prepare_request`` so framework
    auth is genuinely applied and the final query string is captured per page.

    ``request.params`` is a single dict mutated in place across pages, so snapshot the prepared URL's
    query at send time rather than inspecting the shared dict after the run.
    """
    session.headers = {}
    capture = _Capture()
    real_session = requests.Session()

    def _prepare(request: Any) -> Any:
        prepared = real_session.prepare_request(request)
        capture.urls.append(prepared.url or "")
        query = parse_qs(urlsplit(prepared.url or "").query)
        capture.query_params.append({k: v[0] for k, v in query.items()})
        capture.auth_headers.append(prepared.headers.get("Authorization"))
        return prepared

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return capture


def _rows(source_response: Any) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _run(
    session: mock.MagicMock,
    responses: list[Response],
    *,
    endpoint: str = "tasks",
    manager: mock.MagicMock | None = None,
    **kwargs: Any,
) -> tuple[list[dict[str, Any]], _Capture, mock.MagicMock]:
    capture = _wire(session, responses)
    manager = manager or _make_manager()
    rows = _rows(
        teamwork_source(
            host="mycompany.teamwork.com",
            api_key="key",
            endpoint=endpoint,
            team_id=1,
            job_id="j",
            resumable_source_manager=manager,
            **kwargs,
        )
    )
    return rows, capture, manager


class TestNormalizeHost:
    @parameterized.expand(
        [
            ("bare_subdomain", "mycompany", "mycompany.teamwork.com"),
            ("full_host", "mycompany.teamwork.com", "mycompany.teamwork.com"),
            ("https_url", "https://mycompany.teamwork.com/", "mycompany.teamwork.com"),
            ("http_url_with_path", "http://mycompany.teamwork.com/projects", "mycompany.teamwork.com"),
            ("regional_host", "mycompany.eu.teamwork.com", "mycompany.eu.teamwork.com"),
            ("trims_whitespace_and_case", "  MyCompany  ", "mycompany.teamwork.com"),
            ("trailing_dot", "mycompany.teamwork.com.", "mycompany.teamwork.com"),
        ]
    )
    def test_normalize_host(self, _name: str, raw: str, expected: str) -> None:
        assert normalize_host(raw) == expected

    def test_base_url(self) -> None:
        assert base_url("mycompany.teamwork.com") == "https://mycompany.teamwork.com/projects/api/v3"


class TestFormatUpdatedAfter:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14Z"),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14Z"),
            ("date_value", date(2026, 3, 4), "2026-03-04T00:00:00Z"),
            ("string_passthrough", "2026-03-04T02:58:14Z", "2026-03-04T02:58:14Z"),
        ]
    )
    def test_format_updated_after(self, _name: str, value: object, expected: str) -> None:
        assert _format_updated_after(value) == expected

    def test_no_offset_suffix(self) -> None:
        assert "+00:00" not in _format_updated_after(datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC))


class TestAuth:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_uses_basic_auth_with_api_key_as_username(self, MockSession: mock.MagicMock) -> None:
        # Teamwork Basic auth: API key is the username, any value is the password.
        session = MockSession.return_value
        _, capture, _ = _run(session, [_page("tasks", [{"id": 1}], has_more=False)])
        scheme, token = (capture.auth_headers[0] or "").split(" ", 1)
        assert scheme == "Basic"
        assert base64.b64decode(token).decode() == "key:x"


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_single_page(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        rows, capture, _ = _run(session, [_page("tasks", [{"id": 1}, {"id": 2}], has_more=False)])
        assert rows == [{"id": 1}, {"id": 2}]
        assert session.send.call_count == 1
        assert capture.query_params[0]["page"] == "1"
        assert capture.query_params[0]["pageSize"] == str(PAGE_SIZE)
        assert capture.query_params[0]["orderMode"] == "asc"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_follows_pagination_until_has_more_false(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        responses = [
            _page("tasks", [{"id": 1}], has_more=True),
            _page("tasks", [{"id": 2}], has_more=True),
            _page("tasks", [{"id": 3}], has_more=False),
        ]
        rows, capture, _ = _run(session, responses)
        assert rows == [{"id": 1}, {"id": 2}, {"id": 3}]
        assert [q["page"] for q in capture.query_params] == ["1", "2", "3"]
        # hasMore=false on the last (non-empty) page stops without an extra empty-page request.
        assert session.send.call_count == 3

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_stops_on_empty_page(self, MockSession: mock.MagicMock) -> None:
        # hasMore lies and says there's more, but an empty page must terminate the loop.
        session = MockSession.return_value
        rows, capture, _ = _run(session, [_page("tasks", [], has_more=True)])
        assert rows == []
        assert session.send.call_count == 1

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_saves_checkpoint_after_each_yielded_page(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        responses = [
            _page("tasks", [{"id": 1}], has_more=True),
            _page("tasks", [{"id": 2}], has_more=False),
        ]
        _, _, manager = _run(session, responses)
        # Checkpoint points at the NEXT page to fetch; the final (hasMore=false) page saves nothing.
        assert manager.save_state.call_count == 1
        assert manager.save_state.call_args.args[0] == TeamworkResumeConfig(page=2, updated_after=None)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_page(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        manager = _make_manager(TeamworkResumeConfig(page=3, updated_after="2026-01-01T00:00:00Z"))
        rows, capture, _ = _run(session, [_page("tasks", [{"id": 7}], has_more=False)], manager=manager)
        assert rows == [{"id": 7}]
        assert capture.query_params[0]["page"] == "3"
        # A resumed run rebuilds the SAME window it started with (the pinned cursor), not a fresh one.
        assert capture.query_params[0]["updatedAfter"] == "2026-01-01T00:00:00Z"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_builds_updated_after_from_last_value(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        _, capture, _ = _run(
            session,
            [_page("tasks", [{"id": 1}], has_more=False)],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
        )
        assert capture.query_params[0]["updatedAfter"] == "2026-03-04T02:58:14Z"
        assert capture.query_params[0]["orderBy"] == "updatedat"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_full_refresh_endpoint_never_sends_updated_after(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        _, capture, _ = _run(
            session,
            [_page("projects", [{"id": 1}], has_more=False)],
            endpoint="projects",
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
        )
        assert "updatedAfter" not in capture.query_params[0]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_reads_endpoint_specific_data_key(self, MockSession: mock.MagicMock) -> None:
        # `time.json` returns rows under "timelogs", not "time".
        session = MockSession.return_value
        rows, _, _ = _run(session, [_page("timelogs", [{"id": 99}], has_more=False)], endpoint="timelogs")
        assert rows == [{"id": 99}]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_stops_at_page_cap(self, MockSession: mock.MagicMock) -> None:
        # Every page claims hasMore=True forever; the MAX_PAGES cap must break the loop.
        session = MockSession.return_value
        session.headers = {}
        real_session = requests.Session()
        session.prepare_request.side_effect = lambda request: real_session.prepare_request(request)
        session.send.side_effect = lambda *a, **k: _page("tasks", [{"id": 1}], has_more=True)

        rows = _rows(
            teamwork_source(
                host="mycompany.teamwork.com",
                api_key="key",
                endpoint="tasks",
                team_id=1,
                job_id="j",
                resumable_source_manager=_make_manager(),
            )
        )
        assert len(rows) == MAX_PAGES


class TestRedirectRejection:
    @parameterized.expand([("moved", 301), ("found", 302), ("temporary", 307), ("permanent", 308)])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_redirect_is_rejected(self, _name: str, status: int, MockSession: mock.MagicMock) -> None:
        # A 3xx means the host tried to bounce us elsewhere — refuse rather than forward credentials.
        session = MockSession.return_value
        with pytest.raises(ValueError, match="redirect"):
            _run(session, [_redirect(status)])


class TestValidateCredentials:
    @parameterized.expand([("ok", 200, True), ("unauthorized", 401, False), ("forbidden", 403, False)])
    @mock.patch(TEAMWORK_SESSION_PATCH)
    def test_status_mapping(self, _name: str, status_code: int, expected: bool, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status_code)
        assert validate_credentials("mycompany.teamwork.com", "key") is expected

    @mock.patch(TEAMWORK_SESSION_PATCH)
    def test_network_error_is_false(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.side_effect = requests.ConnectionError("boom")
        assert validate_credentials("mycompany.teamwork.com", "key") is False

    @mock.patch(TEAMWORK_SESSION_PATCH)
    def test_uses_no_redirect_session(self, mock_session: mock.MagicMock) -> None:
        # The Basic auth header must never follow a redirect off the validated host.
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=200)
        validate_credentials("mycompany.teamwork.com", "key")
        assert mock_session.call_args.kwargs["allow_redirects"] is False

    @mock.patch(TEAMWORK_SESSION_PATCH)
    def test_probes_me_endpoint(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=200)
        validate_credentials("mycompany.teamwork.com", "key")
        assert mock_session.return_value.get.call_args.args[0] == (
            "https://mycompany.teamwork.com/projects/api/v3/me.json"
        )


class TestEndpointCatalog:
    def test_every_endpoint_has_id_primary_key(self) -> None:
        for config in TEAMWORK_ENDPOINTS.values():
            assert config.primary_keys == ["id"]

    def test_partition_keys_are_creation_fields_not_update_fields(self) -> None:
        # An update-timestamp partition key would rewrite partitions every sync.
        for config in TEAMWORK_ENDPOINTS.values():
            if config.partition_key is not None:
                assert "updated" not in config.partition_key.lower()
                assert "edited" not in config.partition_key.lower()

    def test_incremental_endpoints_sort_by_an_update_field(self) -> None:
        # If we filter by updatedAfter we must also sort by the update field, or sort_mode="asc" lies.
        for config in TEAMWORK_ENDPOINTS.values():
            if config.incremental_field is not None:
                assert config.order_by is not None
                assert "updated" in config.order_by.lower()

    @parameterized.expand(
        [
            ("projects", "projects", "/projects.json"),
            ("tasks", "tasks", "/tasks.json"),
            ("tasklists", "tasklists", "/tasklists.json"),
            ("milestones", "milestones", "/milestones.json"),
            ("timelogs", "timelogs", "/time.json"),
            ("people", "people", "/people.json"),
            ("companies", "companies", "/companies.json"),
            ("tags", "tags", "/tags.json"),
            ("comments", "comments", "/comments.json"),
        ]
    )
    def test_endpoint_paths_and_keys(self, name: str, data_key: str, path: str) -> None:
        config = TEAMWORK_ENDPOINTS[name]
        assert config.data_key == data_key
        assert config.path == path


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
