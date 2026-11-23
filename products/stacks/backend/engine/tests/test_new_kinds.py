import os
import json
import shutil
from pathlib import Path
from time import monotonic
from urllib.parse import urlencode

import pytest

from products.stacks.backend.engine import EngineError, read_bindings, run_diff, run_push, translate_in, translate_out
from products.stacks.backend.engine.addresses import address, decode_address, event_link_address
from products.stacks.backend.engine.claims import saved_adoptions
from products.stacks.backend.engine.event_imports import event_imports
from products.stacks.backend.engine.natural_keys import natural_imports
from products.stacks.backend.engine.tests.test_translate_out import CAPTURED, ENGINE_WORDS, row
from products.stacks.backend.engine.types import Binding, EngineOptions, Json, ResourceDescription, StackDescription

from .test_binding_lifecycle import _project

GROUP_ID = "bb6538f7-9305-4579-8aaf-2383110b0a85"
EVENT_ID = "09f9870f-a9d8-44ef-876e-42916dcda820"


def _event(groups: list[Json]) -> ResourceDescription:
    return {
        "kind": "event",
        "key": "checkout / ${region}",
        "body": {"name": "checkout / ${region}", "property_groups": groups},
    }


def test_event_links_are_stable_and_do_not_appear_as_separate_definitions() -> None:
    group: ResourceDescription = {
        "kind": "property_group",
        "key": "Checkout",
        "body": {
            "name": "Checkout",
            "properties": [{"name": "tier", "property_type": "String", "enum": ["paid", "free"]}],
        },
    }
    reference: Json = {"$ref": {"kind": "property_group", "key": "Checkout"}}
    groups: list[Json] = [reference, GROUP_ID]
    event = _event(groups)
    description: StackDescription = {"version": 1, "resources": [group, event]}
    config = translate_in(description, [], {}).config
    resources = config["resource"]
    links = resources["posthog_event_schema"]
    assert len(links) == 2
    assert {link["property_group_id"] for link in links.values()} == {
        GROUP_ID,
        "${" + address("property_group", "Checkout") + ".id}",
    }
    assert {link["event_definition"] for link in links.values()} == {"${" + address("event", event["key"]) + ".id}"}
    assert resources["posthog_schema_property_group"][address("property_group", "Checkout").split(".")[1]][
        "properties"
    ] == [{"name": "tier", "property_type": "String"}]
    groups.reverse()
    assert translate_in(description, [], {}).config == config
    assert all(decode_address("posthog_event_schema." + label) == ("event", event["key"], True) for label in links)
    rows = [
        {
            "address": "posthog_event_schema." + label,
            "change": {
                "actions": ["create"],
                "before": None,
                "after": {"property_group_id": v["property_group_id"] if v["property_group_id"] == GROUP_ID else None},
            },
        }
        for label, v in links.items()
    ]
    diff = translate_out({"resource_changes": rows}, description)
    assert not diff["errors"] and diff["summary"]["update"] == 1
    assert {row["path"] for row in diff["changes"][0]["fields"]} == {"property_groups[0]", "property_groups[1]"}


@pytest.mark.parametrize(
    ("value", "path"),
    [
        ([{"$ref": {"kind": "model", "key": "x"}}], "property_groups[0]"),
        (["not-an-id"], "property_groups[0]"),
        ([GROUP_ID, GROUP_ID], "property_groups[1]"),
        ("", "property_groups"),
    ],
)
def test_invalid_event_group_names_the_body_path(value: Json, path: str) -> None:
    event = _event([])
    event["body"]["property_groups"] = value
    with pytest.raises(EngineError) as error:
        translate_in({"version": 1, "resources": [event]}, [], {})
    assert error.value.errors[0]["path"] == path
    assert not ENGINE_WORDS.search(str(error.value))


def test_named_import_claims_use_read_uuid_and_preserve_event_names() -> None:
    event = _event([])
    binding: Binding = {"kind": "event", "key": event["key"], "entity_id": EVENT_ID, "status": "pending"}
    config = translate_in({"version": 1, "resources": [event]}, [binding], {}).config
    (block,) = config["import"]
    assert block["id"] == "${var.stack_project_id}/checkout / $${region}"
    assert "stack_project_id" in config["variable"]
    change = {
        "actions": ["update"],
        "importing": {"id": "7/checkout / ${region}"},
        "before": {"id": EVENT_ID},
        "after": {"id": EVENT_ID},
    }
    assert list(saved_adoptions({"resource_changes": [{"address": block["to"], "change": change}]})) == [
        ("event", event["key"], EVENT_ID)
    ]
    shown = translate_out(
        {"resource_changes": [{"address": block["to"], "change": change}]}, {"version": 1, "resources": [event]}
    )
    assert shown["changes"][0].get("entity_id") == EVENT_ID
    event["body"]["name"] = "different"
    with pytest.raises(EngineError) as exc:
        translate_in({"version": 1, "resources": [event]}, [binding], {})
    assert not ENGINE_WORDS.search(str(exc.value))


def test_new_kinds_map_api_bodies_and_composed_model_fields() -> None:
    model: ResourceDescription = {
        "kind": "model",
        "key": "orders",
        "body": {
            "name": "orders",
            "query": {"kind": "HogQLQuery", "query": "select 1 as k"},
            "is_materialized": True,
            "sync_frequency": "1hour",
            "incremental": {"enabled": True, "incremental_key": "k", "unique_key": ["k"], "lookback_seconds": 0},
            "columns": {"k": "number"},
        },
    }
    reference: Json = {"$ref": {"kind": "model", "key": "orders"}}
    check: ResourceDescription = {
        "kind": "check",
        "key": "has-rows",
        "body": {"subject_type": "view", "subject_uuid": reference, "check_type": "row_count", "config": {"min": 1}},
    }
    endpoint: ResourceDescription = {
        "kind": "endpoint",
        "key": "read-orders",
        "body": {
            "name": "read-orders",
            "query": {"kind": "HogQLQuery", "query": "select * from orders"},
            "is_active": True,
        },
    }
    metric: ResourceDescription = {
        "kind": "metric",
        "key": "revenue",
        "body": {
            "name": "revenue",
            "description": "Order revenue",
            "definition": {"kind": "HogQLQuery", "query": "select 1"},
            "owner": None,
        },
    }
    config = translate_in({"version": 1, "resources": [model, check, endpoint, metric]}, [], {}).config["resource"]
    attrs = config["posthog_warehouse_saved_query"]["stack_orders"]
    assert attrs["incremental"] == model["body"]["incremental"]
    assert attrs["is_materialized"] is True and attrs["sync_frequency"] == "1hour" and "columns" not in attrs
    assert json.loads(attrs["query_json"]) == model["body"]["query"]
    assert (
        config["posthog_data_quality_check"]["stack_has-rows"]["subject_uuid"]
        == "${posthog_warehouse_saved_query.stack_orders.id}"
    )
    assert json.loads(config["posthog_endpoint"]["stack_read-orders"]["query_json"]) == endpoint["body"]["query"]
    assert config["posthog_data_catalog_metric"]["stack_revenue"]["owner"] == ""
    assert (
        json.loads(config["posthog_data_catalog_metric"]["stack_revenue"]["definition_json"])
        == metric["body"]["definition"]
    )


def test_only_declared_event_metadata_appears_in_drift() -> None:
    event = _event([])
    event["body"].update({"tags": [], "owner": None})
    found = row(
        address("event", event["key"]),
        ["update"],
        {"description": "First", "owner": 5, "tags": []},
        {"description": "Edited in PostHog", "owner": 9, "tags": ["external"]},
    )
    diff = translate_out({"resource_drift": [found]}, {"version": 1, "resources": [event]})
    assert diff["drift"] == [
        {"kind": "event", "key": event["key"], "fields": [{"path": "tags", "pushed": [], "found": ["external"]}]}
    ]


@pytest.mark.skipif(
    not os.environ.get("POSTHOG_STACK_MIRROR") or not shutil.which("tofu"),
    reason="Needs the installed stack mirror and binary.",
)
@pytest.mark.parametrize("release", [False, True])
def test_event_membership_edit_detaches_the_link_and_event_release_preserves_it(tmp_path: Path, release: bool) -> None:
    event = _event([])
    link_id = "f4ec7bbf-d3b0-47ae-af73-f6b1f3371d0c"
    primary = address("event", event["key"])
    link = event_link_address(event["key"], GROUP_ID, literal=True)
    attrs = {
        "project_id": "7",
        "id": EVENT_ID,
        "name": event["key"],
        "tags": [],
        "enforcement_mode": "reject",
        "description": "Purchased",
        "verified": False,
        "hidden": False,
        "owner": None,
    }
    event["body"].update({"enforcement_mode": "reject", "description": "Purchased"})
    linked = {"project_id": "7", "event_definition": EVENT_ID, "property_group_id": GROUP_ID, "id": link_id}
    snapshot = json.dumps(
        {
            "version": 4,
            "terraform_version": "1.12.6",
            "serial": 2,
            "lineage": "41895877-37b1-4397-8993-a1452848af2c",
            "resources": [
                {
                    "mode": "managed",
                    "type": addr.split(".")[0],
                    "name": addr.split(".")[1],
                    "provider": 'provider["registry.opentofu.org/posthog/posthog"]',
                    "instances": [{"schema_version": 0, "attributes": values, "sensitive_attributes": []}],
                }
                for addr, values in ((primary, attrs), (link, linked))
            ],
        }
    ).encode()
    description: StackDescription = {"version": 1, "resources": [] if release else [event]}
    options: EngineOptions = {"mirror": os.environ["POSTHOG_STACK_MIRROR"], "refresh": False}
    engine_input = translate_in(description, [{"kind": "event", "key": event["key"], "entity_id": EVENT_ID}], options)
    route = f"/api/projects/7/event_schemas/{link_id}/"
    routes: dict[str, object] = {
        "DELETE " + route: {},
        "/api/projects/7/event_schemas/": {"results": [], "next": None},
        "/api/projects/7/event_definitions/by_name/?" + urlencode({"name": event["key"]}): attrs,
    }
    with _project(routes) as (credentials, requests):
        diff, saved, _ = run_diff(tmp_path, engine_input, snapshot, credentials)
        assert diff["errors"] == []
        assert [c["action"] for c in diff["changes"]] == (["release"] if release else ["update"])
        if not release:
            assert diff["changes"][0]["fields"] == [
                {"path": "property_groups", "before": GROUP_ID, "after": None, "sensitive": False}
            ]
        assert not ENGINE_WORDS.search(json.dumps(diff))
        pushed, updated = run_push(tmp_path, engine_input, saved, snapshot, credentials)
        assert pushed["errors"] == [], requests
        assert read_bindings(updated) == (
            [] if release else [{"kind": "event", "key": event["key"], "entity_id": EVENT_ID}]
        )
        if not release:
            stored = next(
                resource
                for resource in json.loads(updated)["resources"]
                if resource["type"] == "posthog_event_definition"
            )
            assert stored["instances"][0]["attributes"]["manages_enforcement_mode"] is True
        assert [r for r in requests if r[0] != "GET"] == ([] if release else [("DELETE", route)])


@pytest.mark.parametrize(
    ("kind", "loss"),
    [
        ("event", "schema links"),
        ("property_group", "links to events"),
        ("model", "materialized data and run history"),
        ("endpoint", "version history"),
        ("metric", "review"),
        ("check", "run history"),
    ],
)
def test_new_kind_recreate_and_error_vocabulary(kind: str, loss: str) -> None:
    entry = {
        "address": address(kind, "example"),
        "change": {"actions": ["delete", "create"], "before": {"name": "Before"}, "after": {"name": "After"}},
    }
    diagnostic = {**CAPTURED["crash"][0], "address": entry["address"]}
    diff = translate_out({"resource_changes": [entry], "diagnostics": [diagnostic]}, {"version": 1, "resources": []})
    (change,) = diff["changes"]
    assert change["action"] == "recreate" and change["loses"] and loss in change["loses"]
    assert (diff["errors"][0]["code"], diff["errors"][0]["kind"], diff["errors"][0]["key"]) == (
        "stack_interrupted",
        kind,
        "example",
    )
    assert not ENGINE_WORDS.search(json.dumps(diff))


def test_composed_event_link_diagnostic_vocabulary() -> None:
    diagnostic = {**CAPTURED["validation"][0], "address": event_link_address("checkout", "Cart")}
    diff = translate_out({"diagnostics": [diagnostic]}, {"version": 1, "resources": []})
    (error,) = diff["errors"]
    assert (error["code"], error["kind"], error["key"]) == ("body_invalid", "event", "checkout")
    assert not ENGINE_WORDS.search(json.dumps(error))


def test_new_kind_change_summary_vocabulary() -> None:
    moved = row(address("endpoint", "recent"), ["no-op"], {}, {})
    moved["previous_address"] = address("endpoint", "old")
    entries = [
        row(address("event", "sample"), ["forget"], {}, None),
        row(address("model", "orders"), ["delete"], {}, None),
        row(address("check", "nulls"), ["update"], {"enabled": True}, {"enabled": False}),
        row(address("metric", "total"), ["create"], None, {}),
        row(
            address("property_group", "Cart"), ["no-op"], {"id": GROUP_ID}, {"id": GROUP_ID}, importing={"id": "7/Cart"}
        ),
        moved,
    ]
    diff = translate_out({"resource_changes": entries}, {"version": 1, "resources": []})
    assert not diff["errors"]
    assert {change["action"] for change in diff["changes"]} == {
        "adopt",
        "create",
        "release",
        "remove",
        "rename",
        "update",
    }
    assert not ENGINE_WORDS.search(json.dumps(diff))


@pytest.mark.parametrize(
    "duplicate_in_posthog", [False, True], ids=["definitions-share-name", "live-entities-share-name"]
)
def test_ambiguous_adoption_diagnostic_vocabulary(duplicate_in_posthog: bool) -> None:
    if duplicate_in_posthog:
        definitions: list[ResourceDescription] = [{"kind": "model", "key": "orders", "body": {"name": "orders"}}]
        routes = {
            "/api/projects/7/warehouse_saved_queries/": [{"id": id_, "name": "orders"} for id_ in [EVENT_ID, GROUP_ID]]
        }
    else:
        definitions = [{"kind": "survey", "key": key, "body": {"name": "Experience"}} for key in ["first", "second"]]
        routes = {}
    incoming = translate_in({"version": 1, "resources": definitions}, [], {})
    with _project(routes) as (credentials, _), pytest.raises(EngineError) as exc:
        natural_imports(incoming, set(), credentials)
    (error,) = exc.value.errors
    assert error["code"] == "binding_conflict" and error["kind"] == definitions[-1]["kind"]
    assert not ENGINE_WORDS.search(json.dumps(error))


def test_unmanaging_a_link_leaves_the_event_in_code() -> None:
    entry = {
        "address": event_link_address("example", "group"),
        "change": {"actions": ["forget"], "before": {"property_group_id": GROUP_ID}, "after": None},
    }
    diff = translate_out({"resource_changes": [entry]}, {"version": 1, "resources": []})
    (change,) = diff["changes"]
    assert (
        change["action"] == "update"
        and change["summary"] == "The property group link stays in PostHog and is no longer managed in code."
    )
    assert not ENGINE_WORDS.search(json.dumps(diff))


def test_clearing_a_metric_owner_shows_the_api_null() -> None:
    entry = {
        "address": address("metric", "example"),
        "change": {"actions": ["update"], "before": {"owner": "member@example.com"}, "after": {"owner": ""}},
    }
    diff = translate_out({"resource_changes": [entry]}, {"version": 1, "resources": []})
    assert diff["changes"][0]["fields"] == [
        {"path": "owner", "before": "member@example.com", "after": None, "sensitive": False}
    ]


def test_literal_group_import_uses_its_api_name_and_checks_both_ids() -> None:
    event = _event([GROUP_ID])
    desc: StackDescription = {"version": 1, "resources": [event]}
    engine_input = translate_in(desc, [], {})
    known = {address("event", event["key"]): EVENT_ID}
    link = {
        "id": "03bcdbf0-06e4-4808-946e-a3b91424f906",
        "event_definition": EVENT_ID,
        "property_group": {"id": GROUP_ID, "name": "Cart / items"},
    }
    page = f"/api/projects/7/event_schemas/?event_definition={EVENT_ID}"
    other_event = {**link, "event_definition": GROUP_ID}
    routes = {
        page: {"results": [other_event, link], "next": "?cursor=second"},
        "/api/projects/7/event_schemas/?cursor=second": {"results": [link], "next": None},
    }
    target = event_link_address(event["key"], GROUP_ID, literal=True)
    with _project(routes) as (credentials, requests):
        assert event_imports(engine_input, set(), known, credentials, monotonic() + 5) == [
            {"to": target, "id": "checkout%20%2F%20%24%7Bregion%7D/Cart%20%2F%20items"}
        ]
        assert not event_imports(engine_input, {target}, known, credentials, monotonic() + 5)
    assert len(requests) == 2


@pytest.mark.skipif(
    not os.getenv("POSTHOG_STACK_MIRROR") or not shutil.which("tofu"), reason="Needs the installed development build"
)
@pytest.mark.parametrize("literal_first", [True, False], ids=["literal-to-reference", "reference-to-literal"])
def test_switching_an_existing_membership_keeps_its_link_without_a_write(tmp_path: Path, literal_first: bool) -> None:
    event = {"name": "checkout", "id": EVENT_ID, "tags": [], "enforcement_mode": "allow"}
    group = {"name": "Cart", "id": GROUP_ID, "description": "", "properties": []}
    link = {"id": "57293013-cf01-46d0-be5b-8acb55f38bd5", "event_definition": EVENT_ID, "property_group": group}
    root = "/api/projects/7/"
    routes = {
        root + "event_definitions/": {"results": [event], "next": None},
        root + "event_definitions/by_name/?name=checkout": event,
        root + "schema_property_groups/": {"results": [group], "next": None},
        root + f"schema_property_groups/{GROUP_ID}/": group,
        root + "event_schemas/": {"results": [link], "next": None},
        root + f"event_schemas/?event_definition={EVENT_ID}": {"results": [link], "next": None},
        root + f"event_schemas/{link['id']}/": link,
    }
    reference: Json = {"$ref": {"kind": "property_group", "key": "Cart"}}
    desc: StackDescription = {
        "version": 1,
        "resources": [
            {
                "kind": "event",
                "key": "checkout",
                "body": {"name": "checkout", "property_groups": [GROUP_ID if literal_first else reference]},
            },
            {"kind": "property_group", "key": "Cart", "body": {"name": "Cart"}},
        ],
    }
    options: EngineOptions = {"mirror": os.environ["POSTHOG_STACK_MIRROR"]}
    with _project(routes) as (credentials, requests):
        first = translate_in(desc, [], options)
        original, saved, _ = run_diff(tmp_path, first, None, credentials)
        assert not original["errors"] and saved, requests
        pushed, record = run_push(tmp_path, first, saved, None, credentials)
        assert not pushed["errors"] and record
        desc["resources"][0]["body"]["property_groups"] = [reference if literal_first else GROUP_ID]
        new_input = translate_in(desc, [Binding(**b) for b in pushed["bindings"]], options)
        changed, saved, _ = run_diff(tmp_path, new_input, record, credentials)
        assert (changed["changes"], changed["errors"], changed["drift"]) == ([], [], [])
        pushed_again, updated = run_push(tmp_path, new_input, saved, record, credentials)
        assert pushed_again["errors"] == []
        following, _, _ = run_diff(tmp_path, new_input, updated, credentials)
        assert (following["changes"], following["errors"], following["drift"]) == ([], [], [])
        assert all(method == "GET" for method, _ in requests)


@pytest.mark.parametrize("conflict", ["duplicate_reference", "occupied_link", "contradictory_page", "malformed_link"])
def test_event_link_import_refuses_conflicting_or_unreadable_membership(conflict: str) -> None:
    reference: Json = {"$ref": {"kind": "property_group", "key": "Cart"}}
    groups: list[Json] = [GROUP_ID, reference] if conflict == "duplicate_reference" else [GROUP_ID]
    event = _event(groups)
    group: ResourceDescription = {"kind": "property_group", "key": "Cart", "body": {"name": "Cart"}}
    incoming = translate_in({"version": 1, "resources": [event, group]}, [], {})
    link_id = "68654285-b26b-47a7-8b3f-a77233ca0c2f"
    by_ref = event_link_address(event["key"], "Cart")
    link: dict[str, object] = {
        "id": link_id,
        "event_definition": EVENT_ID,
        "property_group": {"name": "Cart", "id": GROUP_ID},
    }
    known = {address("event", event["key"]): EVENT_ID, address("property_group", "Cart"): GROUP_ID, by_ref: link_id}
    rows = [link]
    if conflict == "contradictory_page":
        rows.append({**link, "id": "25382e3c-63d5-4b05-9681-1b875512b693"})
    if conflict == "malformed_link":
        rows = [{**link, "property_group": None}]
    route = f"/api/projects/7/event_schemas/?event_definition={EVENT_ID}"
    with _project({route: {"results": rows, "next": None}}) as (credentials, _), pytest.raises(EngineError) as exc:
        event_imports(
            incoming,
            {by_ref} if conflict in ("occupied_link", "duplicate_reference") else set(),
            known,
            credentials,
            monotonic() + 5,
        )
    assert exc.value.errors[0]["code"] == ("lookup_failed" if conflict == "malformed_link" else "binding_conflict")
    assert not ENGINE_WORDS.search(str(exc.value))
