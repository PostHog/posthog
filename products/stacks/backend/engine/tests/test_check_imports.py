from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

import pytest

from products.stacks.backend.engine import read_bindings, run_diff, run_push, translate_in
from products.stacks.backend.engine.addresses import address
from products.stacks.backend.engine.check_imports import check_imports
from products.stacks.backend.engine.tests.test_binding_lifecycle import _project
from products.stacks.backend.engine.tests.test_read_entities import _api
from products.stacks.backend.engine.tests.test_translate_out import ENGINE_WORDS
from products.stacks.backend.engine.types import (
    Binding,
    ClaimedEntity,
    EngineError,
    EngineOptions,
    Json,
    ResourceDescription,
    StackDescription,
)

BASE = "/api/projects/7/data_quality_checks/"
SUBJECT = "eee41a42-463f-4e25-adb8-adb05bed8a71"
CHECK = "85733be5-c7c9-421e-95b2-1a5fd2ec4502"
MODEL: ResourceDescription = {
    "kind": "model",
    "key": "sales",
    "body": {"name": "sales", "query": {"query": "select 1"}},
}
REF: Json = {"$ref": {"kind": "model", "key": "sales"}}


def _check(kind: str, config: Json, subject: Json = SUBJECT, column: str = "code") -> ResourceDescription:
    return {
        "kind": "check",
        "key": "example",
        "body": {
            "subject_type": "view",
            "subject_uuid": subject,
            "check_type": kind,
            "column_name": column,
            "config": config,
        },
    }


@pytest.mark.parametrize(
    ("kind", "authored", "stored", "column_type"),
    [
        ("unique", {"lookback_hours": None}, {}, ""),
        ("not_null", {"lookback_hours": "2"}, {"lookback_hours": 2}, ""),
        ("row_count", {"min": "1"}, {"min": 1, "max": None}, ""),
        (
            "relationships",
            {
                "to_subject_type": "view",
                "to_subject_uuid": SUBJECT.upper(),
                "to_column": "code",
                "to_lookback_hours": None,
            },
            {"to_subject_type": "view", "to_subject_uuid": SUBJECT, "to_column": "code"},
            "",
        ),
        ("freshness", {"max_age_minutes": "24"}, {"max_age_minutes": 24}, ""),
        ("custom_sql", {"query": "select 1"}, {"query": "select 1"}, ""),
        ("accepted_values", {"values": ["2", 1, "2"]}, {"values": [1.0, 2.0]}, "LowCardinality(Nullable(Int64))"),
        ("accepted_values", {"values": [True, "false"]}, {"values": [False, True]}, "Bool"),
        ("accepted_values", {"values": [1, False, "1"]}, {"values": ["1", "false"]}, "String"),
    ],
)
def test_adopts_existing_assertion_by_uuid(
    kind: str, authored: dict[str, Any], stored: dict[str, Any], column_type: str
) -> None:
    check = _check(kind, authored, REF)
    engine = translate_in({"version": 1, "resources": [MODEL, check]}, [], {})
    live = {
        "id": CHECK,
        "subject_type": "view",
        "subject_uuid": SUBJECT,
        "check_type": kind,
        "column_name": "code",
        "config": stored,
        "name": "different",
    }
    routes: dict[str, Any] = {
        BASE: {"results": [{**live, "column_name": "other"}], "next": "?offset=1"},
        BASE + "?offset=1": [live, live],
    }
    if column_type:
        routes[BASE + "subjects/?subject_type=view"] = [
            {"subject_type": "view", "id": SUBJECT, "columns": {"code": column_type}}
        ]
    with _api(routes) as (credentials, requests):
        assert check_imports(engine, set(), {address("model", "sales"): SUBJECT}, credentials, None) == [
            {"to": address("check", "example"), "id": CHECK}
        ]
        assert set(requests) == routes.keys()


def test_claimed_check_aborts_before_upsert() -> None:
    check = _check("not_null", {})
    claim: ClaimedEntity = {"kind": "check", "entity_id": CHECK, "stack": "quality", "repository": "example/warehouse"}
    engine = translate_in({"version": 1, "resources": [check]}, [], {"claimed": [claim]})
    with _api({BASE: [{"id": CHECK, **check["body"]}]}) as (credentials, _), pytest.raises(EngineError) as caught:
        check_imports(engine, set(), {}, credentials, None)
    assert caught.value.errors[0]["code"] == "claimed_by_other_stack"
    assert claim["repository"] in str(caught.value)
    assert not ENGINE_WORDS.search(str(caught.value))


def test_distinct_stored_assertion_stays_separate() -> None:
    check = _check("row_count", {"min": 1})
    engine = translate_in({"version": 1, "resources": [check]}, [], {})
    with _api({BASE: [{"id": CHECK, **check["body"], "config": {"min": 2, "max": None}}]}) as (credentials, _):
        assert check_imports(engine, set(), {}, credentials, None) == []


def test_new_subject_and_bound_check_skip_the_api() -> None:
    check = _check("unique", {}, REF)
    engine = translate_in({"version": 1, "resources": [MODEL, check]}, [], {})
    with _api({}) as (credentials, requests):
        assert check_imports(engine, set(), {}, credentials, None) == []
        assert (
            check_imports(
                engine, {address("check", "example")}, {address("model", "sales"): SUBJECT}, credentials, None
            )
            == []
        )
        assert not requests


def test_unreadable_existing_subject_ref_fails_closed() -> None:
    engine = translate_in({"version": 1, "resources": [MODEL, _check("unique", {}, REF)]}, [], {})
    with _api({}) as (credentials, _), pytest.raises(EngineError) as caught:
        check_imports(engine, {address("model", "sales")}, {}, credentials, None)
    assert caught.value.errors[0]["code"] == "binding_conflict"
    assert not ENGINE_WORDS.search(str(caught.value))


def test_equivalent_definitions_cannot_upsert_the_same_check_on_a_new_subject() -> None:
    check = _check("row_count", {"min": 1}, REF, column="")
    other: ResourceDescription = {
        **check,
        "key": "other",
        "body": {**check["body"], "config": {"max": None, "min": "1"}},
    }
    engine = translate_in({"version": 1, "resources": [MODEL, check, other]}, [], {})
    with _api({}) as (credentials, requests), pytest.raises(EngineError) as caught:
        check_imports(engine, set(), {}, credentials, None)
    assert not requests
    assert caught.value.errors[0]["code"] == "binding_conflict"
    assert not ENGINE_WORDS.search(str(caught.value))


def test_orphaned_checks_and_renamed_model_do_not_block_matching() -> None:
    check = _check("not_null", {}, REF)
    engine = translate_in(
        {"version": 1, "resources": [MODEL, check]},
        [],
        {"rename_map": {address("model", "old"): {"kind": "model", "key": "sales"}}},
    )
    old, new = address("model", "old"), address("model", "sales")
    routes = {
        BASE: [
            {"id": "deleted", **check["body"], "subject_uuid": None},
            {"id": CHECK, **check["body"], "subject_uuid": SUBJECT},
        ]
    }
    with _api(routes) as (credentials, _):
        assert check_imports(engine, {old}, {old: SUBJECT, new: SUBJECT}, credentials, None) == [
            {"to": address("check", "example"), "id": CHECK}
        ]


def test_repeated_accepted_values_on_a_fresh_subject_allow_for_its_future_column_type() -> None:
    check = _check("accepted_values", {"values": ["2"]}, REF)
    other: ResourceDescription = {**check, "key": "other", "body": {**check["body"], "config": {"values": [2]}}}
    engine = translate_in({"version": 1, "resources": [MODEL, check, other]}, [], {})
    with _api({}) as (credentials, requests), pytest.raises(EngineError) as caught:
        check_imports(engine, set(), {}, credentials, None)
    assert not requests
    assert caught.value.errors[0]["code"] == "binding_conflict"


@pytest.mark.skipif(
    not os.getenv("POSTHOG_STACK_MIRROR") or not shutil.which("tofu"), reason="Needs the installed development build"
)
def test_diff_and_push_adopt_an_existing_check_then_converge(tmp_path: Path) -> None:
    check = _check("not_null", {"lookback_hours": 4})
    description: StackDescription = {"version": 1, "resources": [check]}
    options: EngineOptions = {"mirror": os.environ["POSTHOG_STACK_MIRROR"]}
    incoming = translate_in(description, [], options)
    live = {
        **check["body"],
        "id": CHECK,
        "name": "OrderCode",
        "fingerprint": "b" * 64,
        "description": "",
        "enabled": True,
        "severity": "error",
        "created_source": "user",
        "tags": [],
    }
    detail = BASE + CHECK + "/"
    with _project({BASE: {"results": [live], "next": None}, detail: live}) as (credentials, requests):
        diff, saved, _ = run_diff(tmp_path, incoming, None, credentials)
        assert diff["errors"] == []
        assert [(c["kind"], c["key"], c["action"]) for c in diff["changes"]] == [("check", "example", "adopt")]
        pushed, record = run_push(tmp_path, incoming, saved, None, credentials)
        assert pushed["errors"] == []
        binding: Binding = {"kind": "check", "key": "example", "entity_id": CHECK, "origin": "adopted"}
        assert pushed["bindings"] == [binding]
        assert read_bindings(record) == [{"kind": "check", "key": "example", "entity_id": CHECK}]
        after, _, _ = run_diff(tmp_path, translate_in(description, [binding], options), record, credentials)
        assert not after["errors"] and not after["changes"] and not after["drift"]
        assert set(requests) == {("GET", BASE), ("GET", detail)}
