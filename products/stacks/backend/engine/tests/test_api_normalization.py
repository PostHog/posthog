import os
import json
import shutil
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Thread
from typing import Any
from urllib.parse import urlsplit

import pytest

from products.stacks.backend.engine import Credentials, StackDescription, run_diff, run_push, translate_in
from products.stacks.backend.engine.mappings import PROVIDER_VERSION
from products.stacks.backend.engine.types import Json

Response = tuple[int, object]
Route = Callable[[str, str, dict[str, Any]], Response]


@contextmanager
def loopback_api(route: Route) -> Iterator[Credentials]:
    class API(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            pass

        def dispatch(self) -> None:
            assert self.headers.get("Authorization") == "Bearer example-key"
            body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            status, result = route(self.command, urlsplit(self.path).path, json.loads(body) if body else {})
            self.send_response(status)
            if status != 204:
                self.send_header("Content-Type", "application/json")
            self.end_headers()
            if status != 204:
                self.wfile.write(json.dumps(result).encode())

        do_GET = do_POST = do_PATCH = do_PUT = do_DELETE = dispatch

    with HTTPServer(("127.0.0.1", 0), API) as server:
        thread = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        thread.start()
        try:
            yield {"host": f"http://127.0.0.1:{server.server_port}", "project_id": 7, "api_key": "example-key"}
        finally:
            server.shutdown()
            thread.join()


@pytest.fixture(params=["1.0.24", PROVIDER_VERSION])
def provider(request: pytest.FixtureRequest) -> tuple[str, str]:
    version = request.param
    mirror = os.environ.get("POSTHOG_STACK_PREVIOUS_MIRROR" if version == "1.0.24" else "POSTHOG_STACK_MIRROR")
    if not mirror or not shutil.which("tofu"):
        pytest.skip(f"Needs the local mirror for {version} and OpenTofu")
    assert mirror is not None
    return version, mirror


def test_dashboard_layout_round_trip_when_api_keeps_only_grid_coordinates(
    tmp_path: Path, provider: tuple[str, str]
) -> None:
    version, mirror = provider
    collection = "/api/projects/7/dashboards/"
    dashboard: dict[str, Any] = {}
    submitted: list[dict[str, Any]] = []
    layout: dict[str, Json] = {
        "sm": {"x": 0, "y": 0, "w": 6, "h": 4, "i": "4", "minH": 4, "minW": 3, "moved": False, "static": False}
    }

    def route(method: str, path: str, body: dict[str, Any]) -> Response:
        if (method, path) == ("POST", collection):
            dashboard.update({"id": 18, "tiles": [], **body})
            return 201, dashboard
        if path == f"{collection}18/" and method == "GET":
            return 200, dashboard
        if path == f"{collection}18/" and method == "PATCH":
            for tile in body["tiles"]:
                submitted.append(tile["layouts"])
                filtered = {
                    breakpoint: {key: box[key] for key in ("x", "y", "w", "h") if key in box}
                    for breakpoint, box in tile["layouts"].items()
                }
                dashboard["tiles"] = [{"id": 4, **tile, "layouts": filtered}]
            return 200, dashboard
        return 404, {"detail": "Unknown route."}

    description: StackDescription = {
        "version": 1,
        "resources": [
            {
                "kind": "dashboard",
                "key": "grid",
                "body": {"name": "Grid", "tiles": [{"text": {"body": "Notes"}, "layouts": layout}]},
            }
        ],
    }
    incoming = translate_in(description, [], {"mirror": mirror})
    incoming.config["terraform"]["required_providers"]["posthog"]["version"] = version
    with loopback_api(route) as credentials:
        review, saved, _ = run_diff(tmp_path, incoming, None, credentials)
        assert not review["errors"], review
        pushed, record = run_push(tmp_path, incoming, saved, None, credentials)
        following, _, _ = run_diff(tmp_path, incoming, record, credentials)
    assert submitted == [layout]
    assert pushed["bindings"] == [{"kind": "dashboard", "key": "grid", "entity_id": 18}]
    assert not following["errors"]
    if version == PROVIDER_VERSION:
        # The pinned build compares layouts on the coordinates PostHog keeps, so the push converges.
        assert pushed["errors"] == []
        assert following["changes"] == []
        return
    assert [(error["code"], error.get("kind"), error.get("key")) for error in pushed["errors"]] == [
        ("stack_failed", "dashboard", "grid")
    ]
    (change,) = following["changes"]
    assert change["action"] == "update"
    assert change["fields"] == [
        {
            "path": "tiles[0].layouts",
            "before": {"sm": {"x": 0, "y": 0, "w": 6, "h": 4}},
            "after": layout,
            "sensitive": False,
        }
    ]


def test_internal_destination_round_trip_when_api_sets_its_filter_source(
    tmp_path: Path, provider: tuple[str, str]
) -> None:
    version, mirror = provider
    collection = "/api/environments/7/hog_functions/"
    entity_id = "4d732952-65a0-432b-ad2d-b58cde5bafdb"
    destination: dict[str, Any] = {}
    submitted: list[str] = []

    def route(method: str, path: str, body: dict[str, Any]) -> Response:
        if (method, path) in {("POST", collection), ("PATCH", f"{collection}{entity_id}/")}:
            submitted.append(body["filters"]["source"])
            destination.update({**body, "id": entity_id, "filters": {**body["filters"], "source": "internal-events"}})
            return (201 if method == "POST" else 200), destination
        if (method, path) == ("GET", f"{collection}{entity_id}/"):
            return 200, destination
        return 404, {"detail": "Unknown route."}

    description: StackDescription = {
        "version": 1,
        "resources": [
            {
                "kind": "destination",
                "key": "notify",
                "body": {
                    "type": "internal_destination",
                    "name": "Notify",
                    "hog": "print('hello')",
                    "enabled": True,
                    "filters": {"source": "events"},
                },
            }
        ],
    }
    incoming = translate_in(description, [], {"mirror": mirror})
    incoming.config["terraform"]["required_providers"]["posthog"]["version"] = version
    with loopback_api(route) as credentials:
        review, saved, _ = run_diff(tmp_path, incoming, None, credentials)
        assert not review["errors"], review
        pushed, record = run_push(tmp_path, incoming, saved, None, credentials)
        following, _, _ = run_diff(tmp_path, incoming, record, credentials)
    assert submitted == ["events"]
    assert pushed["bindings"] == [{"kind": "destination", "key": "notify", "entity_id": entity_id}]
    assert not following["errors"]
    if version == PROVIDER_VERSION:
        # The pinned build reads the source PostHog forces on an internal destination as the configured one.
        assert pushed["errors"] == []
        assert following["changes"] == []
        return
    assert [(error["code"], error.get("kind"), error.get("key")) for error in pushed["errors"]] == [
        ("stack_failed", "destination", "notify")
    ]
    (change,) = following["changes"]
    assert change["action"] == "recreate"
    assert change["fields"] == [
        {"path": "filters", "before": {"source": "internal-events"}, "after": {"source": "events"}, "sensitive": False}
    ]
