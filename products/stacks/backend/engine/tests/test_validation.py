from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from products.stacks.backend.engine import translate_in, validate_description
from products.stacks.backend.engine.tests.test_translate_out import ENGINE_WORDS
from products.stacks.backend.engine.types import EngineError, Json, StackDescription
from products.stacks.backend.engine.validation import MAX_DESCRIPTION_BYTES, MAX_DESCRIPTION_DEPTH, MAX_RESOURCES


def _one(kind: str, body: dict[str, Json]) -> StackDescription:
    return {"version": 1, "resources": [{"kind": kind, "key": "sample", "body": body}]}


def _invalid(description: Any, code: str, path: str | None = None) -> None:
    errors = validate_description(description, [])
    assert errors and errors[0]["code"] == code
    if path:
        assert errors[0]["path"] == path
    assert not ENGINE_WORDS.search(errors[0]["message"])
    with pytest.raises(EngineError) as caught:
        translate_in(description, [], {})
    assert caught.value.errors == errors


@pytest.mark.parametrize(
    ("kind", "body", "path"),
    [
        ("source", {"payload": {"password": "example-private"}}, "payload.password"),
        ("source", {"payload": {"connection": {"$secret": "S", "other": "example-private"}}}, "payload.connection"),
        ("source", {"payload": {"host": {"password": "example-private"}}}, "payload.host"),
        (
            "destination",
            {"inputs_schema": [{"key": "login", "secret": True}], "inputs": {"login": {"value": "example-private"}}},
            "inputs.login",
        ),
        (
            "destination",
            {
                "inputs_schema": [{"key": "login", "secret": True}],
                "inputs": {"login": {"value": {"metadata": {"$secret": "OTHER"}, "token": "example-private"}}},
            },
            "inputs.login",
        ),
        (
            "destination",
            {
                "inputs_schema": [{"key": "login", "secret": True}],
                "inputs": {"login": {"value": {"$secret": "S"}, "note": "example-private"}},
            },
            "inputs.login",
        ),
        (
            "destination",
            {"inputs_schema": [{"key": "login", "secret": True, "default": "example-private"}]},
            "inputs_schema[0].default",
        ),
        ("destination", {"inputs": {"apiKey": {"value": "example-private"}}}, "inputs.apiKey"),
        (
            "destination",
            {"inputs": {"headers": {"value": {"Authorization": "example-private"}}}},
            "inputs.headers.value.Authorization",
        ),
        (
            "destination",
            {
                "mappings": [
                    {
                        "inputs_schema": [{"key": "login", "secret": True}],
                        "inputs": {"login": {"value": "example-private"}},
                    }
                ]
            },
            "mappings[0].inputs.login",
        ),
    ],
)
def test_rejects_inline_secrets_before_storage(kind: str, body: dict[str, Json], path: str) -> None:
    desc = _one(kind, body)
    errors = validate_description(desc, [])
    assert errors[0]["kind"] == kind and errors[0]["key"] == "sample"
    assert "example-private" not in json.dumps(errors)
    _invalid(desc, "secret_literal", path)


def test_named_secrets_work_in_all_supported_positions() -> None:
    marker: Json = {"$secret": "STACK_KEY"}
    body: dict[str, Json] = {
        "inputs_schema": [{"key": "login", "secret": True, "default": marker}],
        "inputs": {
            "login": {"value": marker, "templating": "hog"},
            "headers": {"value": {"Authorization": marker, "Accept": "application/json"}},
        },
    }
    assert not validate_description(_one("destination", body), [])
    assert translate_in(_one("destination", body), [], {}).secret_names == {"STACK_KEY"}


def test_detaching_does_not_bypass_secret_or_body_validation() -> None:
    desc = _one("source", {"payload": {"password": "example-private"}})
    binding: Any = [{"kind": "source", "key": "sample", "entity_id": "id", "status": "detached"}]
    assert validate_description(desc, binding)[0]["code"] == "secret_literal"
    with pytest.raises(EngineError) as error:
        translate_in(desc, [], {"detach": [{"kind": "source", "key": "sample"}]})
    assert error.value.errors[0]["code"] == "secret_literal"


@pytest.mark.parametrize(
    ("kind", "body", "code", "path"),
    [
        (
            "flag",
            {"filters": {"groups": [{"$ref": {"kind": "insight", "key": "absent"}}]}},
            "reference_missing",
            "filters.groups[0]",
        ),
        ("model", {"columns": {"c": {"$ref": {"kind": "model", "key": "absent"}}}}, "reference_missing", "columns.c"),
        ("cohort", {"unknown": True}, "invalid_definition", "unknown"),
        (
            "property_group",
            {"properties": [{"name": "tier", "unknown": True}]},
            "invalid_definition",
            "properties[0].unknown",
        ),
        ("model", {"incremental": {"unknown": True}}, "invalid_definition", "incremental.unknown"),
    ],
)
def test_checks_references_and_unknown_fields_in_all_mapped_shapes(
    kind: str, body: dict[str, Json], code: str, path: str
) -> None:
    _invalid(_one(kind, body), code, path)


def test_references_must_resolve_inside_the_description() -> None:
    desc = _one("alert", {"insight": {"$ref": {"kind": "insight", "key": "gone"}}})
    assert (
        validate_description(desc, [{"kind": "insight", "key": "gone", "entity_id": 23}])[0]["code"]
        == "reference_missing"
    )


@pytest.mark.parametrize(
    "description",
    [
        None,
        {"version": True, "resources": []},
        {"version": 1, "resources": [None]},
        {"version": 1, "resources": [{"kind": "insight", "key": "valid", "source": {"file": []}, "body": {}}]},
        _one("insight", {"query": {"x": float("nan")}}),
        _one("insight", {"query": {"x": "\udfff"}}),
    ],
)
def test_malformed_description_is_an_error_value(description: Any) -> None:
    _invalid(description, "invalid_definition")


def test_limits_include_unmanaged_values_and_metadata() -> None:
    _invalid(_one("flag", {"filters": {"groups": "x" * MAX_DESCRIPTION_BYTES}}), "definition_too_large")
    desc = _one("insight", {"name": "small"})
    desc["resources"][0]["source"] = {"file": "x" * MAX_DESCRIPTION_BYTES}
    _invalid(desc, "definition_too_large")
    _invalid({"version": 1, "resources": [{}] * (MAX_RESOURCES + 1)}, "too_many_definitions")
    nested: Json = None
    for _ in range(MAX_DESCRIPTION_DEPTH + 1):
        nested = [nested]
    _invalid(_one("flag", {"filters": nested}), "invalid_definition")


def test_checks_long_dependency_chains_without_recursing_and_finds_cycles() -> None:
    desc: StackDescription = {
        "version": 1,
        "resources": [
            {
                "kind": "insight",
                "key": f"item-{n}",
                "body": {} if n == 0 else {"query": {"parent": {"$ref": {"kind": "insight", "key": f"item-{n - 1}"}}}},
            }
            for n in range(1100)
        ],
    }
    assert validate_description(desc, []) == []
    desc["resources"][0]["body"] = {"query": {"parent": {"$ref": {"kind": "insight", "key": "item-1099"}}}}
    _invalid(desc, "reference_cycle")


def test_dashboard_tiles_and_insights_can_refer_to_each_other() -> None:
    desc = json.loads((Path(__file__).parent / "fixtures/description.json").read_bytes())
    assert validate_description(desc, []) == []


@pytest.mark.parametrize(
    ("body", "path"),
    [
        (
            {
                "inputs_schema": [{"key": "login", "secret": True}],
                "mappings": [{"inputs": {"login": {"value": "example-private"}}}],
            },
            "mappings[0].inputs.login",
        ),
        ({"inputs": {"pin": {"secret": True, "value": "example-private"}}}, "inputs.pin"),
        (
            {
                "inputs_schema": [
                    {"key": "headers", "type": "dictionary", "default": {"Authorization": "example-private"}}
                ]
            },
            "inputs_schema[0].default.Authorization",
        ),
    ],
)
def test_sensitive_schema_defaults_and_inherited_mapping_inputs(body: dict, path: str) -> None:
    _invalid(_one("destination", body), "secret_literal", path)


def test_unused_secrets_and_references_do_not_create_runtime_dependencies() -> None:
    model = _one("model", {"columns": {"old": {"$secret": "OLD"}}})
    assert not translate_in(model, [], {}).secret_names
    destination = _one("destination", {"inputs": {"token": {"value": {"$secret": "OLD"}, "secret": True}}})
    assert not translate_in(destination, [], {"detach": [{"kind": "destination", "key": "sample"}]}).secret_names
    assert not validate_description(destination, [])
    unused_ref = _one("model", {"columns": {"self": {"$ref": {"kind": "model", "key": "sample"}}}})
    assert not validate_description(unused_ref, [])


def test_survey_uses_a_slug_for_its_definition_key() -> None:
    desc = _one("survey", {"name": "Product experience"})
    desc["resources"][0]["key"] = "Product experience"
    _invalid(desc, "invalid_definition", "key")


def test_credential_field_rules_preserve_public_settings_and_reject_literal_defaults() -> None:
    assert (
        validate_description(
            _one("destination", {"inputs": {"max_tokens": {"value": 32}, "tokenizer": {"value": "words"}}}), []
        )
        == []
    )
    _invalid(
        _one("destination", {"inputs_schema": [{"key": "pin", "secret": True, "default": None}]}),
        "secret_literal",
        "inputs_schema[0].default",
    )


def test_compact_json_byte_limit_includes_unicode_escaping_and_accepts_the_limit() -> None:
    desc = _one("insight", {"name": "é", "description": ""})
    initial_size = len(json.dumps(desc, separators=(",", ":")).encode())
    desc["resources"][0]["body"]["description"] = "x" * (MAX_DESCRIPTION_BYTES - initial_size)
    assert validate_description(desc, []) == []
    desc["resources"][0]["body"]["name"] = "éx"
    _invalid(desc, "definition_too_large")


@pytest.mark.parametrize(
    ("template", "key"),
    [
        ("template-pagerduty", "routing_key"),
        ("template-klime", "writeKey"),
        ("template-retain", "writeKey"),
        ("template-unify", "write_key"),
        ("template-engage-so", "public_key"),
        ("template-aws-kinesis", "aws_access_key_id"),
        ("template-userlist", "push_key"),
        ("plugin-posthog-gcs-plugin", "googleCloudKeyJson"),
        ("plugin-salesforce-plugin", "consumerKey"),
        ("plugin-customerio-plugin", "customerioSiteId"),
        ("segment-actions-clevertap", "clevertapPasscode"),
        ("segment-actions-insider-cloud", "ucd_key"),
        ("template-pii-hashing", "salt"),
        ("template-source-webhook", "auth_header"),
        ("template-warehouse-source-webflow", "signing_secrets"),
    ],
)
def test_bundled_template_credentials_require_secret_references_without_a_local_schema(template: str, key: str) -> None:
    body: dict[str, Json] = {"template_id": template, "inputs": {key: {"value": "example-private"}}}
    desc = _one("destination", body)
    _invalid(desc, "secret_literal", "inputs." + key)
    body["inputs"] = {key: {"value": {"$secret": "TEMPLATE_INPUT"}}}
    assert validate_description(desc, []) == []


def test_template_and_local_schema_secret_rules_apply_together() -> None:
    body: dict[str, Json] = {
        "template_id": "template-pagerduty",
        "inputs_schema": [{"key": "routing_key", "secret": False}],
        "inputs": {"routing_key": {"value": "example-private"}},
    }
    _invalid(_one("destination", body), "secret_literal", "inputs.routing_key")
    body.update(
        {
            "template_id": "custom",
            "inputs_schema": [{"key": "local_key", "secret": True}],
            "inputs": {"local_key": {"value": "example-private"}},
        }
    )
    _invalid(_one("destination", body), "secret_literal", "inputs.local_key")
    body["inputs"] = {"routing_key": {"value": "public-route"}, "keyboard": {"value": "public-keyboard"}}
    assert not validate_description(_one("destination", body), [])


@pytest.mark.parametrize(
    ("kind", "body", "path"),
    [
        ("model", {"incremental": []}, "incremental"),
        ("property_group", {"properties": {"name": "wrong"}}, "properties"),
        ("property_group", {"properties": None}, "properties"),
        ("action", {"steps": None}, "steps"),
        ("property_group", {"properties": [None]}, "properties[0]"),
        ("action", {"steps": ["invalid"]}, "steps[0]"),
    ],
)
def test_known_structured_fields_reject_other_json_shapes(kind: str, body: dict[str, Json], path: str) -> None:
    _invalid(_one(kind, body), "invalid_definition", path)


def test_nested_source_secrets_preserve_the_source_connection_object() -> None:
    stripe = _one(
        "source",
        {
            "source_type": "Stripe",
            "payload": {"auth_method": {"selection": "api_key", "stripe_secret_key": {"$secret": "STRIPE_KEY"}}},
        },
    )
    incoming = translate_in(stripe, [], {})
    assert not validate_description(stripe, [])
    assert incoming.secret_names == {"STRIPE_KEY"}
    inputs = incoming.config["resource"]["posthog_external_data_source"]["stack_sample"]["job_inputs_json"]
    assert '"auth_method":{"selection":"api_key","stripe_secret_key":' in inputs


@pytest.mark.parametrize(
    ("payload", "path"),
    [
        (
            {
                "auth_method": {
                    "selection": "api_key",
                    "stripe_secret_key": {"$secret": "S"},
                    "other": "example-private",
                }
            },
            "payload.auth_method.other",
        ),
        ({"auth_method.selection": "api_key"}, "payload.auth_method.selection"),
        ({"extra": [{"first": {"$secret": "S"}, "second": "example-private"}]}, "payload.extra[0].second"),
    ],
)
def test_unknown_nested_connection_leaves_remain_secret(payload: dict, path: str) -> None:
    _invalid(_one("source", {"source_type": "Stripe", "payload": payload}), "secret_literal", path)
