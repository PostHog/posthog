from datetime import UTC, date, datetime
from typing import Any
from urllib.parse import urlsplit

import pytest
import time_machine

from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
    source_inputs,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.promptingcompany import (
    PromptingCompanySourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.prompting_company.prompting_company import (
    PromptingCompanyResumeConfig,
    prompting_company_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.prompting_company.source import (
    PromptingCompanySource,
)


@pytest.fixture
def config() -> PromptingCompanySourceConfig:
    return PromptingCompanySourceConfig(api_key="fake-test-key", product_id="product_example", start_date="2025-01-01")


def run(config: PromptingCompanySourceConfig, name: str, script: Any, **kwargs: Any) -> DriveResult:
    return SourceDriver(PromptingCompanySource(), config).run(name, script, **kwargs)


def content_page(doc: str, total_pages: int) -> ScriptedResponse:
    return ScriptedResponse(json={"ok": True, "data": {"items": [{"id": doc}], "totalPages": total_pages}})


@pytest.mark.parametrize("resumed", [False, True])
def test_content_pagination_and_resume(config: PromptingCompanySourceConfig, resumed: bool) -> None:
    first_page = 3 if resumed else 1
    result = run(
        config,
        "published_content",
        [content_page("doc-a", first_page + 1), content_page("doc-b", first_page + 1)],
        resume_state=PromptingCompanyResumeConfig(page=first_page) if resumed else None,
    )

    assert result.items == [[{"id": "doc-a"}], [{"id": "doc-b"}]]
    assert result.saved_states == [PromptingCompanyResumeConfig(page=first_page + 1)]
    assert len(result.requests) == 2
    assert result.queries[0] == {
        "productId": ("product_example",),
        "pageSize": ("100",),
        "page": (str(first_page),),
        "status": ("published",),
        "orderBy": ("createdAt",),
        "orderByDirection": ("asc",),
    }
    assert result.requests[1].param("page") == str(first_page + 1)
    for request in result.requests:
        assert request.headers["x-api-key"] == "fake-test-key"
        assert "authorization" not in request.headers
        assert urlsplit(request.url).path == "/api/v1/content"


def test_completing_a_paginated_table_clears_the_resume_cursor(config: PromptingCompanySourceConfig) -> None:
    with scripted_network([]):
        inputs = source_inputs("published_content")
        manager = PromptingCompanySource().get_resumable_source_manager(inputs)
        manager.save_state(PromptingCompanyResumeConfig(page=2))
        manager.confirm()
        manager.commit()
        assert manager.load_state() == PromptingCompanyResumeConfig(page=2)

        response = prompting_company_source(config, inputs, manager)

        assert response.on_complete is not None
        response.on_complete()
        assert manager.load_state() is None


@pytest.mark.parametrize(
    "incremental, watermark, expected_start",
    [
        (False, "2025-02-01", "2025-01-01"),
        (True, None, "2025-01-01"),
        (True, "2025-02-01T12:00:00Z", "2025-02-01"),
        (True, date(2025, 2, 1), "2025-02-01"),
        (True, datetime(2025, 2, 1, tzinfo=UTC), "2025-02-01"),
        (True, "2024-12-01", "2025-01-01"),
    ],
)
def test_sov_date_filter(
    config: PromptingCompanySourceConfig,
    incremental: bool,
    watermark: object,
    expected_start: str,
) -> None:
    rows = [{"date": "2025-02-01", "sov": 50, "mentions": 1, "runs": 2}]
    with time_machine.travel(datetime(2025, 2, 2, tzinfo=UTC), tick=False):
        result = run(
            config,
            "share_of_voice",
            [ScriptedResponse(json={"ok": True, "data": {"timeSeries": rows}})],
            should_use_incremental_field=incremental,
            db_incremental_field_last_value=watermark,
        )
    assert result.items == [rows]
    assert result.queries == [
        {
            "productId": ("product_example",),
            "start": (expected_start,),
            "end": ("2025-02-02",),
            "granularity": ("day",),
            "rollingWindow": ("1",),
        }
    ]
    assert result.response is not None
    assert result.response.sort_mode == "desc"
    assert result.saved_states == []


def test_validation_rejects_redirects(config: PromptingCompanySourceConfig) -> None:
    redirect = ScriptedResponse(status=302, json={}, headers={"Location": "https://evil.example.com/steal"})
    with scripted_network([redirect]) as network:
        assert validate_credentials(config, None) == (True, None)

    assert network.session_options[0]["allow_redirects"] is False
    assert [request.origin for request in network.requests_log] == ["https://app.promptingco.com"]


def test_sync_rejects_redirects(config: PromptingCompanySourceConfig) -> None:
    redirect = ScriptedResponse(status=302, json={}, headers={"Location": "https://evil.example.com/steal"})

    result = run(config, "published_content", [redirect])

    assert result.raised is not None
    assert [request.origin for request in result.requests] == ["https://app.promptingco.com"]


@pytest.mark.parametrize(
    "status, schema, valid, error",
    [
        (403, None, True, None),
        (403, "published_content", False, "content:read"),
        (403, "prompt_suggestions", False, "prompts:read"),
        (403, "simulation_runs", False, "simulations:read"),
        (403, "share_of_voice", False, "analytics:read"),
        (404, None, False, "product was not found"),
    ],
)
def test_credential_status_mapping(
    config: PromptingCompanySourceConfig,
    status: int,
    schema: str | None,
    valid: bool,
    error: str | None,
) -> None:
    with scripted_network([ScriptedResponse(status=status, json={"ok": status == 200})]) as network:
        result, message = validate_credentials(config, schema)
    assert result is valid
    if error is None:
        assert message is None
    else:
        assert error in (message or "")
    assert len(network.requests_log) == 1
    request = network.requests_log[0]
    assert request.headers["x-api-key"] == "fake-test-key"
    if schema is None or schema in ("published_content", "simulation_runs"):
        assert request.query["pageSize"] == ("1",)
    if schema == "share_of_voice":
        assert request.query["start"] == request.query["end"]


@pytest.mark.parametrize("status", [429, 500])
def test_credential_transient_errors_propagate(config: PromptingCompanySourceConfig, status: int) -> None:
    with scripted_network(always(ScriptedResponse(status=status, json={"ok": False}))):
        with pytest.raises(HTTPError):
            validate_credentials(config, None)


@pytest.mark.parametrize("status, code", [(401, "UNAUTHORIZED"), (403, "FORBIDDEN")])
def test_sync_auth_errors_are_terminal(config: PromptingCompanySourceConfig, status: int, code: str) -> None:
    result = run(
        config,
        "published_content",
        [ScriptedResponse(status=status, json={"ok": False, "code": code, "message": "authentication required"})],
    )

    assert isinstance(result.raised, HTTPError)
    assert len(result.requests) == 1
    assert any(pattern in str(result.raised) for pattern in PromptingCompanySource().get_non_retryable_errors())
