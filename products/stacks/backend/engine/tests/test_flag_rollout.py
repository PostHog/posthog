from __future__ import annotations

import os
import json
import shutil
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Thread
from typing import Any
from urllib.parse import urlsplit

import pytest

from products.stacks.backend.engine import (
    Credentials,
    EngineOptions,
    StackDescription,
    run_diff,
    run_push,
    translate_in,
)
from products.stacks.backend.engine.tests.test_api_normalization import Response, loopback_api
from products.stacks.backend.engine.types import Binding, Json


@pytest.mark.skipif(
    not os.environ.get("POSTHOG_STACK_MIRROR") or not shutil.which("tofu"),
    reason="The flag round trip needs the local binary and mirror.",
)
def test_flag_metadata_push_preserves_a_rollout_edited_after_diff(tmp_path: Path) -> None:
    collection = "/api/projects/7/feature_flags/"
    detail = f"{collection}18/"
    flag: dict[str, Any] = {
        "id": 18,
        "key": "checkout",
        "name": "Checkout",
        "active": True,
        "deleted": False,
        "version": 1,
        "filters": {"groups": [{"rollout_percentage": 10}]},
    }
    patches: list[dict[str, Any]] = []

    class FlagAPI(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            pass

        def reply(self, value: object) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(value).encode())

        def do_GET(self) -> None:
            path = urlsplit(self.path).path
            if path == collection:
                self.reply({"results": [flag], "next": None})
            elif path == detail:
                self.reply(flag)
            else:
                self.send_error(404)

        def do_PATCH(self) -> None:
            if self.path != detail:
                self.send_error(404)
                return
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            patches.append(payload)
            if "version" in payload and payload["version"] != flag["version"]:
                self.send_error(409)
                return
            flag.update(payload)
            flag["version"] += 1
            self.reply(flag)

    options: EngineOptions = {"mirror": os.environ["POSTHOG_STACK_MIRROR"]}
    description: StackDescription = {
        "version": 1,
        "resources": [{"kind": "flag", "key": "checkout", "body": {"key": "checkout", "name": "Checkout"}}],
    }
    current = translate_in(description, [], options)
    with HTTPServer(("127.0.0.1", 0), FlagAPI) as server:
        thread = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        thread.start()
        try:
            credentials: Credentials = {
                "host": f"http://127.0.0.1:{server.server_port}",
                "project_id": 7,
                "api_key": "example-key",
            }
            initial, saved, _ = run_diff(tmp_path, current, None, credentials)
            assert initial["errors"] == [] and initial["summary"]["adopt"] == 1
            adopted, record = run_push(tmp_path, current, saved, None, credentials)
            assert adopted["errors"] == []

            description["resources"][0]["body"]["name"] = "Checkout experiment"
            renamed = translate_in(description, [{"kind": "flag", "key": "checkout", "entity_id": 18}], options)
            reviewed, saved, _ = run_diff(tmp_path, renamed, record, credentials)
            assert reviewed["errors"] == [] and reviewed["summary"]["update"] == 1
            assert [field["path"] for field in reviewed["changes"][0]["fields"]] == ["name"]

            new_filters = {"groups": [{"rollout_percentage": 65}]}
            flag.update({"active": False, "filters": new_filters, "version": 2})
            pushed, _ = run_push(tmp_path, renamed, saved, record, credentials)
        finally:
            server.shutdown()
            thread.join()

    assert len(patches) == 1
    assert {"active", "filters", "rollout_percentage"}.isdisjoint(patches[0])
    assert pushed["errors"] == []
    assert flag["name"] == "Checkout experiment"
    assert flag["active"] is False and flag["filters"] == new_filters


@pytest.mark.skipif(
    not os.environ.get("POSTHOG_STACK_MIRROR") or not shutil.which("tofu"),
    reason="The flag round trip needs the local binary and mirror.",
)
def test_flag_creation_seeds_release_conditions_and_variants_and_owns_only_variants(tmp_path: Path) -> None:
    flags = "/api/projects/7/feature_flags/"
    experiments = "/api/projects/7/experiments/"
    flag: dict[str, Any] = {}
    experiment: dict[str, Any] = {}
    writes: list[tuple[str, dict[str, Any]]] = []

    def route(method: str, path: str, body: dict[str, Any]) -> Response:
        if (method, path) == ("GET", flags):
            return 200, {"results": [flag] if flag else [], "next": None}
        if (method, path) == ("POST", flags):
            writes.append(("flag", body))
            flag.update({**body, "id": 18, "version": 1, "deleted": False})
            return 201, flag
        if (method, path) == ("GET", f"{flags}18/"):
            return 200, flag
        if (method, path) == ("PATCH", f"{flags}18/"):
            writes.append(("flag", body))
            if body.get("version", flag["version"]) != flag["version"]:
                return 409, {}
            flag.update({**body, "version": flag["version"] + 1})
            return 200, flag
        if (method, path) == ("POST", experiments):
            if (
                body["feature_flag_key"] != flag.get("key")
                or len(flag.get("filters", {}).get("multivariate", {}).get("variants", [])) < 2
            ):
                return 400, {"detail": "Feature flag must have at least 2 variants."}
            writes.append(("experiment", body))
            experiment.update({**body, "id": 19, "status": "draft"})
            return 201, experiment
        if (method, path) == ("GET", f"{experiments}19/"):
            return 200, experiment
        return 404, {"detail": "Unknown route."}

    original_variants: dict[str, Json] = {
        "variants": [{"key": "control", "rollout_percentage": 50}, {"key": "test", "rollout_percentage": 50}]
    }
    original_groups: list[Json] = [{"rollout_percentage": 10, "properties": []}]
    filters: dict[str, Json] = {"groups": original_groups, "multivariate": original_variants, "payloads": {"test": "1"}}
    flag_body: dict[str, Json] = {"key": "checkout", "name": "Checkout", "active": True, "filters": filters}
    desc: StackDescription = {
        "version": 1,
        "resources": [
            {
                "kind": "experiment",
                "key": "checkout",
                "depends_on": [{"kind": "flag", "key": "checkout"}],
                "body": {"name": "Checkout experiment", "feature_flag_key": "checkout"},
            },
            {"kind": "flag", "key": "checkout", "body": flag_body},
        ],
    }
    options: EngineOptions = {"mirror": os.environ["POSTHOG_STACK_MIRROR"]}
    fresh = translate_in(desc, [], options)
    with loopback_api(route) as credentials:
        diff, saved, _ = run_diff(tmp_path, fresh, None, credentials)
        assert not diff["errors"]
        pushed, record = run_push(tmp_path, fresh, saved, None, credentials)
        assert not pushed["errors"]
        assert [kind for kind, _ in writes] == ["flag", "experiment"]
        assert writes[0][1]["filters"] == filters and writes[0][1]["active"] is True

        interim_groups: list[Json] = [{"rollout_percentage": 30, "properties": []}]
        flag.update({"filters": {**filters, "groups": interim_groups}, "active": False, "version": 2})
        bindings = [Binding(**b) for b in pushed["bindings"]]
        incoming = translate_in(desc, bindings, options)
        conditions_only, _, _ = run_diff(tmp_path, incoming, record, credentials)
        assert not conditions_only["changes"] and not conditions_only["drift"] and not conditions_only["errors"]

        filters["groups"] = [{"rollout_percentage": 40, "properties": []}]
        incoming = translate_in(desc, bindings, options)
        conditions_only, _, _ = run_diff(tmp_path, incoming, record, credentials)
        assert not conditions_only["changes"] and not conditions_only["drift"] and not conditions_only["errors"]
        filters["groups"] = original_groups

        changed_variants: dict[str, Json] = {
            "variants": [{"key": "control", "rollout_percentage": 25}, {"key": "test", "rollout_percentage": 75}]
        }
        filters["multivariate"] = changed_variants
        flag_body["active"] = True
        incoming = translate_in(desc, bindings, options)
        reviewed, saved, _ = run_diff(tmp_path, incoming, record, credentials)
        assert not reviewed["errors"]
        (change,) = reviewed["changes"]
        assert (change["kind"], change["action"], change["fields"]) == (
            "flag",
            "update",
            [
                {
                    "path": "filters.multivariate",
                    "before": original_variants,
                    "after": changed_variants,
                    "sensitive": False,
                }
            ],
        )
        latest_groups = [{"rollout_percentage": 65, "properties": []}]
        flag["filters"]["groups"] = latest_groups
        flag["version"] = 3
        pushed, record = run_push(tmp_path, incoming, saved, record, credentials)
        assert not pushed["errors"]
        assert len(writes) == 3
        assert "active" not in writes[2][1] and flag["active"] is False
        assert flag["filters"] == {**filters, "groups": latest_groups}
        followup, _, _ = run_diff(tmp_path, incoming, record, credentials)
        assert not followup["changes"] and not followup["drift"] and not followup["errors"]
