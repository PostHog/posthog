import os
import shutil
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from products.stacks.backend.engine import StackDescription, run_diff, run_push, translate_in, validate_description
from products.stacks.backend.engine.tests.test_api_normalization import Response, loopback_api
from products.stacks.backend.engine.types import Binding, EngineOptions


@pytest.mark.parametrize("value", [[{"kind": "model", "key": "absent"}], [{"kind": "model"}], None])
def test_invalid_declared_dependency_names_the_definition(value: Any) -> None:
    desc: StackDescription = {
        "version": 1,
        "resources": [{"kind": "model", "key": "existing", "body": {}, "depends_on": value}],
    }
    (error,) = validate_description(desc, [])
    assert (error["code"], error["kind"], error["key"]) == ("invalid_definition", "model", "existing")
    assert error["path"].startswith("depends_on")


def test_declared_dependencies_and_body_references_cannot_form_a_cycle() -> None:
    description: StackDescription = {
        "version": 1,
        "resources": [
            {"kind": "insight", "key": "one", "body": {}, "depends_on": [{"kind": "insight", "key": "two"}]},
            {"kind": "insight", "key": "two", "body": {"query": {"id": {"$ref": {"kind": "insight", "key": "one"}}}}},
        ],
    }
    (error,) = validate_description(description, [])
    assert (error["code"], error["kind"]) == ("reference_cycle", "insight")
    assert error["key"] in {"one", "two"}


@pytest.mark.skipif(
    not os.getenv("POSTHOG_STACK_MIRROR") or not shutil.which("tofu"), reason="Needs the local mirror and OpenTofu"
)
def test_models_and_metric_are_created_in_sql_dependency_order_and_removed_in_reverse(tmp_path: Path) -> None:
    models = "/api/projects/7/warehouse_saved_queries/"
    metrics = "/api/projects/7/data_catalog/metrics/"
    by_name: dict[str, dict[str, Any]] = {}
    operations: list[tuple[str, str]] = []
    requires = {"summary": "base", "count": "summary"}

    def route(method: str, path: str, body: dict[str, Any]) -> Response:
        if method == "GET":
            if path in (models, metrics):
                return 200, {"results": list(by_name.values()) if path == models else [], "next": None}
            for name, row in by_name.items():
                if path in (models + row["id"] + "/", metrics + name + "/"):
                    return 200, row
        elif method == "POST" and path in (models, metrics):
            name = body["name"]
            if requires.get(name) and requires[name] not in by_name:
                return 400, {"detail": "The query references a model that does not exist."}
            assert "depends_on" not in body
            row = {"id": str(UUID(int=len(by_name) + 1)), "status": "approved", "created_source": "user", **body}
            by_name[name] = row
            operations.append((method, name))
            return 201, row
        elif method == "DELETE":
            for name, row in by_name.items():
                if path in (models + row["id"] + "/", metrics + name + "/"):
                    if any(dep == name and dependent in by_name for dependent, dep in requires.items()):
                        return 409, {"detail": "A dependent query still exists."}
                    del by_name[name]
                    operations.append((method, name))
                    return 204, None
        return 404, {"detail": "Unknown route."}

    desc: StackDescription = {
        "version": 1,
        "resources": [
            {
                "kind": "metric",
                "key": "count",
                "depends_on": [{"kind": "model", "key": "summary"}],
                "body": {
                    "name": "count",
                    "description": "Number of rows in the summary model.",
                    "definition": {"kind": "HogQLQuery", "query": "SELECT count() FROM summary"},
                },
            },
            {
                "kind": "model",
                "key": "summary",
                "depends_on": [{"kind": "model", "key": "base"}],
                "body": {"name": "summary", "query": {"kind": "HogQLQuery", "query": "SELECT * FROM base"}},
            },
            {
                "kind": "model",
                "key": "base",
                "body": {"name": "base", "query": {"kind": "HogQLQuery", "query": "SELECT 1 AS value"}},
            },
        ],
    }
    options: EngineOptions = {"mirror": os.environ["POSTHOG_STACK_MIRROR"]}
    incoming = translate_in(desc, [], options)
    with loopback_api(route) as credentials:
        review, saved, _ = run_diff(tmp_path, incoming, None, credentials)
        assert not review["errors"]
        pushed, record = run_push(tmp_path, incoming, saved, None, credentials)
        assert not pushed["errors"]
        assert operations == [("POST", "base"), ("POST", "summary"), ("POST", "count")]

        empty = translate_in({"version": 1, "resources": []}, [Binding(**b) for b in pushed["bindings"]], options)
        review, saved, _ = run_diff(tmp_path, empty, record, credentials)
        assert not review["errors"] and review["summary"]["remove"] == 3
        removed, _ = run_push(tmp_path, empty, saved, record, credentials)
        assert not removed["errors"] and not removed["bindings"]
    assert operations[3:] == [("DELETE", "count"), ("DELETE", "summary"), ("DELETE", "base")]
