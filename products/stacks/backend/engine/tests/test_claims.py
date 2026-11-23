import os
import json
import shutil
from pathlib import Path

import pytest
from unittest.mock import patch

from products.stacks.backend.engine.claims import check_saved_claims
from products.stacks.backend.engine.natural_keys import natural_imports
from products.stacks.backend.engine.runner import run_diff, run_push
from products.stacks.backend.engine.translate_in import translate_in
from products.stacks.backend.engine.types import (
    Binding,
    ClaimedEntity,
    Credentials,
    DiffError,
    EngineError,
    EngineOptions,
    Json,
    StackDescription,
)

from .test_binding_lifecycle import _project
from .test_translate_out import ENGINE_WORDS

FLAG: StackDescription = {
    "version": 1,
    "resources": [{"kind": "flag", "key": "checkout", "body": {"key": "checkout", "name": "Checkout"}}],
}
CREDENTIALS: Credentials = {"host": "https://127.0.0.1:1", "project_id": 7, "api_key": "example-key"}
CLAIM: ClaimedEntity = {"kind": "flag", "entity_id": "31", "stack": "retail-metrics", "repository": "example/catalog"}


def _assert_claim(error: DiffError) -> None:
    assert error["code"] == "claimed_by_other_stack"
    assert error["kind"] == "flag" and error["key"] == "checkout"
    message = error["message"]
    assert CLAIM["stack"] in message and CLAIM["repository"] in message
    assert not ENGINE_WORDS.search(message)


@pytest.mark.parametrize(
    ("route", "entity_id"), [("pending", 31), ("pending", "00031"), ("existing", 31), ("catalog", 31)]
)
def test_claimed_entity_cannot_be_adopted(route: str, entity_id: int | str) -> None:
    binding: Binding = {"kind": "flag", "key": "checkout", "entity_id": entity_id, "status": "pending"}
    options: EngineOptions = {"claimed": [CLAIM]}
    if route == "existing":
        options["existing"] = [binding]
    with pytest.raises(EngineError) as exc:
        engine_input = translate_in(FLAG, [binding] if route == "pending" else [], options)
        if route == "catalog":
            with patch("http.client.HTTPSConnection", autospec=True) as connection:
                response = connection.return_value.getresponse.return_value
                response.status = 200
                response.read.return_value = b'{"results":[{"key":"checkout","id":31}],"next":null}'
                natural_imports(engine_input, set(), CREDENTIALS)
    _assert_claim(exc.value.errors[0])


@pytest.mark.parametrize("cached", [False, True])
def test_missing_existing_hint_still_adopts_and_ignores_other_kinds_with_the_same_id(cached: bool) -> None:
    description: StackDescription = {
        "version": 1,
        "resources": [*FLAG["resources"], {"kind": "flag", "key": "search", "body": {"key": "search"}}],
    }
    options: EngineOptions = {
        "existing": [{"kind": "flag", "key": "search", "entity_id": 33}] if cached else [],
        "claimed": [{**CLAIM, "kind": "dashboard"}],
    }
    engine_input = translate_in(description, [], options)
    with patch("http.client.HTTPSConnection", autospec=True) as connection:
        response = connection.return_value.getresponse.return_value
        response.status = 200
        response.read.return_value = b'{"results":[{"key":"checkout","id":31}],"next":null}'
        assert natural_imports(engine_input, set(), CREDENTIALS) == [
            {"to": "posthog_feature_flag.stack_checkout", "id": "31"}
        ]


@pytest.mark.skipif(
    not os.environ.get("POSTHOG_STACK_MIRROR") or not shutil.which("tofu"),
    reason="Needs the installed stack mirror and binary.",
)
def test_a_claim_acquired_after_diff_blocks_push(tmp_path: Path) -> None:
    flag = {
        "key": "checkout",
        "name": "Checkout",
        "id": 31,
        "active": False,
        "deleted": False,
        "filters": {"groups": []},
    }
    options: EngineOptions = {"mirror": os.environ["POSTHOG_STACK_MIRROR"]}
    catalog = {
        "/api/projects/7/feature_flags/": {"results": [flag], "next": None},
        "/api/projects/7/feature_flags/31/": flag,
    }
    with _project(catalog) as (credentials, requests):
        diff, saved, _ = run_diff(tmp_path, translate_in(FLAG, [], options), None, credentials)
        assert diff["errors"] == [] and diff["summary"]["adopt"] == 1
        refreshed = translate_in(FLAG, [], {**options, "claimed": [CLAIM]})
        blocked, empty, _ = run_diff(tmp_path, refreshed, None, credentials)
        _assert_claim(blocked["errors"][0])
        assert empty == b""
        result, record = run_push(tmp_path, refreshed, saved, None, credentials)
        assert result["errors"]
        _assert_claim(result["errors"][0])
        assert record == b"" and result["bindings"] == []
    assert all(method == "GET" for method, _ in requests)


def test_lookup_stops_before_network_when_the_run_deadline_has_passed() -> None:
    engine_input = translate_in(FLAG, [], {})
    with patch("http.client.HTTPSConnection", autospec=True) as connection, pytest.raises(EngineError) as exc:
        natural_imports(engine_input, set(), CREDENTIALS, deadline=0)
    assert exc.value.errors[0]["code"] == "run_timeout"
    assert not ENGINE_WORDS.search(exc.value.errors[0]["message"])
    connection.assert_not_called()


def test_saved_adoption_needs_an_entity_id_to_check_its_claim() -> None:
    with pytest.raises(EngineError) as exc:
        check_saved_claims(
            {"resource_changes": [{"address": "posthog_feature_flag.stack_checkout", "change": {"importing": {}}}]},
            [CLAIM],
        )
    error = exc.value.errors[0]
    assert error["code"] == "binding_unknown"
    assert not ENGINE_WORDS.search(error["message"])


@pytest.mark.skipif(
    not os.environ.get("POSTHOG_STACK_MIRROR") or not shutil.which("tofu"),
    reason="Needs the installed stack mirror and binary.",
)
@pytest.mark.parametrize("case", ["claimed", "unclaimed", "moved"])
def test_natural_key_reused_after_external_deletion(tmp_path: Path, case: str) -> None:
    original = {
        "key": "checkout",
        "name": "Checkout",
        "id": 31,
        "active": False,
        "deleted": False,
        "filters": {"groups": []},
    }
    replacement = {**original, "id": 32}
    options: EngineOptions = {"mirror": os.environ["POSTHOG_STACK_MIRROR"]}
    collection = "/api/projects/7/feature_flags/"
    routes = {collection: {"results": [original], "next": None}, collection + "31/": original}
    with _project(routes) as (credentials, requests):
        first = translate_in(FLAG, [], options)
        _, saved, _ = run_diff(tmp_path, first, None, credentials)
        adopted, prior = run_push(tmp_path, first, saved, None, credentials)
        assert not adopted["errors"] and adopted["bindings"][0]["entity_id"] == 31

        del routes[collection + "31/"]
        routes[collection] = {"results": [replacement], "next": None}
        routes[collection + "32/"] = replacement
        if case == "claimed":
            options["claimed"] = [{**CLAIM, "entity_id": "32"}]
        elif case == "moved":
            record = json.loads(prior)
            resource = record["resources"][0]
            resource["name"] = "delivery"
            resource["instances"][0]["index_key"] = "beta"
            prior = json.dumps(record).encode()
            options["rename_map"] = {'posthog_feature_flag.delivery["beta"]': {"kind": "flag", "key": "checkout"}}
        next_input = translate_in(FLAG, [Binding(**b) for b in adopted["bindings"]], options)
        diff, saved, serial = run_diff(tmp_path, next_input, prior, credentials)
        if case == "claimed":
            assert diff["errors"]
            _assert_claim(diff["errors"][0])
            assert not saved
        else:
            assert not diff["errors"]
            assert diff["summary"]["adopt"] == 1 and diff["summary"]["create"] == 0
            assert diff["drift"][0]["deleted"] is True
            assert serial > 0
            result, snapshot = run_push(tmp_path, next_input, saved, prior, credentials)
            assert result["errors"] == []
            assert result["bindings"] == [{"kind": "flag", "key": "checkout", "entity_id": 32, "origin": "adopted"}]
            following, _, _ = run_diff(
                tmp_path, translate_in(FLAG, [Binding(**b) for b in result["bindings"]], options), snapshot, credentials
            )
            assert not following["changes"] and not following["drift"]
    assert all(method == "GET" for method, _ in requests)


@pytest.mark.parametrize(("source", "web_name"), [("hint", "Feedback"), ("pending", "Feedback"), ("hint", "New name")])
def test_two_keys_cannot_bind_the_same_natural_entity(source: str, web_name: str) -> None:
    survey_id = "018a914f-f28f-7cf0-9b67-d44e40f2b424"
    body: dict[str, Json] = {"name": "Feedback", "type": "popover", "questions": []}
    description: StackDescription = {
        "version": 1,
        "resources": [
            {"kind": "survey", "key": "mobile", "body": body},
            {"kind": "survey", "key": "web", "body": {**body, "name": web_name}},
        ],
    }
    binding: Binding = {"kind": "survey", "key": "web", "entity_id": survey_id, "status": "pending"}
    options: EngineOptions = {"existing": [binding]} if source == "hint" else {}
    with pytest.raises(EngineError) as exc:
        engine_input = translate_in(description, [binding] if source == "pending" else [], options)
        with _project(
            {"/api/projects/7/surveys/": {"results": [{"name": "Feedback", "id": survey_id}], "next": None}}
        ) as (credentials, _):
            natural_imports(engine_input, set(), credentials)
    error = exc.value.errors[0]
    assert error["code"] == "binding_conflict"
    assert not ENGINE_WORDS.search(error["message"])


@pytest.mark.skipif(
    not os.environ.get("POSTHOG_STACK_MIRROR") or not shutil.which("tofu"),
    reason="Needs the installed stack mirror and binary.",
)
def test_natural_match_cannot_adopt_an_entity_held_under_another_key(tmp_path: Path) -> None:
    survey_id = "018a914f-f28f-7cf0-9b67-d44e40f2b424"
    original: dict[str, Json] = {"name": "Feedback", "type": "popover", "questions": []}
    survey = {**original, "id": survey_id, "description": "", "archived": False}
    binding: Binding = {"kind": "survey", "key": "web", "entity_id": survey_id}
    prior = json.dumps(
        {
            "version": 4,
            "terraform_version": "1.12.6",
            "serial": 5,
            "lineage": "a3c7eac9-719f-433f-a2e9-374a4b81215b",
            "resources": [
                {
                    "mode": "managed",
                    "type": "posthog_survey",
                    "name": "stack_web",
                    "provider": 'provider["registry.opentofu.org/posthog/posthog"]',
                    "instances": [
                        {
                            "schema_version": 0,
                            "attributes": {
                                "id": survey_id,
                                "name": "Feedback",
                                "project_id": "7",
                                "type": "popover",
                                "questions_json": "[]",
                            },
                        }
                    ],
                }
            ],
        }
    ).encode()
    description: StackDescription = {
        "version": 1,
        "resources": [
            {"kind": "survey", "key": "web", "body": {**original, "name": "New name"}},
            {"kind": "survey", "key": "app", "body": original},
        ],
    }
    collection = "/api/projects/7/surveys/"
    with _project({collection: {"results": [survey], "next": None}, collection + survey_id + "/": survey}) as (
        credentials,
        requests,
    ):
        engine_input = translate_in(description, [binding], {"mirror": os.environ["POSTHOG_STACK_MIRROR"]})
        diff, saved, _ = run_diff(tmp_path, engine_input, prior, credentials)
        assert diff["errors"] and diff["errors"][0]["code"] == "binding_conflict"
        assert not saved
        assert all(method == "GET" for method, _ in requests)


@pytest.mark.parametrize("old_action", ["delete", "forget"])
def test_adoption_can_follow_release_but_cannot_delete_the_same_entity(old_action: str) -> None:
    saved = {
        "resource_changes": [
            {
                "address": "posthog_dashboard.stack_old",
                "change": {"actions": [old_action], "before": {"id": 17}, "after": None},
            },
            {
                "address": "posthog_dashboard.stack_new",
                "change": {"actions": ["no-op"], "importing": {"id": "17"}, "after": {"id": 17}},
            },
        ]
    }
    if old_action == "delete":
        with pytest.raises(EngineError) as exc:
            check_saved_claims(saved, [])
        assert exc.value.errors[0]["code"] == "binding_conflict"
        assert not ENGINE_WORDS.search(exc.value.errors[0]["message"])
    else:
        check_saved_claims(saved, [])
