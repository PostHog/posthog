from typing import Any

import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.superwall import (
    SuperwallSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.superwall.source import SuperwallSource
from products.warehouse_sources.backend.temporal.data_imports.sources.superwall.superwall import SuperwallResumeConfig


def driver() -> SourceDriver:
    return SourceDriver(
        SuperwallSource(),
        SuperwallSourceConfig(api_key="test_api_key", project_id="project_test", application_id="application_test"),
    )


@pytest.mark.parametrize(
    ("name", "path", "scope_param", "scope_value", "extra_params"),
    [
        (
            "paywalls",
            "/v2/paywalls",
            "application_id",
            "application_test",
            {"include_legacy_editor": "true", "exclude_global_templates": "true"},
        ),
        ("campaigns", "/v2/campaigns", "application_id", "application_test", {}),
        ("products", "/v2/products", "project_id", "project_test", {}),
        ("entitlements", "/v2/entitlements", "project_id", "project_test", {}),
    ],
)
def test_configuration_walk_uses_last_id_and_stops_on_has_more(
    name: str, path: str, scope_param: str, scope_value: str, extra_params: dict[str, str]
) -> None:
    rows = [{"id": "first", "products": []}, {"id": "second", "products": [{"id": "nested"}]}]
    result = driver().run(
        name,
        [
            ScriptedResponse(json={"data": rows, "has_more": True}),
            ScriptedResponse(json={"data": [{"id": "last"}], "has_more": False}),
        ],
    )
    assert result.raised is None
    assert result.rows == [*rows, {"id": "last"}]
    assert result.paths == [path, path]
    assert result.params("starting_after") == [None, "second"]
    assert result.params(scope_param) == [scope_value, scope_value]
    for key, value in extra_params.items():
        assert result.params(key) == [value, value]
    assert result.committed_states == [SuperwallResumeConfig(cursor="second")]


@pytest.mark.parametrize("resume_cursor", [None, "saved_iterator"])
def test_event_log_uses_iterator_and_preserves_payload(resume_cursor: str | None) -> None:
    rows = [
        {"id": "message_test", "payload": {"data": {"id": "transaction_test"}}, "timestamp": "2026-01-01T00:00:00Z"}
    ]
    result = driver().run(
        "webhook_events",
        [
            ScriptedResponse(json={"data": [], "has_more": True, "iterator": "next_iterator"}),
            ScriptedResponse(json={"data": rows, "has_more": False, "iterator": "terminal_iterator"}),
        ],
        resume_state=SuperwallResumeConfig(cursor=resume_cursor) if resume_cursor else None,
    )
    assert result.raised is None
    assert result.rows == rows
    assert result.paths == ["/v2/projects/project_test/events"] * 2
    assert result.params("iterator") == [resume_cursor, "next_iterator"]
    assert result.params("starting_after") == [None, None]
    assert result.params("with_content") == ["true", "true"]
    assert result.params("project_id") == [None, None]
    assert result.committed_states == [SuperwallResumeConfig(cursor="next_iterator")]


def test_configuration_resume_continues_from_saved_id() -> None:
    result = driver().run(
        "products",
        [
            ScriptedResponse(json={"data": [{"id": "last"}], "has_more": False}),
        ],
        resume_state=SuperwallResumeConfig(cursor="saved_id"),
    )
    assert result.raised is None
    assert result.rows == [{"id": "last"}]
    assert result.params("starting_after") == ["saved_id"]


@pytest.mark.parametrize("rows", [[], [{"id": "survey_test", "options": ["Reason one"], "message": None}]])
def test_surveys_do_not_send_unsupported_pagination(rows: list[dict[str, Any]]) -> None:
    result = driver().run("surveys", [ScriptedResponse(json={"object": "list", "data": rows})])
    assert result.raised is None
    assert result.rows == rows
    assert result.queries == [{"application_id": ("application_test",)}]
    assert result.saved_states == []


@pytest.mark.parametrize(
    ("name", "body"),
    [
        ("paywalls", {"data": [], "has_more": True}),
        ("paywalls", {"data": [{"name": "No ID"}], "has_more": True}),
        ("webhook_events", {"data": [{"id": "message_test"}], "has_more": True}),
        ("paywalls", {"data": [{"id": "first"}]}),
    ],
)
def test_invalid_pagination_fails_instead_of_truncating(name: str, body: dict[str, Any]) -> None:
    result = driver().run(name, [ScriptedResponse(json=body)])
    assert isinstance(result.raised, ValueError)
    assert result.rows == []
    assert result.committed_states == []
