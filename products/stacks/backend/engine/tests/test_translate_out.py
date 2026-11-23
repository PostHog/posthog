import re
import json
from pathlib import Path
from typing import Any

import pytest

from products.stacks.backend.engine.addresses import address
from products.stacks.backend.engine.translate_out import translate_error, translate_out
from products.stacks.backend.engine.types import Action, Json, Source, StackDescription

FIXTURES = Path(__file__).parent / "fixtures"
CAPTURED = json.loads((FIXTURES / "diagnostics.json").read_bytes())
ENGINE_WORDS = re.compile(r"terraform|opentofu|tofu|provider|state|plan|apply|hcl|resource address", re.I)


@pytest.mark.parametrize(
    ("case", "code"),
    [
        ("auth401", "credentials_invalid"),
        ("auth", "credentials_invalid"),
        ("missing", "entity_missing"),
        ("validation", "body_invalid"),
        ("conflict", "entity_exists"),
        ("lock", "stack_locked"),
        ("stale", "stack_moved"),
        ("crash", "stack_interrupted"),
        ("timeout", "connection_timeout"),
        ("tls_timeout", "connection_timeout"),
        ("reference", "reference_missing"),
        ("cycle", "reference_cycle"),
        ("invalid", "invalid_definition"),
    ],
)
def test_captured_diagnostic(case: str, code: str) -> None:
    diagnostic = CAPTURED[case][0]
    errors = translate_error({"diagnostics": [diagnostic]})

    assert len(errors) == 1
    assert errors[0]["code"] == code
    assert not ENGINE_WORDS.search(json.dumps(errors))
    if case == "validation":
        assert errors[0]["message"] == "A query is required."
        assert errors[0]["path"] == "query"
        assert (errors[0]["kind"], errors[0]["key"]) == ("insight", "example")
    else:
        assert len(errors[0]["message"].split(".")) >= 3
    assert translate_error("Error: " + diagnostic["summary"] + "\n" + diagnostic["detail"])[0]["code"] == code


@pytest.mark.parametrize(
    ("field", "reason", "expected"),
    [
        (
            "detail",
            "Connection check failed for password 'pass word'.",
            "Connection check failed for password '[redacted]'.",
        ),
        (
            "detail",
            "Connection check failed for password pass%20word.",
            "Connection check failed for password [redacted].",
        ),
        (
            "detail",
            "Connection check failed for password pass+word.",
            "Connection check failed for password [redacted].",
        ),
        ("detail", "The Terraform provider rejected the input.", "PostHog rejected a field in this definition."),
        # A source's connection check answers with `message`, not DRF's `detail`.
        ("message", "Could not connect to Postgres. Check the host.", "Could not connect to Postgres. Check the host."),
    ],
)
def test_body_errors_surface_only_safe_api_detail(field: str, reason: str, expected: str) -> None:
    payload = json.dumps({"type": "validation_error", field: reason})
    (error,) = translate_error({"detail": f"API error (status 400): {payload}"}, secret_values=["pass word"])
    assert error["code"] == "body_invalid" and error["message"].startswith(expected)
    assert not ENGINE_WORDS.search(error["message"])


@pytest.mark.parametrize(
    ("summary", "detail", "code"),
    [
        (
            "Provider produced inconsistent result after apply",
            "When applying changes to {addr}, provider produced an unexpected new value: .appearance_json: was null.",
            "stack_failed",
        ),
        (
            "Resource instance cannot be destroyed",
            "Resource instance {addr} has prevent_destroy set, but the plan calls for it to be destroyed.",
            "removal_blocked",
        ),
    ],
)
def test_a_diagnostic_without_an_address_names_the_definition_its_detail_names(
    summary: str, detail: str, code: str
) -> None:
    diagnostic = {"severity": "error", "summary": summary, "detail": detail.format(addr=address("survey", "feedback"))}

    errors = translate_error({"diagnostics": [diagnostic]})

    assert [(e["code"], e.get("kind"), e.get("key")) for e in errors] == [(code, "survey", "feedback")]
    assert not ENGINE_WORDS.search(json.dumps(errors))


def test_stream_contains_multiple_diagnostics_and_never_quotes_raw_output() -> None:
    raw = "\n".join(
        json.dumps(item)
        for item in [
            {"type": "version", "tofu": "1.12.6"},
            {"type": "diagnostic", "diagnostic": dict(CAPTURED["auth"][0], severity="warning")},
            {"type": "diagnostic", "diagnostic": CAPTURED["auth"][0]},
            {
                "type": "diagnostic",
                "diagnostic": {
                    "summary": "terraform-provider-posthog crashed while reading phx_example_secret",
                    "detail": "unrecognized failure",
                },
            },
        ]
    )
    errors = translate_error(raw.encode())
    assert [error["code"] for error in errors] == ["credentials_invalid", "stack_failed"]
    assert "phx_example_secret" not in json.dumps(errors)
    assert not ENGINE_WORDS.search(json.dumps(errors))


def row(addr: str, actions: list[str], before: Any, after: Any, **attributes: Any) -> dict[str, Any]:
    return {
        "address": addr,
        "mode": "managed",
        "change": {"actions": actions, "before": before, "after": after, **attributes},
    }


def test_dashboards_include_tile_fields_and_change_counts_once() -> None:
    dashboard = address("dashboard", "sales")
    layout = address("dashboard", "sales", layout=True)
    source: Source = {"file": "views.ts", "export": "sales"}
    description: StackDescription = {
        "version": 1,
        "resources": [{"kind": "dashboard", "key": "sales", "body": {"name": "Sales"}, "source": source}],
    }
    diff = translate_out(
        {
            "resource_changes": [
                row(
                    layout,
                    ["update"],
                    {"tiles": [{"text_body": "old", "tile_id": 2, "layouts_json": '{"sm":{"w":6}}'}]},
                    {"tiles": [{"text_body": "new", "tile_id": 3, "layouts_json": '{ "sm": { "w": 6 } }'}]},
                ),
                row(
                    dashboard,
                    ["update"],
                    {"name": "Old", "tags": ["two", "one"]},
                    {"name": "Sales", "tags": ["one", "two"]},
                ),
            ]
        },
        description,
    )
    assert diff["changes"] == [
        {
            "kind": "dashboard",
            "key": "sales",
            "name": "Sales",
            "action": "update",
            "source": source,
            "loses": None,
            "summary": "2 fields changed",
            "fields": [
                {"path": "name", "before": "Old", "after": "Sales", "sensitive": False},
                {"path": "tiles[0].text.body", "before": "old", "after": "new", "sensitive": False},
            ],
        }
    ]
    assert sum(diff["summary"].values()) == diff["summary"]["update"] == 1


def test_alert_includes_the_description_path_and_unresolved_reference() -> None:
    reference: Json = {"$ref": {"kind": "insight", "key": "sales"}}
    description: StackDescription = {
        "version": 1,
        "resources": [{"kind": "alert", "key": "limit", "body": {"insight": reference}}],
    }
    windows = [{"start": "02:00", "end": "03:00"}, {"start": "05:00", "end": "06:00"}]
    diff = translate_out(
        {
            "resource_changes": [
                row(
                    address("alert", "limit"),
                    ["update"],
                    {"threshold_upper": 2, "insight": 42, "schedule_restriction": {"blocked_windows": windows}},
                    {
                        "threshold_upper": 4,
                        "project_id": "1",
                        "schedule_restriction": {"blocked_windows": windows[::-1]},
                    },
                    after_unknown={"insight": True},
                )
            ]
        },
        description,
    )
    assert diff["changes"][0]["fields"] == [
        {"path": "insight", "before": 42, "after": reference, "sensitive": False},
        {"path": "threshold.configuration.bounds.upper", "before": 2, "after": 4, "sensitive": False},
    ]
    reordered = row(
        address("alert", "limit"),
        ["update"],
        {"schedule_restriction": {"blocked_windows": windows}},
        {"schedule_restriction": {"blocked_windows": windows[::-1]}},
    )
    diff = translate_out({"resource_changes": [reordered], "resource_drift": [reordered]}, description)
    assert diff["drift"] == []
    assert diff["summary"]["update"] == 1
    assert diff["changes"][0]["fields"] == []


def test_update_to_a_computed_field_is_visible() -> None:
    diff = translate_out(
        {
            "resource_changes": [
                row(address("insight", "traffic"), ["update"], {"short_id": "old"}, {"short_id": "new"})
            ]
        },
        {"version": 1, "resources": []},
    )
    assert [(entry["action"], entry["fields"], entry["summary"]) for entry in diff["changes"]] == [
        ("update", [], "PostHog will refresh fields it computes.")
    ]
    assert sum(diff["summary"].values()) == diff["summary"]["update"] == 1
    assert not ENGINE_WORDS.search(json.dumps(diff))


def test_recreate_move_import_remove_and_forget_are_distinct() -> None:
    original = row(address("dashboard", "sales"), ["delete", "create"], {"name": "Sales"}, {"name": "Sales"})
    original["previous_address"] = "posthog_dashboard.old"
    moved = row(address("insight", "email"), ["no-op"], {}, {})
    moved["previous_address"] = 'posthog_insight.by_channel["email"]'
    moved_layout = row(address("dashboard", "views", layout=True), ["no-op"], {"tiles": []}, {"tiles": []})
    moved_layout["previous_address"] = "posthog_dashboard_layout.old"
    diff = translate_out(
        {
            "resource_changes": [
                original,
                moved,
                moved_layout,
                row(address("dashboard", "views"), ["no-op"], {}, {}),
                row(address("dashboard", "adopted", layout=True), ["no-op"], {}, {}, importing={"id": "4"}),
                row(
                    address("action", "usage"),
                    ["update"],
                    {"name": "Usage"},
                    {"name": "Clicks"},
                    importing={"id": "1/2"},
                ),
                row(address("dashboard", "old"), ["delete"], {"name": "Old"}, None),
                row(address("alert", "detached"), ["forget"], {"name": "Alert"}, None),
                row(address("insight", "nothing"), ["no-op"], {}, {}),
            ],
            "resource_drift": [row(moved["previous_address"], ["update"], {"name": "Original"}, {"name": "Edited"})],
        },
        {"version": 1, "resources": []},
    )
    assert diff["errors"] == []
    assert diff["summary"] == {
        "create": 0,
        "adopt": 2,
        "rename": 2,
        "recreate": 1,
        "remove": 1,
        "release": 1,
        "update": 0,
    }
    assert {c["key"]: c.get("entity_id") for c in diff["changes"] if c["action"] == "adopt"} == {
        "adopted": "4",
        "usage": "2",
    }
    assert diff["drift"] == [
        {"kind": "insight", "key": "email", "fields": [{"path": "name", "pushed": "Original", "found": "Edited"}]}
    ]
    recreated = next(change for change in diff["changes"] if change["action"] == "recreate")
    assert recreated["loses"] and "links" in recreated["loses"]


@pytest.mark.parametrize(
    ("primary", "verb", "summary"),
    [
        ("forget", "release", "This dashboard stays in PostHog and is no longer managed in code."),
        ("no-op", "update", "The dashboard tiles stay in PostHog and are no longer managed in code."),
    ],
)
def test_releasing_dashboard_tiles_preserves_them(primary: str, verb: Action, summary: str) -> None:
    before = {"id": 4, "name": "Reviews"}
    diff = translate_out(
        {
            "resource_changes": [
                row(
                    address("dashboard", "reviews", layout=True), ["forget"], {"tiles": [{"text_body": "Intro"}]}, None
                ),
                row(address("dashboard", "reviews"), [primary], before, None if primary == "forget" else before),
            ]
        },
        {"version": 1, "resources": []},
    )
    assert [(entry["kind"], entry["action"], entry["fields"], entry["summary"]) for entry in diff["changes"]] == [
        ("dashboard", verb, [], summary)
    ]
    assert sum(diff["summary"].values()) == diff["summary"][verb] == 1
    assert not ENGINE_WORDS.search(json.dumps(diff))


def test_unrecognized_or_protected_deletion_cannot_pass_silently() -> None:
    diff = translate_out(
        {
            "resource_changes": [
                row(address("alert", "on-call"), ["delete"], {"name": "On call"}, None),
                row("posthog_insight.legacy", ["delete"], {"name": "Legacy"}, None),
                row(
                    address("flag", "checkout"),
                    ["create", "delete"],
                    {"key": "older"},
                    {"key": "checkout"},
                    importing={"id": "12"},
                ),
            ]
        },
        {"version": 1, "resources": []},
    )
    assert [(error["code"], error.get("key")) for error in diff["errors"]] == [
        ("removal_blocked", "on-call"),
        ("removal_blocked", "checkout"),
        ("binding_unknown", None),
    ]
    assert diff["errors"][0]["key"] == "on-call"
    assert not ENGINE_WORDS.search(json.dumps(diff["errors"]))


def test_external_deletion_is_drift_and_can_be_recreated() -> None:
    diff = translate_out(
        json.loads((FIXTURES / "missing_insight.json").read_bytes()),
        {"version": 1, "resources": [{"kind": "insight", "key": "example", "body": {"name": "Example"}}]},
    )
    assert diff["summary"]["create"] == 1
    assert diff["errors"] == []
    assert diff["drift"][0] == {
        "kind": "insight",
        "key": "example",
        "deleted": True,
        "fields": [
            {"path": "name", "pushed": "Example", "found": None},
            {"path": "query", "pushed": {"kind": "TrendsQuery"}, "found": None},
        ],
    }


def test_deletion_drift_survives_without_mapped_field_values() -> None:
    diff = translate_out(
        {"resource_drift": [row(address("insight", "traffic"), ["delete"], {"id": 3}, None)]},
        {"version": 1, "resources": []},
    )
    assert diff["drift"] == [{"kind": "insight", "key": "traffic", "deleted": True, "fields": []}]


@pytest.mark.parametrize(
    ("kind", "path", "attribute", "body", "sensitivity"),
    [
        ("source", "payload", "job_inputs_json", {}, {}),
        ("destination", "inputs", "sensitive_inputs_json", {}, {}),
        ("destination", "filters", "filters_json", {"filters": {"properties": [{"value": {"$secret": "KEY"}}]}}, {}),
        ("destination", "mappings", "mappings_json", {}, {"before_sensitive": {"mappings_json": [False, True]}}),
    ],
)
def test_secrets_are_masked_in_both_drift_and_changes(
    kind: str, path: str, attribute: str, body: dict[str, Any], sensitivity: dict[str, Any]
) -> None:
    description: StackDescription = {"version": 1, "resources": [{"kind": kind, "key": "sales", "body": body}]}
    change = row(
        address(kind, "sales"),
        ["update"],
        {attribute: '{"value":"previous-value"}'},
        {attribute: '{"value":"new-value"}'},
        **sensitivity,
    )
    diff = translate_out({"resource_changes": [change], "resource_drift": [change]}, description)
    assert diff["changes"][0]["fields"] == [{"path": path, "before": None, "after": None, "sensitive": True}]
    assert diff["drift"][0]["fields"] == [{"path": path, "pushed": None, "found": None, "sensitive": True}]
    assert "previous-value" not in json.dumps(diff)
    assert "new-value" not in json.dumps(diff)
