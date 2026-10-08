from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any, cast
from urllib.parse import parse_qs, urlencode, urlsplit

import pytest
from unittest.mock import MagicMock

import responses
import structlog
from requests import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import UnknownResourceError
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.survicate import (
    SurvicateSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.survicate.source import SurvicateSource
from products.warehouse_sources.backend.temporal.data_imports.sources.survicate.survicate import SurvicateResumeConfig

BASE = "https://data-api.survicate.com/v2"
WATERMARK = "2025-04-01T00:00:00.000000Z"


def page(rows: list[dict[str, Any]], next_url: str | None = None, has_more: bool | None = None) -> dict[str, Any]:
    return {
        "data": rows,
        "pagination_data": {"has_more": bool(next_url) if has_more is None else has_more, "next_url": next_url},
    }


def inputs(endpoint: str, incremental: bool = False, watermark: Any = None) -> SourceInputs:
    return SourceInputs(
        schema_name=endpoint,
        schema_id="schema-test",
        source_id="source-test",
        team_id=1,
        should_use_incremental_field=incremental,
        db_incremental_field_last_value=watermark,
        db_incremental_field_earliest_value=None,
        incremental_field="collected_at" if incremental else None,
        incremental_field_type=None,
        job_id="job-test",
        logger=structlog.get_logger(),
        reset_pipeline=False,
    )


def manager(state: dict[str, Any] | None = None) -> MagicMock:
    result = MagicMock(spec=ResumableSourceManager)
    result.can_resume.return_value = state is not None
    result.load_state.return_value = SurvicateResumeConfig(state=state) if state else None
    return result


def run(
    endpoint: str,
    resume_manager: MagicMock,
    incremental: bool = False,
    watermark: Any = None,
    attributes: str | None = None,
) -> tuple[list[dict[str, Any]], SourceResponse]:
    result = SurvicateSource().source_for_pipeline(
        SurvicateSourceConfig(api_key="fake-api-key", attribute_names=attributes),
        resume_manager,
        inputs(endpoint, incremental, watermark),
    )
    batches = cast(Iterable[list[dict[str, Any]]], result.items())
    return [row for batch in batches for row in batch], result


@responses.activate
@pytest.mark.parametrize(
    ("endpoint", "incremental", "watermark", "expected_end"),
    [
        ("responses", True, WATERMARK, WATERMARK),
        ("responses", True, datetime(2025, 4, 1, tzinfo=UTC), WATERMARK),
        ("responses", True, None, None),
        ("responses", False, WATERMARK, None),
        ("questions", False, WATERMARK, None),
    ],
)
def test_child_requests_and_parent_keys(
    endpoint: str, incremental: bool, watermark: Any, expected_end: str | None
) -> None:
    responses.get(BASE + "/surveys", json=page([{"id": "survey-a"}, {"id": "survey-b"}]))
    row = {"uuid": "response-a", "collected_at": WATERMARK} if endpoint == "responses" else {"id": 7}
    responses.get(BASE + f"/surveys/survey-a/{endpoint}", json=page([row]))
    responses.get(BASE + f"/surveys/survey-b/{endpoint}", json=page([row]))
    checkpoint = manager()

    rows, result = run(endpoint, checkpoint, incremental, watermark, " order_id, store, ,")

    assert rows == [{**row, "survey_id": "survey-a"}, {**row, "survey_id": "survey-b"}]
    assert result.primary_keys is not None
    assert len({tuple(row[key] for key in result.primary_keys) for row in rows}) == 2
    assert parse_qs(urlsplit(responses.calls[0].request.url).query) == {"items_per_page": ["100"]}
    for call in responses.calls[1:]:
        params = parse_qs(urlsplit(call.request.url).query)
        assert params.get("end") == ([expected_end] if expected_end else None)
        assert "start" not in params
        assert "survey_id" not in params
        assert params.get("attributes[]") == (["order_id", "store"] if endpoint == "responses" else None)
        assert call.request.headers["Authorization"] == "Basic fake-api-key"
    assert checkpoint.save_state.call_args.args[0].state["completed"] == [
        f"surveys/survey-a/{endpoint}",
        f"surveys/survey-b/{endpoint}",
    ]
    if incremental:
        assert result.sort_mode == "desc"


@responses.activate
@pytest.mark.parametrize("endpoint", ["questions", "responses"])
@pytest.mark.parametrize("resumed", [False, True])
def test_child_pagination_and_resume(endpoint: str, resumed: bool) -> None:
    params = {"start": "2025-05-01T00:00:00.000000Z", "items_per_page": "100"}
    if endpoint == "responses":
        params["end"] = WATERMARK
    next_url = f"/surveys/survey-b/{endpoint}?{urlencode(params)}"
    responses.get(BASE + "/surveys", json=page([{"id": "survey-a"}], "/surveys?start=older-survey"))
    responses.get(BASE + "/surveys?start=older-survey", json=page([{"id": "survey-b"}]))
    first_row = {"id": 7} if endpoint == "questions" else {"uuid": "response-a", "collected_at": WATERMARK}
    last_row = {"id": 8} if endpoint == "questions" else {"uuid": "response-b", "collected_at": WATERMARK}
    if not resumed:
        responses.get(BASE + f"/surveys/survey-a/{endpoint}", json=page([]))
        responses.get(BASE + f"/surveys/survey-b/{endpoint}", json=page([first_row], next_url))
    responses.get(BASE + next_url, json=page([last_row], next_url, False))
    state = {
        "completed": [f"surveys/survey-a/{endpoint}"],
        "current": f"surveys/survey-b/{endpoint}",
        "child_state": {"next_url": BASE + next_url},
    }
    checkpoint = manager(state if resumed else None)

    rows, _ = run(endpoint, checkpoint, endpoint == "responses", WATERMARK)

    expected = [last_row] if resumed else [first_row, last_row]
    assert rows == [{**row, "survey_id": "survey-b"} for row in expected]
    assert len(responses.calls) == (3 if resumed else 5)
    assert responses.calls[-1].request.url == BASE + next_url
    if not resumed:
        assert any(call.args[0].state == state for call in checkpoint.save_state.call_args_list)


@responses.activate
@pytest.mark.parametrize("status", [200, 401, 403, 404, 429, 500])
def test_credential_probe_and_error_mapping(status: int) -> None:
    responses.get(BASE + "/surveys", status=status, json=page([]) if status == 200 else {"message": "Unauthorized"})
    source = SurvicateSource()
    config = SurvicateSourceConfig(api_key="fake-api-key")
    if status in (429, 500):
        with pytest.raises(RESTClientRetryableError):
            source.validate_credentials(config, 1)
    elif status == 404:
        with pytest.raises(HTTPError):
            source.validate_credentials(config, 1)
    else:
        valid, error = source.validate_credentials(config, 1)
        assert valid is (status == 200)
        if status == 200:
            assert error is None
        elif status == 401:
            assert error == "Survicate rejected your API key. Check the key in Settings > Organization > Access Keys."
        else:
            assert error == "Survicate denied API access. Check that your plan includes the Data Export API."
        assert len(responses.calls) == 1
    assert responses.calls[0].request.headers["Authorization"] == "Basic fake-api-key"
    assert parse_qs(urlsplit(responses.calls[0].request.url).query) == {"items_per_page": ["1"]}


@responses.activate
@pytest.mark.parametrize("status", [401, 403])
def test_sync_auth_errors_match_non_retryable_patterns(status: int) -> None:
    responses.get(BASE + "/surveys", status=status, json={"message": "Unauthorized"})
    with pytest.raises(HTTPError) as exc:
        run("surveys", manager())
    assert any(pattern in str(exc.value) for pattern in SurvicateSource().get_non_retryable_errors())
    assert len(responses.calls) == 1


@responses.activate
@pytest.mark.parametrize("next_url", [None, "https://example.com/next", "//example.com/next"])
def test_invalid_pagination_link_fails(next_url: str | None) -> None:
    responses.get(BASE + "/surveys", json=page([], next_url, True))
    with pytest.raises(ValueError, match="invalid pagination link"):
        run("surveys", manager())
    assert len(responses.calls) == 1


@pytest.mark.parametrize("endpoint", ["invalid", "responses"])
def test_invalid_sync_input(endpoint: str) -> None:
    with pytest.raises(UnknownResourceError if endpoint == "invalid" else ValueError):
        run(endpoint, manager(), True, "invalid-date")
