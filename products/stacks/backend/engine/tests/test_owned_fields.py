from typing import Any

import pytest

from products.stacks.backend import engine
from products.stacks.backend.engine.types import Json


def test_write_lock_uses_the_bound_events_declared_fields() -> None:
    body: dict[str, Json] = {"name": "checkout", "owner": None, "hidden": False, "tags": [], "property_groups": []}
    assert engine.owned_fields("event", body) == {"name", "hidden", "tags", "property_groups"}
    assert engine.owned_fields("event", {"name": "checkout"}) == {"name"}


@pytest.mark.parametrize(
    ("kind", "lifecycle_fields"),
    [
        (
            "survey",
            {
                "start_date": "2026-01-01T00:00:00Z",
                "end_date": "2026-01-10T00:00:00Z",
                "response_sampling_start_date": "2026-01-02T00:00:00Z",
            },
        ),
        (
            "experiment",
            {"conclusion": "won", "conclusion_comment": "Checkout completed more often."},
        ),
    ],
)
def test_lifecycle_definition_owns_only_the_fields_it_sets(kind: str, lifecycle_fields: dict[str, Json]) -> None:
    def config(body: dict[str, Json]) -> dict[str, Any]:
        translated = engine.translate_in(
            {"version": 1, "resources": [{"kind": kind, "key": "checkout", "body": body}]}, [], {}
        )
        return translated.config["resource"][f"posthog_{kind}"]["stack_checkout"]

    attributes = {"status": {"stopped": lifecycle_fields}} if kind == "experiment" else lifecycle_fields
    empty_bodies: list[dict[str, Json]] = [{}, dict.fromkeys(lifecycle_fields)]
    for empty in empty_bodies:
        assert engine.owned_fields(kind, empty).isdisjoint(lifecycle_fields)
        unchanged = config(empty)
        assert attributes.keys().isdisjoint(unchanged)
        assert attributes.keys().isdisjoint(unchanged.get("lifecycle", {}).get("ignore_changes", []))
    assert lifecycle_fields.keys() <= engine.owned_fields(kind, lifecycle_fields)
    configured = config(lifecycle_fields)
    assert {key: configured[key] for key in attributes} == attributes
    assert attributes.keys().isdisjoint(configured.get("lifecycle", {}).get("ignore_changes", []))


def test_owned_fields_includes_composed_and_dotted_paths_and_excludes_rollout() -> None:
    assert "tiles" in engine.owned_fields("dashboard", {"tiles": []})
    assert "tiles" not in engine.owned_fields("dashboard", {})
    alert = engine.owned_fields("alert", {})
    assert {"threshold.configuration.bounds.lower", "config.type"} <= alert
    assert "threshold.id" not in alert
    flag = engine.owned_fields("flag", {"active": True, "filters": {}})
    assert "name" in flag and flag.isdisjoint({"active", "filters", "rollout_percentage"})
    assert engine.owned_fields(
        "flag", {"filters": {"multivariate": {"variants": []}, "payloads": {}, "groups": [], "holdout": 3}}
    ) - flag == {"filters.multivariate", "filters.payloads"}
    assert "columns" not in engine.owned_fields("model", {"columns": {"n": "number"}})
    # PostHog gives a new survey a default appearance, so a definition that sets none leaves it editable.
    assert "appearance" not in engine.owned_fields("survey", {})
    assert "appearance" in engine.owned_fields("survey", {"appearance": {"position": "left"}})
    with pytest.raises(engine.EngineError):
        engine.owned_fields("unknown-example", {})


def test_source_write_lock_leaves_discovered_schemas_editable() -> None:
    payload: dict[str, Json] = {"host": "127.0.0.1", "password": {"$secret": "db_password"}, "schemas": []}
    fields = engine.owned_fields("source", {"payload": payload})
    assert fields == {"source_type", "prefix", "payload.host", "payload.password"}
    payload["schemas"] = [{"name": "customers", "should_sync": True}]
    assert engine.owned_fields("source", {"payload": payload}) == fields | {"payload.schemas"}
