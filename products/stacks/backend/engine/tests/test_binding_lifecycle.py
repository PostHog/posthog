import os
import json
import shutil
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Thread

import pytest

from products.stacks.backend.engine.local import main
from products.stacks.backend.engine.runner import read_bindings, run_diff, run_push
from products.stacks.backend.engine.tests.test_translate_out import ENGINE_WORDS
from products.stacks.backend.engine.translate_in import translate_in
from products.stacks.backend.engine.types import Binding, Credentials, EngineOptions, Identity, Json, StackDescription

pytestmark = pytest.mark.skipif(
    not os.environ.get("POSTHOG_STACK_MIRROR") or not shutil.which("tofu"),
    reason="The binding lifecycle needs the installed stack mirror and binary.",
)


@contextmanager
def _project(
    routes: Mapping[str, object], *, missing: Mapping[str, object] | None = None
) -> Iterator[tuple[Credentials, list[tuple[str, str]]]]:
    requests = []

    class API(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            requests.append((self.command, self.path))

        def do_GET(self) -> None:
            self.respond(self.path, 200)

        def do_POST(self) -> None:
            self.respond(f"POST {self.path}", 201)

        def do_DELETE(self) -> None:
            self.respond(f"DELETE {self.path}", 204)

        def respond(self, route: str, status: int) -> None:
            if self.command == "GET" and missing and route in missing:
                body, status = missing[route], 404
            elif route in routes:
                body = routes[route]
            else:
                self.send_error(404)
                return
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            if status != 204:
                self.wfile.write(json.dumps(body).encode())

    with HTTPServer(("127.0.0.1", 0), API) as server:
        credentials: Credentials = {
            "host": f"http://127.0.0.1:{server.server_port}",
            "project_id": 7,
            "api_key": "example-personal-key",
        }
        worker = Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            yield credentials, requests
        finally:
            server.shutdown()
            worker.join()


def test_move_and_detach_an_existing_dashboard_without_writing_to_posthog(tmp_path: Path) -> None:
    attrs: dict[str, Json] = {
        "id": 17,
        "name": "Weekly activity",
        "pinned": False,
        "deleted": False,
        "description": None,
        "tags": None,
        "project_id": "7",
    }
    prior = json.dumps(
        {
            "version": 4,
            "terraform_version": "1.12.6",
            "serial": 5,
            "lineage": "23c0cfeb-4984-4e75-9c4b-cc8810112f01",
            "outputs": {},
            "resources": [
                {
                    "mode": "managed",
                    "type": "posthog_dashboard",
                    "name": "weekly",
                    "provider": 'provider["registry.opentofu.org/posthog/posthog"]',
                    "instances": [
                        {"index_key": "email", "schema_version": 0, "attributes": attrs, "sensitive_attributes": []}
                    ],
                }
            ],
        }
    ).encode()
    target: Identity = {"kind": "dashboard", "key": "weekly-activity"}
    description: StackDescription = {"version": 1, "resources": [{**target, "body": {"name": attrs["name"]}}]}
    mirror = os.environ["POSTHOG_STACK_MIRROR"]
    move = translate_in(
        description, [], {"mirror": mirror, "rename_map": {'posthog_dashboard.weekly["email"]': target}}
    )
    detach = translate_in(description, [], {"mirror": mirror, "detach": [target]})
    with _project({"/api/projects/7/dashboards/17/": attrs}) as (credentials, requests):
        diff, saved, serial = run_diff(tmp_path, move, prior, credentials)
        assert diff["errors"] == [] and serial == 5
        assert [(row["action"], row["kind"], row["key"]) for row in diff["changes"]] == [
            ("rename", "dashboard", "weekly-activity")
        ]
        result, renamed = run_push(tmp_path, move, saved, prior, credentials)
        assert result["errors"] == []
        assert read_bindings(renamed) == result["bindings"] == [{**target, "entity_id": 17}]

        diff, saved, _ = run_diff(tmp_path, detach, renamed, credentials)
        assert diff["errors"] == []
        assert sum(diff["summary"].values()) == diff["summary"]["release"] == 1
        result, released = run_push(tmp_path, detach, saved, renamed, credentials)
        assert result["errors"] == []
        assert read_bindings(released) == result["bindings"] == []
    assert set(requests) == {("GET", "/api/projects/7/dashboards/17/")}


def test_adopt_flag_by_key_and_dashboard_with_existing_tile(tmp_path: Path) -> None:
    layout: dict[str, Json] = {"sm": {"x": 0, "y": 0, "w": 4, "h": 3}}
    text: dict[str, Json] = {"body": "Welcome"}
    flag = {
        "key": "example",
        "name": "Example flag",
        "active": True,
        "deleted": False,
        "filters": {"groups": [{"rollout_percentage": 25}]},
    }
    description: StackDescription = {
        "version": 1,
        "resources": [
            {"kind": "flag", "key": "example", "body": {"key": "example", "name": "Example flag"}},
            {
                "kind": "dashboard",
                "key": "overview",
                "body": {"name": "Overview", "tiles": [{"text": text, "layouts": layout}]},
            },
        ],
    }
    options: EngineOptions = {"mirror": os.environ["POSTHOG_STACK_MIRROR"]}
    pending = translate_in(
        description, [{"kind": "dashboard", "key": "overview", "entity_id": 17, "status": "pending"}], options
    )
    routes = {
        "/api/projects/7/feature_flags/": {"results": [{"id": 31, **flag}], "next": None},
        "/api/projects/7/feature_flags/31/": {"id": 31, **flag},
        "/api/projects/7/dashboards/17/": {
            "id": 17,
            "name": "Overview",
            "pinned": False,
            "deleted": False,
            "tiles": [{"id": 12, "text": text, "layouts": layout}],
        },
    }
    with _project(routes) as (credentials, requests):
        diff, saved, _ = run_diff(tmp_path, pending, None, credentials)
        assert diff["errors"] == []
        assert [(change["kind"], change["action"]) for change in diff["changes"]] == [
            ("dashboard", "adopt"),
            ("flag", "adopt"),
        ]
        result, snapshot = run_push(tmp_path, pending, saved, None, credentials)
        assert result["errors"] == []
        raw = read_bindings(snapshot)
        assert raw == [
            {"kind": "dashboard", "key": "overview", "entity_id": 17},
            {"kind": "flag", "key": "example", "entity_id": 31},
        ]
        assert result["bindings"] == [{**binding, "origin": "adopted"} for binding in raw]
        after, _, _ = run_diff(tmp_path, translate_in(description, [], options), snapshot, credentials)
        assert not after["errors"] and not after["changes"] and not after["drift"]
        released_bindings = [Binding(**binding) for binding in result["bindings"]]
        unmarked_bindings = [Binding(**binding) for binding in raw]
        release = translate_in({"version": 1, "resources": []}, released_bindings, options)
        old_input = translate_in({"version": 1, "resources": []}, unmarked_bindings, options)
        old_diff, old_saved, _ = run_diff(tmp_path, old_input, snapshot, credentials)
        assert old_diff["summary"]["remove"] == 2
        explicit = translate_in(
            {"version": 1, "resources": []},
            unmarked_bindings,
            {**options, "detach": [Identity(kind=b["kind"], key=b["key"]) for b in raw]},
        )
        refused, unchanged = run_push(tmp_path, explicit, old_saved, snapshot, credentials)
        assert refused["errors"][0]["code"] == "removal_blocked" and unchanged == snapshot
        refused, unchanged = run_push(tmp_path, release, old_saved, snapshot, credentials)
        assert refused["errors"][0]["code"] == "removal_blocked"
        assert not ENGINE_WORDS.search(refused["errors"][0]["message"])
        assert unchanged == snapshot
        released, saved, _ = run_diff(tmp_path, release, snapshot, credentials)
        assert released["errors"] == []
        assert [change["action"] for change in released["changes"]] == ["release", "release"]
        assert sum(released["summary"].values()) == released["summary"]["release"] == 2
        result, empty = run_push(tmp_path, release, saved, snapshot, credentials)
        assert result["errors"] == [] and read_bindings(empty) == []
    assert set(requests) == {("GET", path) for path in routes}


def test_local_natural_adoption_releases_the_flag_on_a_later_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    definition, saved, snapshot = (tmp_path / name for name in ("description.json", "saved.diff", "snapshot"))
    definition.write_text(
        json.dumps({"version": 1, "resources": [{"kind": "flag", "key": "example", "body": {"name": "Example"}}]})
    )
    flag = {"id": 31, "key": "example", "name": "Example", "active": False, "deleted": False, "filters": {"groups": []}}
    routes = {
        "/api/projects/7/feature_flags/": {"results": [flag], "next": None},
        "/api/projects/7/feature_flags/31/": flag,
    }
    with _project(routes) as (credentials, requests):
        monkeypatch.setenv("POSTHOG_API_KEY", credentials["api_key"])
        args = [
            str(definition),
            "--host",
            credentials["host"],
            "--project-id",
            "7",
            "--snapshot",
            str(snapshot),
            "--saved-diff",
            str(saved),
        ]
        assert main(["diff", *args]) == 2
        assert json.loads(capsys.readouterr().out)["summary"]["adopt"] == 1
        assert main(["push", *args]) == 0
        assert json.loads(capsys.readouterr().out)["bindings"][0].get("origin") == "adopted"
        definition.write_text(json.dumps({"version": 1, "resources": []}))
        assert main(["diff", *args]) == 2
        diff = json.loads(capsys.readouterr().out)
        assert [change["action"] for change in diff["changes"]] == ["release"]
        assert main(["push", *args]) == 0
        assert json.loads(capsys.readouterr().out)["bindings"] == []
    assert all(method == "GET" for method, _ in requests)


def test_removed_protected_kind_in_an_older_snapshot_is_released(tmp_path: Path) -> None:
    resource = {
        "mode": "managed",
        "type": "posthog_alert",
        "name": "stack_missing",
        "provider": 'provider["registry.opentofu.org/posthog/posthog"]',
        "instances": [
            {
                "schema_version": 0,
                "attributes": {"id": "alert-example", "project_id": "7", "name": "Example"},
                "sensitive_attributes": [],
            }
        ],
    }
    previous = json.dumps(
        {
            "version": 4,
            "terraform_version": "1.12.6",
            "serial": 1,
            "lineage": "cf11ef8e-f458-4944-b2d7-26c325df0f83",
            "outputs": {},
            "resources": [resource],
        }
    ).encode()
    engine_input = translate_in(
        {"version": 1, "resources": []}, [], {"refresh": False, "mirror": os.environ["POSTHOG_STACK_MIRROR"]}
    )
    with _project({}) as (credentials, requests):
        diff, saved, _ = run_diff(tmp_path, engine_input, previous, credentials)
        assert diff["errors"] == []
        assert [change["action"] for change in diff["changes"]] == ["release"]
        result, snapshot = run_push(tmp_path, engine_input, saved, previous, credentials)
        assert result["errors"] == [] and read_bindings(snapshot) == []
    assert requests == []


def test_external_deletion_allows_push_to_create_a_new_owned_entity(tmp_path: Path) -> None:
    target: Identity = {"kind": "dashboard", "key": "weekly"}
    attrs = {
        "id": 42,
        "name": "Weekly",
        "pinned": False,
        "deleted": False,
        "description": None,
        "tags": None,
        "project_id": "7",
    }
    previous = json.dumps(
        {
            "version": 4,
            "terraform_version": "1.12.6",
            "serial": 4,
            "lineage": "7627c584-785e-47c6-8012-49faa32d263c",
            "resources": [
                {
                    "mode": "managed",
                    "type": "posthog_dashboard",
                    "name": "stack_weekly",
                    "provider": 'provider["registry.opentofu.org/posthog/posthog"]',
                    "instances": [{"schema_version": 0, "attributes": attrs, "sensitive_attributes": []}],
                }
            ],
        }
    ).encode()
    options: EngineOptions = {"mirror": os.environ["POSTHOG_STACK_MIRROR"]}
    description: StackDescription = {"version": 1, "resources": [{**target, "body": {"name": "Weekly"}}]}
    engine_input = translate_in(description, [{**target, "entity_id": 42, "origin": "adopted"}], options)
    routes = {
        "POST /api/projects/7/dashboards/": {**attrs, "id": 43},
        "/api/projects/7/dashboards/43/": {**attrs, "id": 43},
    }
    with _project(routes) as (credentials, requests):
        diff, saved, _ = run_diff(tmp_path, engine_input, previous, credentials)
        assert saved and diff["errors"] == [] and diff["summary"]["create"] == 1
        assert diff["drift"][0]["deleted"] is True
        result, snapshot = run_push(tmp_path, engine_input, saved, previous, credentials)
        assert result["errors"] == []
        assert result["bindings"] == [{**target, "entity_id": 43}]
        following, _, _ = run_diff(
            tmp_path,
            translate_in(description, [Binding(**b) for b in result["bindings"]], options),
            snapshot,
            credentials,
        )
        assert not following["errors"] and not following["drift"] and not following["changes"]
    assert [method for method, _ in requests].count("POST") == 1
