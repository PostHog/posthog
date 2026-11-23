import os
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import pytest

from products.stacks.backend import engine
from products.stacks.backend.engine.addresses import address
from products.stacks.backend.engine.mappings import load_mapping
from products.stacks.backend.engine.tests.test_binding_lifecycle import _project
from products.stacks.backend.engine.tests.test_translate_out import ENGINE_WORDS
from products.stacks.backend.engine.types import StackDescription


def test_natural_key_kinds_match_the_declared_identity_rules() -> None:
    assert engine.natural_key_kinds() == frozenset(
        {"flag", "event", "property_group", "model", "endpoint", "metric", "context_page"}
    )


@pytest.mark.parametrize(
    ("detail", "code", "guidance"),
    [
        ("the context layer is not enabled for project 7", "context_layer_not_enabled", "enable"),
        (
            'context wiki revision conflict writing "areas/overview.md" (current head abc). Refresh and create a new plan',
            "stack_moved",
            "run diff again",
        ),
        (
            'context page "areas/{overview}.md" is managed twice in this organization. Keep a single resource for this wiki path',
            "context_page_managed_twice",
            "one definition",
        ),
        (
            'context wiki revision conflict writing "areas/{overview}.md" (current head abc). The previous PUT may have been applied. Refresh to see the published content before planning again',
            "context_page_write_uncertain",
            "published content",
        ),
    ],
)
def test_wiki_failures_use_actionable_project_language(detail: str, code: str, guidance: str) -> None:
    (error,) = engine.translate_error({"detail": detail})
    assert error["code"] == code and not ENGINE_WORDS.search(error["message"])
    assert guidance in error["message"].lower() and "abc" not in error["message"]


def test_managed_write_refusal_points_to_the_definition() -> None:
    refusal = {
        "code": "managed_in_code",
        "detail": "private diagnostic",
        "stack": "metrics",
        "repository": "example/analytics",
        "source": {"file": "metrics/events.ts"},
    }
    (error,) = engine.translate_error(
        {"detail": "failed to send PATCH request: API error (status 409): " + json.dumps(refusal)}
    )
    assert error["code"] == "managed_in_code"
    assert all(value in error["message"] for value in ("metrics", "example/analytics", "metrics/events.ts"))
    assert "private diagnostic" not in error["message"] and not ENGINE_WORDS.search(error["message"])


def test_missing_secrets_name_every_missing_reference_without_revealing_values(tmp_path: Path) -> None:
    description: StackDescription = {
        "version": 1,
        "resources": [
            {
                "kind": "destination",
                "key": "example",
                "body": {
                    "name": "Example",
                    "inputs": {
                        "left": {"value": {"$secret": "LEFT"}},
                        "right": {"value": {"$secret": "RIGHT"}},
                        "kept": {"value": {"$secret": "KEPT"}},
                    },
                },
            }
        ],
    }
    diff, saved, _ = engine.run_diff(
        tmp_path,
        engine.translate_in(description, [], {"mirror": tmp_path}),
        None,
        {
            "project_id": 7,
            "host": "https://127.0.0.1:1",
            "api_key": "example-key",
            "secrets": {"KEPT": "example-private-value"},
        },
    )
    assert not saved
    assert all(error["code"] == "secret_missing" for error in diff["errors"])
    messages = " ".join(error["message"] for error in diff["errors"])
    assert "LEFT" in messages and "RIGHT" in messages
    assert "example-private-value" not in json.dumps(diff) and not ENGINE_WORDS.search(messages)


@pytest.mark.skipif(
    not os.getenv("POSTHOG_STACK_MIRROR") or not shutil.which("tofu"),
    reason="This comparison needs the installed development build",
)
@pytest.mark.parametrize("real", [False, True], ids=["handwritten", "evaluated-sdk"])
def test_new_kinds_from_an_empty_record(real: bool, tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[5]
    fixture = (
        root / "packages/sdk/tests/fixtures/stack-all-kinds/description.json"
        if real
        else Path(__file__).parent / "fixtures/new_kinds.json"
    )
    if real and not fixture.exists():
        pytest.skip("The evaluated SDK fixture is required for this comparison")
    mirror = os.environ["POSTHOG_STACK_MIRROR"]
    description: StackDescription = json.loads(fixture.read_bytes())
    pages = {row["key"] for row in description["resources"] if row["kind"] == "context_page"}
    if real:
        assert len(pages) == 2
    incoming = engine.translate_in(description, [], {"mirror": mirror, "refresh": False})
    if real:
        with_dependencies = [row for row in description["resources"] if row.get("depends_on")]
        assert {"experiment", "metric", "model"} <= {row["kind"] for row in with_dependencies}
        for row in with_dependencies:
            resource_type, label = address(row["kind"], row["key"]).split(".")
            targets = incoming.config["resource"][resource_type][label]["depends_on"]
            assert set(targets) == {address(dep["kind"], dep["key"]) for dep in row["depends_on"]}
    empty_catalog: dict[str, object] = {"results": [], "next": None}
    routes = {
        f"/api/projects/7/{load_mapping(kind)['natural_key']['lookup']}/": empty_catalog
        for kind in engine.natural_key_kinds()
    }
    routes["/api/projects/7/surveys/"] = empty_catalog
    routes["/api/projects/7/event_schemas/"] = empty_catalog
    routes["/api/projects/7/data_quality_checks/"] = empty_catalog
    missing = {
        "/api/projects/7/context_layer/agent/pages/?" + urlencode({"path": path}): {"detail": f"no page at {path}"}
        for path in pages
    }
    with _project(routes, missing=missing) as (credentials, _):
        credentials["secrets"] = dict.fromkeys(incoming.secret_names, "example-secret-value")
        diff, saved, serial = engine.run_diff(tmp_path, incoming, None, credentials)
    assert diff["errors"] == [] and saved and serial == 0
    assert sorted((row["kind"], row["key"], row["action"]) for row in diff["changes"]) == sorted(
        (row["kind"], row["key"], "create") for row in description["resources"]
    )
    assert diff["summary"]["create"] == len(description["resources"]) and not diff["drift"]
    assert "example-secret-value" not in json.dumps(diff)


@pytest.mark.skipif(
    not os.getenv("POSTHOG_STACK_MIRROR") or not shutil.which("tofu"), reason="Needs the installed development build"
)
def test_existing_event_membership_and_both_name_imports_are_adopted(tmp_path: Path) -> None:
    event_id = "00000000-0000-4000-a000-000000000011"
    group_id = "00000000-0000-4000-a000-000000000012"
    link_id = "00000000-0000-4000-a000-000000000013"
    event = {
        "name": "sample",
        "id": event_id,
        "tags": ["original"],
        "enforcement_mode": "reject",
        "owner": {"id": 42},
        "description": "Kept in PostHog",
        "verified": True,
        "hidden": False,
    }
    group = {"name": "Cart", "id": group_id, "description": "", "properties": []}
    link = {"id": link_id, "event_definition": event_id, "property_group": group}
    root = "/api/projects/7/"
    routes: dict[str, object] = {
        root + "event_definitions/": {"results": [event], "next": None},
        root + "event_definitions/by_name/?name=sample": event,
        root + "schema_property_groups/": {"results": [group], "next": None},
        root + f"schema_property_groups/{group_id}/": group,
        root + "event_schemas/": {"results": [link], "next": None},
        root + f"event_schemas/?event_definition={event_id}": {"results": [link], "next": None},
    }
    desc: StackDescription = {
        "version": 1,
        "resources": [
            {
                "kind": "event",
                "key": "sample",
                "body": {"name": "sample", "property_groups": [{"$ref": {"kind": "property_group", "key": "Cart"}}]},
            },
            {"kind": "property_group", "key": "Cart", "body": {"name": "Cart"}},
        ],
    }
    options: engine.EngineOptions = {"mirror": os.environ["POSTHOG_STACK_MIRROR"]}
    incoming = engine.translate_in(desc, [], options)
    event_config = incoming.config["resource"]["posthog_event_definition"]["stack_sample"]
    assert set(event_config) == {"name", "lifecycle"}
    with _project(routes) as (credentials, requests):
        diff, saved, _ = engine.run_diff(tmp_path, incoming, None, credentials)
        assert diff["errors"] == [] and diff["summary"]["adopt"] == 2
        assert {change["key"]: change["entity_id"] for change in diff["changes"]} == {
            "Cart": group_id,
            "sample": event_id,
        }
        result, snapshot = engine.run_push(tmp_path, incoming, saved, None, credentials)
        assert result["errors"] == [], requests
        assert result["bindings"] == [
            {"kind": "event", "key": "sample", "entity_id": event_id, "origin": "adopted"},
            {"kind": "property_group", "key": "Cart", "entity_id": group_id, "origin": "adopted"},
        ]
        event.update({"description": "Edited in PostHog", "tags": ["updated"], "owner": {"id": 72}})
        following, _, _ = engine.run_diff(
            tmp_path,
            engine.translate_in(desc, [engine.Binding(**b) for b in result["bindings"]], options),
            snapshot,
            credentials,
        )
        assert not following["errors"] and not following["changes"] and not following["drift"]
    assert all(method == "GET" for method, _ in requests)


@pytest.mark.skipif(
    not os.getenv("POSTHOG_STACK_MIRROR") or not shutil.which("tofu"), reason="Needs the installed development build"
)
def test_name_import_checks_the_bound_id_before_it_can_push(tmp_path: Path) -> None:
    identity: engine.Binding = {
        "kind": "model",
        "key": "daily_counts",
        "entity_id": "00000000-0000-4000-a000-000000000011",
        "status": "pending",
    }
    desc: StackDescription = {
        "version": 1,
        "resources": [
            {
                "kind": "model",
                "key": "daily_counts",
                "body": {"name": "daily_counts", "query": {"kind": "HogQLQuery", "query": "SELECT 1"}},
            }
        ],
    }
    view = {
        "id": "00000000-0000-4000-a000-000000000022",
        "name": "daily_counts",
        "query": {"kind": "HogQLQuery", "query": "SELECT 1"},
    }
    collection = "/api/projects/7/warehouse_saved_queries/"
    routes: dict[str, object] = {
        collection: {"results": [view], "next": None},
        collection + "?include_columns=false&search=daily_counts": {"results": [view], "next": None},
        collection + "00000000-0000-4000-a000-000000000022/": view,
    }
    with _project(routes) as (credentials, _):
        diff, saved, _ = engine.run_diff(
            tmp_path,
            engine.translate_in(desc, [identity], {"mirror": os.environ["POSTHOG_STACK_MIRROR"]}),
            None,
            credentials,
        )
    assert [error["code"] for error in diff["errors"]] == ["binding_conflict"] and not saved
    assert not ENGINE_WORDS.search(diff["errors"][0]["message"])


@pytest.mark.skipif(
    not os.getenv("POSTHOG_STACK_MIRROR") or not shutil.which("tofu"), reason="Needs the installed development build"
)
def test_event_that_appears_after_diff_requires_review_before_push(tmp_path: Path) -> None:
    desc: StackDescription = {
        "version": 1,
        "resources": [{"kind": "event", "key": "sample", "body": {"name": "sample"}}],
    }
    incoming = engine.translate_in(desc, [], {"mirror": os.environ["POSTHOG_STACK_MIRROR"]})
    collection = "/api/projects/7/event_definitions/"
    routes: dict[str, object] = {collection: {"results": [], "next": None}}
    with _project(routes) as (credentials, requests):
        diff, saved, _ = engine.run_diff(tmp_path, incoming, None, credentials)
        assert diff["errors"] == [] and diff["summary"]["create"] == 1
        routes[collection] = {
            "results": [{"name": "sample", "id": "00000000-0000-4000-a000-000000000031"}],
            "next": None,
        }
        result, _ = engine.run_push(tmp_path, incoming, saved, None, credentials)
        assert [e["code"] for e in result["errors"]] == ["stack_moved"] and not ENGINE_WORDS.search(
            result["errors"][0]["message"]
        )
    assert all(method == "GET" for method, _ in requests)


@pytest.mark.skipif(
    not os.getenv("POSTHOG_STACK_MIRROR") or not shutil.which("tofu"), reason="Needs the installed development build"
)
def test_snapshot_matches_the_installed_binary(tmp_path: Path) -> None:
    def structural(value: Any) -> Any:
        if isinstance(value, dict):
            return {
                key: structural(item)
                for key, item in value.items()
                if not (key in ("description", "description_kind") and isinstance(item, str))
            }
        if isinstance(value, list):
            return [structural(item) for item in value]
        return value

    incoming = engine.translate_in({"version": 1, "resources": []}, [], {})
    (tmp_path / "main.tf.json").write_text(json.dumps(incoming.config))
    cli = tmp_path / "offline.tfrc"
    cli.write_text(
        "provider_installation {\n filesystem_mirror {\n path = "
        + json.dumps(os.environ["POSTHOG_STACK_MIRROR"])
        + "\n }\n}"
    )
    env = {"HOME": str(tmp_path), "PATH": os.defpath, "TF_CLI_CONFIG_FILE": str(cli), "CHECKPOINT_DISABLE": "1"}
    tofu = shutil.which("tofu")
    assert tofu
    subprocess.run([tofu, "init", "-input=false", "-no-color"], env=env, cwd=tmp_path, capture_output=True, check=True)
    schema = subprocess.check_output([tofu, "providers", "schema", "-json"], env=env, cwd=tmp_path)
    snapshot = json.loads((Path(__file__).parents[1] / "provider_schema.json").read_bytes())
    assert structural(json.loads(schema)) == snapshot
