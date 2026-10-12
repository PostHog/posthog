import io
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any, cast

from unittest.mock import patch

from django.test import override_settings

import requests
from parameterized import parameterized
from requests.adapters import HTTPAdapter
from urllib3.response import HTTPResponse

from products.warehouse_sources.backend.temporal.data_imports.sources.baserow import (
    baserow,
    settings as baserow_settings,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import (
    NO_REQUEST_TIMEOUT,
    make_tracked_adapter,
    make_tracked_session,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import rest_api_resources
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import RESTClient
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import RESTAPIConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.custom import source as custom_source
from products.warehouse_sources.backend.temporal.data_imports.sources.fusionauth import fusionauth
from products.warehouse_sources.backend.temporal.data_imports.sources.plunk import plunk

BASE_URL = "https://api.example.com"
DEFAULT_TIMEOUT = (7.0, 11.0)


class _SilentHost:
    """Stands in for the socket layer. Records the deadline each request would have had."""

    def __init__(self) -> None:
        self.timeouts: list[Any] = []

    def send(self, _adapter: HTTPAdapter, request: requests.PreparedRequest, **kwargs: Any) -> requests.Response:
        self.timeouts.append(kwargs.get("timeout"))
        response = requests.Response()
        response.status_code = 200
        response.url = request.url or ""
        response.request = request
        response.headers["Content-Type"] = "application/json"
        response.raw = HTTPResponse(body=io.BytesIO(b"[]"), status=200, preload_content=False)
        return response


@contextmanager
def _silent_host() -> Iterator[_SilentHost]:
    host = _SilentHost()
    with (
        override_settings(
            DATA_WAREHOUSE_SOURCE_CONNECT_TIMEOUT_SECONDS=DEFAULT_TIMEOUT[0],
            DATA_WAREHOUSE_SOURCE_READ_TIMEOUT_SECONDS=DEFAULT_TIMEOUT[1],
        ),
        patch.object(HTTPAdapter, "send", autospec=True, side_effect=host.send),
    ):
        yield host


def _framework(client: dict[str, Any]) -> None:
    config = cast(
        RESTAPIConfig,
        {"client": {"base_url": BASE_URL, **client}, "resources": [{"name": "items", "endpoint": {"path": "/items"}}]},
    )
    for resource in rest_api_resources(config, 1, "job", None):
        list(resource)


def _paginate(**client_kwargs: Any) -> None:
    list(RESTClient(base_url=BASE_URL, **client_kwargs).paginate("/items"))


def _foreign_session_with_tracked_adapter() -> None:
    session = requests.Session()
    session.mount("https://", make_tracked_adapter())
    session.get(f"{BASE_URL}/items")


class TestDefaultRequestTimeout:
    @parameterized.expand(
        [
            ("framework", lambda: _framework({}), DEFAULT_TIMEOUT),
            ("framework_override", lambda: _framework({"request_timeout": (1.0, 2.0)}), (1.0, 2.0)),
            ("paginate", lambda: _paginate(), DEFAULT_TIMEOUT),
            ("paginate_override", lambda: _paginate(request_timeout=(1.0, 2.0)), (1.0, 2.0)),
            ("paginate_opt_out", lambda: _paginate(request_timeout=NO_REQUEST_TIMEOUT), NO_REQUEST_TIMEOUT),
            ("session_get", lambda: make_tracked_session().get(f"{BASE_URL}/items"), DEFAULT_TIMEOUT),
            ("session_post", lambda: make_tracked_session().post(f"{BASE_URL}/items", json={}), DEFAULT_TIMEOUT),
            (
                "session_explicit_none",
                lambda: make_tracked_session().get(f"{BASE_URL}/items", timeout=None),
                DEFAULT_TIMEOUT,
            ),
            ("session_override", lambda: make_tracked_session().get(f"{BASE_URL}/items", timeout=5), 5),
            (
                "session_opt_out",
                lambda: make_tracked_session().get(f"{BASE_URL}/items", timeout=NO_REQUEST_TIMEOUT),
                NO_REQUEST_TIMEOUT,
            ),
            ("foreign_session_with_tracked_adapter", _foreign_session_with_tracked_adapter, DEFAULT_TIMEOUT),
        ]
    )
    def test_request_reaches_the_socket_with_a_deadline(
        self, _name: str, send_request: Callable[[], Any], expected: Any
    ) -> None:
        with _silent_host() as host:
            send_request()
        assert host.timeouts == [expected]

    @parameterized.expand(
        [
            (
                "baserow",
                lambda: baserow._bounded_session("token"),
                (baserow_settings.CONNECT_TIMEOUT_SECONDS, baserow_settings.READ_TIMEOUT_SECONDS),
            ),
            ("fusionauth", lambda: fusionauth._make_bounded_session("key"), fusionauth.DEFAULT_TIMEOUT_SECONDS),
            ("plunk", lambda: plunk._make_bounded_session("key"), plunk.DEFAULT_TIMEOUT_SECONDS),
            (
                "custom_preview",
                lambda: custom_source._build_preview_session(()),
                (custom_source.PROBE_CONNECT_TIMEOUT, custom_source.PROBE_READ_TIMEOUT),
            ),
        ]
    )
    def test_session_default_applies_on_the_paths_that_pass_none(
        self, _name: str, make_session: Callable[[], requests.Session], expected: Any
    ) -> None:
        with _silent_host() as host:
            list(RESTClient(base_url=BASE_URL, session=make_session()).paginate("/items"))
            make_session().get(f"{BASE_URL}/items")
            make_session().get(f"{BASE_URL}/items", timeout=3)
        assert host.timeouts == [expected, expected, 3]
