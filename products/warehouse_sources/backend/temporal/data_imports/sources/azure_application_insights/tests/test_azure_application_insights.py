import json
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any, cast
from urllib.parse import parse_qs

import pytest
import time_machine
from unittest.mock import MagicMock

from requests import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.azure_application_insights.azure_application_insights import (
    AzureApplicationInsightsClient,
    AzureApplicationInsightsResumeConfig,
    azure_application_insights_source,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.azure_application_insights.source import (
    AzureApplicationInsightsSource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.azureapplicationinsights import (
    AzureApplicationInsightsSourceConfig,
)

TOKEN = {"access_token": "fake-access-token", "expires_in": 3600}
TIMESTAMP = "2026-01-07T10:00:00.1234567Z"
MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.azure_application_insights.azure_application_insights"


def payload(ids: list[str]) -> dict[str, Any]:
    return {
        "tables": [
            {
                "name": "PrimaryResult",
                "columns": [
                    {"name": "timestamp", "type": "datetime"},
                    {"name": "itemId", "type": "string"},
                    {"name": "customDimensions", "type": "dynamic"},
                ],
                "rows": [[TIMESTAMP, item_id, '{"environment":"test"}'] for item_id in ids],
            }
        ]
    }


@time_machine.travel("2026-01-08T12:00:00Z", tick=False)
@pytest.mark.parametrize("terminal_ids", [[], ["c"]])
def test_pagination_auth_and_checkpoint(
    config: AzureApplicationInsightsSourceConfig,
    manager: MagicMock,
    http_mock: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
    terminal_ids: list[str],
) -> None:
    monkeypatch.setattr(f"{MODULE}.PAGE_SIZE", 2)
    http_mock.side_effect = [(200, TOKEN), (200, payload(["a", "b"])), (200, payload(terminal_ids))]
    response = azure_application_insights_source(config, "v1", "requests", 1, "job", manager, None)
    batches = iter(cast(Iterable[list[dict[str, Any]]], response.items()))
    first = next(batches)
    assert first[0]["customDimensions"] == {"environment": "test"}
    assert manager.save_state.call_args.args[0].item_id == "b"
    assert manager.save_state.call_args.args[0].timestamp == TIMESTAMP
    assert [row["itemId"] for batch in [first, *batches] for row in batch] == ["a", "b", *terminal_ids]
    token_request, first_request, second_request = [call.args[0] for call in http_mock.call_args_list]
    assert token_request.url == f"https://login.microsoftonline.com/{config.tenant_id}/oauth2/token"
    assert parse_qs(token_request.body) == {
        "client_id": [config.client_id],
        "client_secret": [config.client_secret],
        "grant_type": ["client_credentials"],
        "resource": ["https://api.applicationinsights.io"],
    }
    assert first_request.url == f"https://api.applicationinsights.io/v1/apps/{config.application_id}/query"
    assert first_request.method == "POST"
    assert first_request.headers["Authorization"] == "Bearer fake-access-token"
    assert second_request.headers["Authorization"] == "Bearer fake-access-token"
    first_body, second_body = json.loads(first_request.body), json.loads(second_request.body)
    assert first_body["timespan"] == "2026-01-01T12:00:00+00:00/2026-01-08T12:00:00+00:00"
    assert second_body["timespan"] == first_body["timespan"]
    assert 'strcmp(tostring(itemId), "b") > 0' in second_body["query"]
    assert TIMESTAMP in second_body["query"]
    assert "order by timestamp asc, itemId asc | take 2" in first_body["query"]
    assert response.sort_mode == "asc"
    manager.safe_point.assert_called()


@time_machine.travel("2026-01-08T12:00:00Z", tick=False)
@pytest.mark.parametrize(
    ("last_value", "expected_start"),
    [
        (None, "2026-01-01T12:00:00+00:00"),
        ("2026-01-07T12:00:00Z", "2026-01-07T11:00:00+00:00"),
        (datetime(2026, 1, 7, 12), "2026-01-07T11:00:00+00:00"),
        (datetime(2026, 1, 7, 12, tzinfo=UTC), "2026-01-07T11:00:00+00:00"),
        ("2025-12-01T12:00:00Z", "2026-01-01T12:00:00+00:00"),
    ],
)
def test_incremental_and_full_refresh_window(
    config: AzureApplicationInsightsSourceConfig,
    manager: MagicMock,
    http_mock: MagicMock,
    last_value: datetime | str | None,
    expected_start: str,
) -> None:
    http_mock.side_effect = [(200, TOKEN), (200, payload([]))]
    response = azure_application_insights_source(config, "v1", "dependencies", 1, "job", manager, last_value)
    assert list(cast(Iterable[Any], response.items())) == []
    body = json.loads(http_mock.call_args.args[0].body)
    assert body["timespan"] == f"{expected_start}/2026-01-08T12:00:00+00:00"
    assert f'timestamp >= todatetime("{expected_start}")' in body["query"]
    assert "strcmp" not in body["query"]
    manager.save_state.assert_not_called()


@time_machine.travel("2026-02-08T12:00:00Z", tick=False)
def test_resume_preserves_window_and_escapes_cursor(
    config: AzureApplicationInsightsSourceConfig,
    manager: MagicMock,
    http_mock: MagicMock,
) -> None:
    manager.can_resume.return_value = True
    manager.load_state.return_value = AzureApplicationInsightsResumeConfig(
        start="2026-01-01T12:00:00Z", end="2026-01-08T12:00:00Z", timestamp=TIMESTAMP, item_id='a"\\b'
    )
    http_mock.side_effect = [(200, TOKEN), (200, payload([]))]
    response = azure_application_insights_source(config, "v1", "exceptions", 1, "job", manager, None)
    assert list(cast(Iterable[Any], response.items())) == []
    body = json.loads(http_mock.call_args.args[0].body)
    assert body["timespan"] == "2026-01-01T12:00:00Z/2026-01-08T12:00:00Z"
    assert f"strcmp(tostring(itemId), {json.dumps('a' + chr(34) + chr(92) + 'b')})" in body["query"]


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ({"tables": [], "error": {"code": "PartialError"}}, "incomplete results"),
        ({}, "no result table"),
        ({"tables": []}, "no result table"),
        (payload([""]), "missing its timestamp or item ID"),
    ],
)
def test_bad_results_do_not_advance_checkpoint(
    config: AzureApplicationInsightsSourceConfig,
    manager: MagicMock,
    http_mock: MagicMock,
    body: dict[str, Any],
    message: str,
) -> None:
    http_mock.side_effect = [(200, TOKEN), (200, body)]
    response = azure_application_insights_source(config, "v1", "availabilityResults", 1, "job", manager, None)
    with pytest.raises(ValueError, match=message):
        list(cast(Iterable[Any], response.items()))
    manager.save_state.assert_not_called()


@pytest.mark.parametrize("status", [401, 403, 404, 429, 500, 503])
def test_http_error_classification(
    config: AzureApplicationInsightsSourceConfig, http_mock: MagicMock, status: int
) -> None:
    client = AzureApplicationInsightsClient(config, "v1", 1, "job")
    client.auth._apply_token_response(TOKEN)
    http_mock.return_value = (status, {"error": {"code": "TestError"}})
    expected = HTTPError if status in (401, 403, 404) else RESTClientRetryableError
    with pytest.raises(expected) as error:
        client.query("print 1", "PT1M")
    patterns = AzureApplicationInsightsSource().get_non_retryable_errors()
    assert any(pattern in str(error.value) for pattern in patterns) == (status in (401, 403, 404))


@pytest.mark.parametrize(
    ("version", "endpoint", "message"),
    [
        ("v2", "requests", "Unsupported Application Insights API version"),
        ("v1", "requests | take 1", "Unknown Application Insights table"),
    ],
)
def test_invalid_query_target_makes_no_request(
    config: AzureApplicationInsightsSourceConfig,
    manager: MagicMock,
    http_mock: MagicMock,
    version: str,
    endpoint: str,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        response = azure_application_insights_source(config, version, endpoint, 1, "job", manager, None)
        list(cast(Iterable[Any], response.items()))
    http_mock.assert_not_called()


def test_repeated_cursor_does_not_advance_checkpoint(
    config: AzureApplicationInsightsSourceConfig,
    manager: MagicMock,
    http_mock: MagicMock,
) -> None:
    manager.can_resume.return_value = True
    manager.load_state.return_value = AzureApplicationInsightsResumeConfig(
        start="2026-01-01T12:00:00Z", end="2026-01-08T12:00:00Z", timestamp=TIMESTAMP, item_id="a"
    )
    http_mock.side_effect = [(200, TOKEN), (200, payload(["a"]))]
    response = azure_application_insights_source(config, "v1", "requests", 1, "job", manager, None)
    with pytest.raises(ValueError, match="pagination did not advance"):
        list(cast(Iterable[Any], response.items()))
    manager.save_state.assert_not_called()


@time_machine.travel("2026-01-08T12:00:00Z", tick=False)
@pytest.mark.parametrize("incremental", [False, True])
def test_pipeline_applies_watermark_only_for_incremental_sync(
    config: AzureApplicationInsightsSourceConfig,
    manager: MagicMock,
    http_mock: MagicMock,
    incremental: bool,
) -> None:
    inputs = MagicMock(
        api_version="v1",
        schema_name="requests",
        team_id=1,
        job_id="job",
        should_use_incremental_field=incremental,
        db_incremental_field_last_value="2026-01-07T12:00:00Z",
    )
    http_mock.side_effect = [(200, TOKEN), (200, payload([]))]
    response = AzureApplicationInsightsSource().source_for_pipeline(config, manager, inputs)
    assert list(cast(Iterable[Any], response.items())) == []
    body = json.loads(http_mock.call_args.args[0].body)
    assert body["timespan"].split("/")[0] == (
        "2026-01-07T11:00:00+00:00" if incremental else "2026-01-01T12:00:00+00:00"
    )
