from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
from typing import Any

import pytest

from products.stacks.backend.engine.entities import read_entities
from products.stacks.backend.engine.tests.test_translate_out import ENGINE_WORDS
from products.stacks.backend.engine.types import Credentials, EngineError


@contextmanager
def _api(routes: dict[str, Any]) -> Iterator[tuple[Credentials, list[str]]]:
    requests: list[str] = []

    class API(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            pass

        def do_GET(self) -> None:
            requests.append(self.path)
            if self.headers.get("Authorization") != "Bearer example" or self.path not in routes:
                self.send_error(404)
                return
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps(routes[self.path]).encode())

    with HTTPServer(("127.0.0.1", 0), API) as server:
        thread = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        thread.start()
        try:
            yield {"host": f"http://127.0.0.1:{server.server_port}", "project_id": 7, "api_key": "example"}, requests
        finally:
            server.shutdown()
            thread.join()


def test_list_and_read_preserve_body_fields_and_skip_duplicate_ids() -> None:
    base = "/api/projects/7/insights/"
    rows = [{"id": 12}, {"id": 12}]
    query = {"kind": "DataTableNode", "source": {"kind": "HogQLQuery", "query": "select 1"}}
    routes = {
        base: {"results": rows, "next": "?offset=2"},
        base + "?offset=2": {"results": [{"id": 12}, {"id": 13}], "next": None},
        base + "12/": {"id": 12, "name": "First", "query": query, "dashboards": [42], "created_by": {"id": 1}},
        base + "13/": {"id": 13, "name": "Second", "created_at": "now"},
    }
    with _api(routes) as (credentials, requests):
        first = read_entities("insight", credentials, limit=1)
        assert first["results"] == [
            {"entity_id": "12", "name": "First", "body": {"name": "First", "query": query, "dashboards": [42]}}
        ]
        assert first["next_cursor"] is not None
        assert read_entities("insight", credentials, cursor=first["next_cursor"], limit=1) == {
            "results": [{"entity_id": "13", "name": "Second", "body": {"name": "Second"}}],
            "next_cursor": None,
        }
        assert requests.count(base + "12/") == 1


@pytest.mark.parametrize(
    ("kind", "route", "record", "expected"),
    [
        (
            "dashboard",
            "dashboards",
            {
                "name": "Weekly",
                "tiles": [
                    {"id": 17, "insight": {"id": 91, "name": "Details"}, "color": "blue", "layouts": {"sm": {"x": 1}}},
                    {"text": {"body": "Hello", "created_by": "owner"}},
                    {"deleted": True, "text": {"body": "Old"}},
                ],
            },
            {
                "name": "Weekly",
                "tiles": [{"insight": 91, "color": "blue", "layouts": {"sm": {"x": 1}}}, {"text": {"body": "Hello"}}],
            },
        ),
        (
            "flag",
            "feature_flags",
            {
                "key": "demo",
                "name": "Demo",
                "active": True,
                "archived": False,
                "filters": {"groups": [{"rollout_percentage": 25}]},
                "analytics_dashboards": [42],
            },
            {"name": "Demo", "key": "demo", "active": True, "filters": {"groups": [{"rollout_percentage": 25}]}},
        ),
        (
            "model",
            "warehouse_saved_queries",
            {
                "name": "mrr",
                "query": {"kind": "HogQLQuery", "query": "select 1"},
                "is_materialized": True,
                "sync_frequency": "1hour",
                "incremental": {
                    "enabled": True,
                    "incremental_key": "t",
                    "unique_key": ["t"],
                    "lookback_seconds": 300,
                    "watermark": "private",
                },
                "columns": [{"name": "t", "type": "datetime", "metadata": "private"}],
                "latest_history_id": "x",
            },
            {
                "name": "mrr",
                "query": {"kind": "HogQLQuery", "query": "select 1"},
                "is_materialized": True,
                "sync_frequency": "1hour",
                "incremental": {"enabled": True, "incremental_key": "t", "unique_key": ["t"], "lookback_seconds": 300},
                "columns": {"t": "datetime"},
            },
        ),
        (
            "property_group",
            "schema_property_groups",
            {
                "name": "Checkout",
                "properties": [
                    {"id": "p", "name": "order", "property_type": "string", "is_required": True, "created_at": "now"}
                ],
            },
            {"name": "Checkout", "properties": [{"name": "order", "property_type": "string", "is_required": True}]},
        ),
    ],
)
def test_read_description_bodies(kind: str, route: str, record: dict, expected: dict) -> None:
    with _api({f"/api/projects/7/{route}/42/": {"id": 42, "created_at": "now", "created_by": "example", **record}}) as (
        credentials,
        _,
    ):
        assert read_entities(kind, credentials, ids=["42", "42"])["results"] == [
            {"entity_id": "42", "name": record["name"], "body": expected}
        ]


def test_event_includes_every_linked_property_group_as_a_literal_id() -> None:
    event = {
        "id": "e",
        "name": "checkout",
        "owner": {"id": 17, "email": "example@example.com"},
        "enforcement_mode": "allow",
        "is_action": False,
    }
    links = "/api/projects/7/event_schemas/?event_definition=e"
    with _api(
        {
            "/api/projects/7/event_definitions/e/": event,
            links: {
                "results": [{"id": "l1", "event_definition": "e", "property_group": {"id": "group1", "created_by": 7}}],
                "next": links + "&offset=1",
            },
            links + "&offset=1": {
                "results": [{"id": "l2", "event_definition": "e", "property_group": {"id": "group2"}}],
                "next": None,
            },
        }
    ) as (credentials, _):
        assert read_entities("event", credentials, ids=["e"])["results"][0]["body"] == {
            "name": "checkout",
            "owner": 17,
            "enforcement_mode": "allow",
            "property_groups": ["group1", "group2"],
        }


@pytest.mark.parametrize(
    ("kind", "route", "record"),
    [
        (
            "destination",
            "/api/environments/7/hog_functions/42/",
            {
                "type": "destination",
                "template": {"id": "webhook", "inputs": {"token": "example-secret"}},
                "inputs": {"token": {"value": "example-secret"}},
                "inputs_schema": [{"key": "token", "secret": True, "default": "example-secret"}],
                "mappings": [{"inputs": {"token": {"value": "example-secret"}}}],
            },
        ),
        (
            "source",
            "/api/projects/7/external_data_sources/42/",
            {
                "source_type": "Postgres",
                "payload": {"password": "example-secret"},
                "job_inputs": {"password": "example-secret"},
                "schemas": [{"name": "events", "should_sync": True, "credential": "example-secret"}],
            },
        ),
    ],
)
def test_pulling_an_entity_cannot_return_stored_input_values(kind: str, route: str, record: dict) -> None:
    with _api({route: {"id": 42, "name": "Demo", **record}}) as (credentials, _):
        result = read_entities(kind, credentials, ids=["42"])
        assert "example-secret" not in json.dumps(result)
        if kind == "source":
            assert result["results"][0]["body"]["payload"] == {"schemas": [{"name": "events", "should_sync": True}]}
        else:
            assert result["results"][0]["body"]["template_id"] == "webhook"


@pytest.mark.parametrize(
    "following",
    ["http://127.0.0.2:1/api/projects/7/insights/", "/api/projects/8/insights/", "/api/projects/7/insights/"],
)
def test_rejects_off_project_or_repeated_continuations(following: str) -> None:
    base = "/api/projects/7/insights/"
    with _api({base: {"results": [], "next": following}}) as (credentials, requests):
        with pytest.raises(EngineError) as error:
            read_entities("insight", credentials)
        assert requests == [base]
        assert not ENGINE_WORDS.search(str(error.value))


@pytest.mark.parametrize(("kind", "collection"), [("endpoint", "endpoints"), ("metric", "data_catalog/metrics")])
def test_uuid_selects_the_right_name_addressed_entity(kind: str, collection: str) -> None:
    base = f"/api/projects/7/{collection}/"
    with _api(
        {
            base: {"results": [{"id": "uuid-a", "name": "a"}, {"id": "uuid-b", "name": "b"}], "next": None},
            base + "b/": {"id": "uuid-b", "name": "b", "description": "Current"},
        }
    ) as (credentials, requests):
        assert read_entities(kind, credentials, ids=["uuid-b"])["results"] == [
            {"entity_id": "uuid-b", "name": "b", "body": {"name": "b", "description": "Current"}}
        ]
        assert requests == [base, base + "b/"]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"ids": ["../secrets"]},
        {"ids": ["%2F"]},
        {"ids": [".."]},
        {"cursor": "https://127.0.0.2:1/internal"},
        {"limit": 0},
    ],
)
def test_rejects_invalid_read_parameters_before_sending_credentials(kwargs: dict) -> None:
    with _api({}) as (credentials, requests):
        with pytest.raises(EngineError) as error:
            read_entities("insight", credentials, **kwargs)
        assert not requests
        assert not ENGINE_WORDS.search(str(error.value))


def test_named_route_cannot_pull_a_different_entity_after_a_rename() -> None:
    base = "/api/projects/7/endpoints/"
    routes = {
        base: {"results": [{"id": "old", "name": "published"}]},
        base + "published/": {"id": "replacement", "name": "published"},
    }
    with _api(routes) as (credentials, _):
        with pytest.raises(EngineError) as exc:
            read_entities("endpoint", credentials, ids=["old"])
    assert exc.value.errors[0]["code"] == "entity_missing"
    assert not ENGINE_WORDS.search(str(exc.value))


def test_action_steps_keep_authored_fields_only() -> None:
    row = {
        "id": 3,
        "name": "Open",
        "steps": [
            {
                "event": "opened",
                "selector": "button",
                "selector_regex": "computed",
                "created_at": "now",
                "created_by": {"id": 7},
            }
        ],
    }
    with _api({"/api/projects/7/actions/3/": row}) as (credentials, _):
        result = read_entities("action", credentials, ids=["3"])
    assert result["results"][0]["body"]["steps"] == [{"event": "opened", "selector": "button"}]
