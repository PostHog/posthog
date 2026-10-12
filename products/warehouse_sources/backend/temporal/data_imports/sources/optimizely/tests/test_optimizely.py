import json
from collections.abc import Callable, Iterable
from typing import Any, cast
from urllib.parse import parse_qs, urlparse

import pytest
from unittest import mock

import requests
from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.optimizely.optimizely import (
    optimizely_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.optimizely.settings import (
    ENDPOINTS,
    OPTIMIZELY_ENDPOINTS,
)

# The RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the optimizely module.
OPTIMIZELY_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.optimizely.optimizely.make_tracked_session"
)


def _response(items: list[dict[str, Any]], *, status: int = 200, next_url: str | None = None) -> Response:
    resp = Response()
    resp.status_code = status
    resp._content = json.dumps(items).encode()
    if next_url:
        # RFC 5988 Link header — requests parses it into `response.links`, which HeaderLinkPaginator reads.
        resp.headers["Link"] = f'<{next_url}>; rel="next"'
    return resp


def _wire(mock_make_session: mock.MagicMock, router: Callable[[str], Any]) -> list[str]:
    """Route the RESTClient's session to ``router(prepared.url)``, capturing each sent URL.

    A real ``requests.Session`` prepares requests (so ``prepared.url`` — used by the framework's
    host-pinning guard — is a genuine URL), while ``send`` is mocked to look up the fixture by URL.
    A router result that is an ``Exception`` is raised; anything else is returned as the response.
    """
    session = requests.Session()
    sent: list[str] = []

    def _send(prepared: Any, **kwargs: Any) -> Response:
        sent.append(prepared.url)
        result = router(prepared.url)
        if isinstance(result, Exception):
            raise result
        return result

    session.send = mock.MagicMock(side_effect=_send)  # type: ignore[method-assign]
    mock_make_session.return_value = session
    return sent


def _rows(endpoint: str) -> list[dict[str, Any]]:
    response = optimizely_source("token", endpoint, team_id=1, job_id="j")
    return [row for page in cast("Iterable[Any]", response.items()) for row in page]


class TestValidateCredentials:
    @parameterized.expand([(200, True), (403, True), (401, False)])
    @mock.patch(OPTIMIZELY_SESSION_PATCH)
    def test_status_mapping(self, status_code, expected, mock_session):
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status_code)
        assert validate_credentials("token") is expected


class TestSimpleEndpoint:
    @parameterized.expand(
        [
            ("attacker_host", "https://evil.example.com/v2/projects?page=2&per_page=100"),
            ("subdomain_spoof", "https://api.optimizely.com.evil.com/v2/projects?page=2"),
            ("internal_metadata", "http://169.254.169.254/latest/meta-data/"),
        ]
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_refuses_to_follow_offhost_next_link(self, _name, off_host_url, mock_make_session):
        # A hostile upstream points the `Link` next URL off-host; the credentialed request must never
        # be sent. The old transport stopped silently; the framework fails loud instead — but the
        # security guarantee (the off-host URL is never fetched) is identical.
        def router(url: str) -> Response:
            return _response([{"id": 1}], next_url=off_host_url)

        sent = _wire(mock_make_session, router)

        with pytest.raises(ValueError):
            _rows("projects")

        assert off_host_url not in sent
        assert sent == ["https://api.optimizely.com/v2/projects?per_page=100"]


class TestProjectScopedFanOut:
    @parameterized.expand([(400,), (403,), (404,)])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_skips_projects_without_feature_access(self, skip_status, mock_make_session):
        def router(url: str) -> Response:
            parsed = urlparse(url)
            if parsed.path == "/v2/projects":
                return _response([{"id": 11}, {"id": 22}])
            project_id = parse_qs(parsed.query)["project_id"][0]
            if project_id == "11":
                return _response([], status=skip_status)
            return _response([{"id": "camp-22"}])

        _wire(mock_make_session, router)
        rows = _rows("campaigns")

        # Project 11 lacks access (4xx) and is skipped; project 22 still syncs.
        assert [row["id"] for row in rows] == ["camp-22"]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_raises_on_unexpected_child_error(self, mock_make_session):
        # 401 is not in the skip set (400/403/404), so it fails the whole stream loudly.
        def router(url: str) -> Response:
            parsed = urlparse(url)
            if parsed.path == "/v2/projects":
                return _response([{"id": 11}])
            return _response([], status=401)

        _wire(mock_make_session, router)

        with pytest.raises(requests.HTTPError):
            _rows("experiments")


class TestOptimizelySourceResponse:
    @parameterized.expand([(endpoint,) for endpoint in ENDPOINTS])
    def test_response_metadata_per_endpoint(self, endpoint):
        config = OPTIMIZELY_ENDPOINTS[endpoint]
        response = optimizely_source("token", endpoint, team_id=1, job_id="j")

        assert response.name == endpoint
        assert response.primary_keys == [config.primary_key]
        assert response.sort_mode == "asc"
        assert response.partition_mode is None
        assert response.partition_keys is None
