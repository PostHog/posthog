import json
import base64
import shutil
import subprocess
from pathlib import Path

import pytest

from products.stacks.backend.engine import translate_in
from products.stacks.backend.engine.addresses import address, decode_address
from products.stacks.backend.engine.tests.test_translate_out import ENGINE_WORDS
from products.stacks.backend.engine.types import Binding, EngineError, EngineOptions, Identity, Json, StackDescription

FIXTURE = Path(__file__).parent / "fixtures" / "description.json"


def test_tiles_do_not_introduce_a_cycle_and_keep_display_order() -> None:
    resources = translate_in(json.loads(FIXTURE.read_bytes()), [], {}).config["resource"]
    layout = resources["posthog_dashboard_layout"]["stack_sample"]
    assert layout["dashboard_id"] == "${posthog_dashboard.stack_sample.id}"
    assert [tile.get("insight_id") for tile in layout["tiles"]] == [
        "${posthog_insight.stack_volume.id}",
        "${posthog_insight.stack_duration.id}",
        None,
    ]
    assert layout["tiles"][2]["text_body"] == "Show $${this} and %%{that} literally."
    assert json.loads(layout["tiles"][0]["layouts_json"])["sm"]["w"] == 6
    assert "tiles" not in resources["posthog_dashboard"]["stack_sample"]
    assert resources["posthog_alert"]["stack_volume-dip"]["threshold_lower"] == 3
    assert resources["posthog_alert"]["stack_volume-dip"]["insight"] == "${posthog_insight.stack_volume.id}"


@pytest.mark.skipif(not shutil.which("tofu"), reason="OpenTofu is unavailable")
def test_reference_values_survive_json_encoding_in_the_expression_evaluator(tmp_path: Path) -> None:
    tofu = shutil.which("tofu")
    assert tofu
    desc = json.loads(FIXTURE.read_bytes())
    body = desc["resources"][2]["body"]
    literals = ["${var.title}", "%{if true}", "$${example}", "%%{if true}", 'line\n"quoted"\\backslash', "á🙂"]
    secret_name = 'service/"${region}"'
    body["filters"] = {
        "${object_key}": literals,
        "ids": [{"$ref": {"kind": kind, "key": key}} for kind, key in (("alert", "volume-dip"), ("insight", "volume"))],
        "value": {"$secret": secret_name},
    }
    translated = translate_in(desc, [], {})
    template = translated.config["resource"]["posthog_hog_function"]["stack_notify"]["filters_json"]
    template = template.replace("posthog_alert.stack_volume-dip.id", "local.alert_id").replace(
        "posthog_insight.stack_volume.id", "local.insight_id"
    )
    string_id = 'id"with\\punctuation'
    secret = 'sample"${literal}'
    (tmp_path / "main.tf.json").write_text(
        json.dumps(
            {
                "locals": {"alert_id": string_id, "insight_id": 42, "filtered": template},
                "variable": translated.config["variable"],
            }
        )
    )
    (tmp_path / "inputs.auto.tfvars.json").write_text(json.dumps({"stack_secrets": {secret_name: secret}}))
    result = subprocess.run(
        [tofu, "console", "-no-color"],
        input="base64encode(nonsensitive(local.filtered))\n",
        capture_output=True,
        text=True,
        cwd=tmp_path,
        check=True,
    )
    assert json.loads(base64.b64decode(json.loads(result.stdout))) == {
        "${object_key}": literals,
        "ids": [string_id, 42],
        "value": secret,
    }


def test_binding_changes_and_removal_guards() -> None:
    desc = json.loads(FIXTURE.read_bytes())
    desc["resources"].append(
        {"kind": "flag", "key": "Checkout_v2", "body": {"active": True, "filters": {"groups": []}}}
    )
    old = 'posthog_insight.old["email"]'
    identity: Identity = {"kind": "insight", "key": "duration"}
    config = translate_in(
        desc,
        [{"kind": "dashboard", "key": "sample", "entity_id": 11, "status": "pending"}],
        {
            "rename_map": {old: identity},
            "existing": [{"kind": "flag", "key": "Checkout_v2", "entity_id": 7}],
            "detach": [{"kind": "dashboard", "key": "previous"}],
        },
    ).config
    flag = address("flag", "Checkout_v2")
    assert decode_address(flag) == ("flag", "Checkout_v2", False)
    assert config["moved"] == [{"from": old, "to": address(**identity)}]
    assert {entry["to"]: entry["id"] for entry in config["import"]} == {
        address("dashboard", "sample"): "11",
        address("dashboard", "sample", layout=True): "11",
        flag: "7",
    }
    assert config["removed"] == [
        {"from": address("dashboard", "previous", layout=layout), "lifecycle": {"destroy": False}}
        for layout in (False, True)
    ]
    assert config["resource"]["posthog_alert"]["stack_volume-dip"]["lifecycle"]["prevent_destroy"]
    flag_config = config["resource"]["posthog_feature_flag"][flag.split(".")[1]]
    assert set(flag_config["lifecycle"]["ignore_changes"]) == {"active", "rollout_percentage"}
    assert flag_config["active"] is True
    assert json.loads(flag_config["filters"]) == {"groups": []}
    assert flag_config["owned_filter_keys"] == []


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("insight", {"$ref": {"kind": "insight", "key": "missing"}}, "reference_missing"),
        ("insight", {"$ref": {"kind": "insight", "key": "duration", "attr": "unavailable"}}, "reference_missing"),
        ("threshold", {"configuration": {"type": "absolute"}, "name": "Separate threshold"}, "invalid_definition"),
        ("config", {"type": "FunnelsAlertConfig"}, "invalid_definition"),
    ],
)
def test_invalid_alert_field_names_the_definition(field: str, value: object, code: str) -> None:
    desc = json.loads(FIXTURE.read_bytes())
    desc["resources"][0]["body"][field] = value
    with pytest.raises(EngineError) as err:
        translate_in(desc, [], {})
    error = err.value.errors[0]
    assert (error["kind"], error["key"], error["code"]) == ("alert", "volume-dip", code)
    assert error["path"].split(".")[0] == field


def test_deeply_nested_body_is_rejected_as_a_definition_error() -> None:
    query: dict = {"kind": "HogQLQuery"}
    for _ in range(600):
        query = {"kind": "Nested", "source": query}
    desc = json.loads(FIXTURE.read_bytes())
    desc["resources"][3]["body"]["query"] = query
    with pytest.raises(EngineError) as err:
        translate_in(desc, [], {})
    error = err.value.errors[0]
    assert (error["kind"], error["key"], error["code"]) == ("insight", "duration", "invalid_definition")


def test_source_and_destination_secrets_are_resolved_outside_the_definition() -> None:
    desc = json.loads(FIXTURE.read_bytes())
    desc["resources"][2]["body"]["inputs"] = {"token": {"value": {"$secret": "TOKEN"}}, "public": {"value": "Yellow"}}
    payload: dict[str, Json] = {
        "host": "example.com",
        "password": {"$secret": "PASSWORD"},
        "schemas": [{"name": "orders", "should_sync": True}],
    }
    source = {"kind": "source", "key": "orders", "body": {"source_type": "Postgres", "payload": payload}}
    desc["resources"].append(source)
    translated = translate_in(desc, [], {})
    assert translated.secret_names == {"PASSWORD", "TOKEN"}
    assert translated.config["variable"]["stack_secrets"]["sensitive"]
    resources = translated.config["resource"]
    destination = resources["posthog_hog_function"]["stack_notify"]
    assert json.loads(destination["inputs_json"]) == {"public": {"value": "Yellow"}}
    assert "TOKEN" in destination["sensitive_inputs_json"]
    assert resources["posthog_external_data_source"]["stack_orders"]["schemas"] == ["orders"]
    payload["password"] = "example"
    with pytest.raises(EngineError) as exc:
        translate_in(desc, [], {})
    assert exc.value.errors[0]["path"] == "payload.password"
    desc["resources"].remove(source)
    destination_body = desc["resources"][2]["body"]
    destination_body["inputs_schema"] = [{"key": "token", "type": "string", "secret": True}]
    destination_body["inputs"]["token"]["value"] = "example"
    with pytest.raises(EngineError) as exc:
        translate_in(desc, [], {})
    assert exc.value.errors[0]["path"] == "inputs.token"


@pytest.mark.parametrize(
    ("bindings", "options"),
    [
        ([], {"rename_map": []}),
        ([], {"rename_map": {"posthog_dashboard.old": "new"}}),
        ([], {"rename_map": {"posthog_dashboard.old": {"key": "new"}}}),
        ([], {"rename_map": {"posthog_dashboard.old": {"kind": "dashboard"}}}),
        ([], {"rename_map": {"posthog_dashboard.old": {"kind": [], "key": "new"}}}),
        ([], {"detach": None}),
        ([], {"detach": [{"kind": "dashboard", "key": []}]}),
        ([], {"existing": [None]}),
        ([], {"existing": [{"kind": "flag", "key": "unused", "entity_id": {}}]}),
        ([], {"claimed": [{"kind": "dashboard", "entity_id": 4, "stack": "other"}]}),
        ([], {"claimed": [{"kind": [], "entity_id": [], "stack": "other", "repository": False}]}),
        (None, {}),
        (["dashboard"], {}),
        ([{"kind": "dashboard", "key": "sample", "entity_id": True}], {}),
        ([{"kind": "dashboard", "key": "sample", "entity_id": 17, "origin": "unknown"}], {}),
        ([{"kind": "dashboard", "key": "sample", "entity_id": 17, "status": []}], {}),
        ([], {"timeout_seconds": True}),
        ([], {"timeout_seconds": float("nan")}),
        ([], {"timeout_seconds": 0}),
        ([], {"binary": []}),
        ([], {"mirror": {}}),
        ([], {"refresh": "yes"}),
        ([], {"allow_registry": 0}),
        ([], None),
    ],
)
def test_malformed_service_input_names_the_option(bindings: list[Binding], options: EngineOptions) -> None:
    with pytest.raises(EngineError) as exc:
        translate_in({"version": 1, "resources": []}, bindings, options)
    error = exc.value.errors[0]
    assert error["code"] == "invalid_definition"
    assert error["path"] == (next(iter(options), "bindings") if isinstance(options, dict) else "options")
    assert not ENGINE_WORDS.search(error["message"])


def test_removal_policy_uses_the_binding_origin_and_preserves_renames() -> None:
    bindings: list[Binding] = [
        {"kind": "dashboard", "key": "adopted", "entity_id": 1, "origin": "adopted"},
        {"kind": "dashboard", "key": "legacy", "entity_id": 2},
        {"kind": "source", "key": "warehouse", "entity_id": "source-1", "origin": "created"},
        {"kind": "dashboard", "key": "old", "entity_id": 3, "origin": "adopted"},
    ]
    target: Identity = {"kind": "dashboard", "key": "new"}
    old = address("dashboard", "old")
    description: StackDescription = {"version": 1, "resources": [{**target, "body": {"name": "New"}}]}
    config = translate_in(description, bindings, {"rename_map": {old: target}}).config
    assert config["removed"] == [
        {"from": name, "lifecycle": {"destroy": False}}
        for name in (
            address("dashboard", "adopted"),
            address("dashboard", "adopted", layout=True),
            address("dashboard", "old", layout=True),
            address("source", "warehouse"),
        )
    ]
    assert config["moved"] == [{"from": old, "to": address(**target)}]
    assert config["resource"]["posthog_dashboard"]["stack_new"]["lifecycle"]["prevent_destroy"]
