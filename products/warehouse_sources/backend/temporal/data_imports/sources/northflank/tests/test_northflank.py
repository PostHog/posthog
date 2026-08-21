from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.northflank.northflank import (
    MAX_PROJECT_PAGES,
    NorthflankRetryableError,
    _build_url,
    _extract_rows,
    _next_cursor,
    _rate_limit_sleep_seconds,
    get_rows,
    northflank_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.northflank.settings import (
    ENDPOINTS,
    NORTHFLANK_ENDPOINTS,
)

PATCH_SESSION = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.northflank.northflank.make_tracked_session"
)


def _response(body: dict[str, Any], status_code: int = 200, headers: dict[str, str] | None = None) -> mock.MagicMock:
    response = mock.MagicMock()
    response.status_code = status_code
    response.ok = status_code < 400
    response.headers = headers or {}
    response.json.return_value = body
    return response


def _page(data_key: str, items: list[dict[str, Any]], cursor: str | None) -> dict[str, Any]:
    return {"data": {data_key: items}, "pagination": {"hasNextPage": cursor is not None, "cursor": cursor}}


def _route_session(mock_session: mock.MagicMock, routes: dict[str, list[dict[str, Any]] | dict[str, Any]]) -> None:
    """Route GET calls by path; values are either a body dict or a list of bodies consumed in order."""
    state: dict[str, int] = {}

    def get(url: str, **kwargs: Any) -> mock.MagicMock:
        path = urlparse(url).path
        body = routes[path]
        if isinstance(body, list):
            index = min(state.get(path, 0), len(body) - 1)
            state[path] = index + 1
            return _response(body[index])
        return _response(body)

    mock_session.return_value.get.side_effect = get


def _requested_urls(mock_session: mock.MagicMock) -> list[str]:
    return [call.args[0] for call in mock_session.return_value.get.call_args_list]


class TestBuildUrl:
    def test_no_params(self):
        assert _build_url("/v1/projects") == "https://api.northflank.com/v1/projects"

    def test_drops_none_values_and_encodes(self):
        url = _build_url("/v1/projects", {"per_page": 100, "cursor": None})
        assert url == "https://api.northflank.com/v1/projects?per_page=100"


class TestExtractRows:
    @parameterized.expand(
        [
            ("nested_under_data_key", {"data": {"projects": [{"id": "p1"}]}}, "projects", [{"id": "p1"}]),
            ("data_is_the_array", {"data": [{"id": "v1"}]}, "volumes", [{"id": "v1"}]),
            ("missing_key", {"data": {"other": []}}, "projects", []),
            ("empty_body", {}, "projects", []),
        ]
    )
    def test_extract_rows(self, _name, body, data_key, expected):
        assert _extract_rows(body, data_key) == expected


class TestNextCursor:
    @parameterized.expand(
        [
            ({"pagination": {"hasNextPage": True, "cursor": "abc"}}, "abc"),
            ({"pagination": {"hasNextPage": False, "cursor": "abc"}}, None),
            ({"pagination": {"hasNextPage": True}}, None),
            ({}, None),
        ]
    )
    def test_next_cursor(self, body, expected):
        assert _next_cursor(body) == expected


class TestRateLimitSleep:
    @parameterized.expand(
        [
            ({"retry-after": "5"}, 5),
            ({"x-ratelimit-reset": "30"}, 30),
            ({"retry-after": "9999"}, 120),
            ({"retry-after": "-3"}, 0),
            ({"retry-after": "nope"}, 0),
            ({}, 0),
        ]
    )
    def test_sleep_seconds_from_headers(self, headers, expected):
        response = mock.MagicMock()
        response.headers = headers
        assert _rate_limit_sleep_seconds(response) == expected


class TestValidateCredentials:
    @parameterized.expand([(200, True), (401, False), (403, False), (500, False)])
    @mock.patch(PATCH_SESSION)
    def test_status_mapping(self, status, expected, mock_session):
        mock_session.return_value.get.return_value = _response({}, status_code=status)

        is_valid, error = validate_credentials("token")

        assert is_valid is expected
        assert (error is None) is expected

    @mock.patch(PATCH_SESSION)
    def test_connection_error_is_not_valid(self, mock_session):
        mock_session.return_value.get.side_effect = Exception("boom")

        is_valid, error = validate_credentials("token")

        assert is_valid is False
        assert error is not None

    @mock.patch(PATCH_SESSION)
    def test_sends_bearer_header(self, mock_session):
        mock_session.return_value.get.return_value = _response({}, status_code=200)

        validate_credentials("token")

        headers = mock_session.return_value.get.call_args.kwargs["headers"]
        assert headers["Authorization"] == "Bearer token"


class TestProjectsPagination:
    @mock.patch(PATCH_SESSION)
    def test_paginates_via_cursor(self, mock_session):
        _route_session(
            mock_session,
            {
                "/v1/projects": [
                    _page("projects", [{"id": "p1"}, {"id": "p2"}], "cursor-2"),
                    _page("projects", [{"id": "p3"}], None),
                ]
            },
        )

        batches = list(get_rows("token", "projects", mock.MagicMock()))

        assert [row["id"] for batch in batches for row in batch] == ["p1", "p2", "p3"]
        urls = _requested_urls(mock_session)
        assert "cursor" not in parse_qs(urlparse(urls[0]).query)
        assert parse_qs(urlparse(urls[1]).query)["cursor"] == ["cursor-2"]

    @mock.patch(PATCH_SESSION)
    def test_empty_page_yields_nothing(self, mock_session):
        _route_session(mock_session, {"/v1/projects": _page("projects", [], None)})

        assert list(get_rows("token", "projects", mock.MagicMock())) == []

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.northflank.northflank.MAX_PROJECT_PAGES", 2
    )
    @mock.patch(PATCH_SESSION)
    def test_page_cap_stops_and_logs(self, mock_session):
        _route_session(mock_session, {"/v1/projects": _page("projects", [{"id": "p"}], "always-more")})
        logger = mock.MagicMock()

        batches = list(get_rows("token", "projects", logger))

        assert len(batches) == 2
        assert mock_session.return_value.get.call_count == 2
        logger.warning.assert_called_once()
        assert "page cap" in logger.warning.call_args.args[0]

    def test_unknown_endpoint_raises(self):
        with pytest.raises(ValueError, match="Unknown Northflank endpoint"):
            list(get_rows("token", "nope", mock.MagicMock()))


class TestFanOut:
    @mock.patch(PATCH_SESSION)
    def test_child_rows_carry_project_id_across_projects(self, mock_session):
        _route_session(
            mock_session,
            {
                "/v1/projects": _page("projects", [{"id": "proj-a"}, {"id": "proj-b"}], None),
                "/v1/projects/proj-a/services": _page("services", [{"id": "svc-1"}], None),
                "/v1/projects/proj-b/services": _page("services", [{"id": "svc-2"}], None),
            },
        )

        batches = list(get_rows("token", "services", mock.MagicMock()))
        rows = [row for batch in batches for row in batch]

        assert [(row["id"], row["projectId"]) for row in rows] == [("svc-1", "proj-a"), ("svc-2", "proj-b")]

    @mock.patch(PATCH_SESSION)
    def test_injected_project_id_does_not_clobber_native_field(self, mock_session):
        # Volumes don't carry projectId natively; the transport must add it for the composite key.
        _route_session(
            mock_session,
            {
                "/v1/projects": _page("projects", [{"id": "proj-a"}], None),
                "/v1/projects/proj-a/volumes": _page(
                    "volumes", [{"id": "vol-1", "createdAt": "2026-01-01T00:00:00Z"}], None
                ),
            },
        )

        rows = [row for batch in get_rows("token", "volumes", mock.MagicMock()) for row in batch]

        assert rows == [{"id": "vol-1", "createdAt": "2026-01-01T00:00:00Z", "projectId": "proj-a"}]

    @mock.patch(PATCH_SESSION)
    def test_child_pagination_per_project(self, mock_session):
        _route_session(
            mock_session,
            {
                "/v1/projects": _page("projects", [{"id": "proj-a"}], None),
                "/v1/projects/proj-a/jobs": [
                    _page("jobs", [{"id": "j1"}], "jobs-cursor-2"),
                    _page("jobs", [{"id": "j2"}], None),
                ],
            },
        )

        rows = [row for batch in get_rows("token", "jobs", mock.MagicMock()) for row in batch]

        assert [row["id"] for row in rows] == ["j1", "j2"]
        job_urls = [u for u in _requested_urls(mock_session) if "/jobs" in u]
        assert parse_qs(urlparse(job_urls[1]).query)["cursor"] == ["jobs-cursor-2"]

    @mock.patch(PATCH_SESSION)
    def test_project_without_id_raises(self, mock_session):
        # A project missing its id would silently drop all of its nested resources; fail loudly instead.
        _route_session(
            mock_session,
            {"/v1/projects": _page("projects", [{"name": "no id"}], None)},
        )

        with pytest.raises(ValueError, match="missing a required 'id' field"):
            list(get_rows("token", "services", mock.MagicMock()))


class TestRetryBehavior:
    @mock.patch("tenacity.nap.time.sleep")
    @mock.patch(PATCH_SESSION)
    def test_429_honors_rate_limit_header(self, mock_session, mock_sleep):
        mock_session.return_value.get.side_effect = [
            _response({}, status_code=429, headers={"retry-after": "7"}),
            _response(_page("projects", [{"id": "p1"}], None)),
        ]

        rows = [row for batch in get_rows("token", "projects", mock.MagicMock()) for row in batch]

        assert [row["id"] for row in rows] == ["p1"]
        mock_sleep.assert_called_once_with(7)

    @mock.patch(PATCH_SESSION)
    def test_5xx_retries_then_succeeds(self, mock_session):
        mock_session.return_value.get.side_effect = [
            _response({}, status_code=503),
            _response(_page("projects", [{"id": "p1"}], None)),
        ]

        rows = [row for batch in get_rows("token", "projects", mock.MagicMock()) for row in batch]

        assert [row["id"] for row in rows] == ["p1"]
        assert mock_session.return_value.get.call_count == 2

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.northflank.northflank.MAX_RETRIES", 2)
    @mock.patch(PATCH_SESSION)
    def test_persistent_5xx_raises(self, mock_session):
        mock_session.return_value.get.return_value = _response({}, status_code=500)

        with pytest.raises(NorthflankRetryableError):
            list(get_rows("token", "projects", mock.MagicMock()))

    @mock.patch(PATCH_SESSION)
    def test_4xx_raises_immediately(self, mock_session):
        response = _response({}, status_code=401)
        response.raise_for_status.side_effect = Exception("401 Client Error")
        mock_session.return_value.get.return_value = response

        with pytest.raises(Exception, match="401 Client Error"):
            list(get_rows("token", "projects", mock.MagicMock()))

        assert mock_session.return_value.get.call_count == 1


class TestNorthflankSourceResponse:
    @parameterized.expand([(endpoint,) for endpoint in ENDPOINTS])
    def test_response_metadata_per_endpoint(self, endpoint):
        config = NORTHFLANK_ENDPOINTS[endpoint]
        response = northflank_source("token", endpoint, mock.MagicMock())

        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None

    @parameterized.expand([(endpoint,) for endpoint in ENDPOINTS])
    def test_fan_out_children_key_includes_project(self, endpoint):
        config = NORTHFLANK_ENDPOINTS[endpoint]
        # A fan-out child's id is only unique within its project, so the key must include projectId
        # or duplicate rows accumulate and every merge multi-matches them.
        if config.fan_out_over_projects:
            assert "projectId" in config.primary_keys

    def test_project_page_cap_is_bounded(self):
        assert MAX_PROJECT_PAGES <= 1000
