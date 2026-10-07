from __future__ import annotations

import json
import asyncio
from datetime import UTC, datetime
from functools import partial
from typing import cast
from uuid import UUID

import pytest
from unittest.mock import AsyncMock, patch

import httpx
from parameterized import parameterized
from pydantic import SecretStr

from products.posthog_ai.eval_harness.engines.types import CaseResult, EvalSummary, ExperimentResult
from products.posthog_ai.eval_harness.offline_results import (
    OfflineEvalPublisher,
    OfflineEvalSettings,
    OfflineEvalSuite,
    OfflineUploadError,
)

EXPERIMENT_ID = "00000000-0000-4000-8000-000000000001"
SCORER_VERSIONS = {
    "boolean_metric": UUID("00000000-0000-4000-8000-000000000002"),
    "numeric_metric": UUID("00000000-0000-4000-8000-000000000003"),
}
SUITE = OfflineEvalSuite(key="sql/test", scorer_kinds={"boolean_metric": "boolean", "numeric_metric": "numeric"})


def _publisher() -> OfflineEvalPublisher:
    return OfflineEvalPublisher(
        OfflineEvalSettings(project_id=123, api_key=SecretStr("test-only-token"), scorer_versions=SCORER_VERSIONS),
        SUITE,
    )


def _case(name: str = "query") -> CaseResult:
    return CaseResult(
        input={"name": name, "prompt": "Count example events"}, output={}, scores=dict.fromkeys(SCORER_VERSIONS, 1.0)
    )


def _prepare(publisher: OfflineEvalPublisher, cases: list[CaseResult]) -> dict[str, object]:
    with patch(
        "products.posthog_ai.eval_harness.offline_results.subprocess.check_output", return_value="test-revision\n"
    ):
        return publisher.prepare(
            experiment_id=EXPERIMENT_ID,
            experiment_name="sql-test",
            started_at=datetime(2026, 1, 1, tzinfo=UTC),
            result=ExperimentResult(
                summary=EvalSummary(
                    engine_name="braintrust",
                    experiment_name="sql-test",
                    scores={},
                    experiment_url="https://braintrust.example.com/experiment/test",
                ),
                results=cases,
            ),
            metadata={"agent_model": "test-model"},
        )


def _batches(upload: dict[str, object]) -> list[dict[str, list[dict[str, object]]]]:
    return cast(list[dict[str, list[dict[str, object]]]], upload["batches"])


@parameterized.expand(
    [
        ("zero", {"boolean_metric": 0.0, "numeric_metric": 0.0}, None, "ok", None),
        ("one", {"boolean_metric": 1.0, "numeric_metric": 1.0}, None, "ok", None),
        ("skipped", {"boolean_metric": None, "numeric_metric": None}, None, "skipped", None),
        ("missing", {}, None, "error", "missing_score"),
        ("task_error", {"boolean_metric": 1.0, "numeric_metric": 1.0}, "Agent failed", "error", "task_error"),
        (
            "not_finite",
            {"boolean_metric": float("nan"), "numeric_metric": float("inf")},
            None,
            "error",
            "invalid_score",
        ),
        ("out_of_range", {"boolean_metric": 0.5, "numeric_metric": -0.1}, None, "error", "invalid_score"),
    ]
)
def test_prepare_preserves_score_types_and_distinguishes_missing_from_skipped(
    _name: str, scores: dict[str, float | None], error: str | None, status: str, error_code: str | None
) -> None:
    case = _case()
    case.scores = scores
    case.error = error
    case.metadata = {"scorer_errors": {"boolean_metric": "Judge failed"}}

    results = _batches(_prepare(_publisher(), [case]))[0]["results"]

    assert [result["scorer_version_id"] for result in results] == [str(version) for version in SCORER_VERSIONS.values()]
    assert [result["status"] for result in results] == [status, status]
    if status == "ok":
        assert results[0]["value"] is bool(scores["boolean_metric"])
        assert type(results[1]["value"]) is float
        assert results[1]["value"] == scores["numeric_metric"]
    else:
        assert all("value" not in result for result in results)
    if error_code is not None:
        assert [result["error_code"] for result in results] == [error_code, error_code]
    if error_code == "missing_score":
        assert results[0]["payload"] == {"error_message": "Judge failed"}


def test_prepare_assigns_stable_distinct_items_for_repeated_trials_and_counts_every_score() -> None:
    publisher = _publisher()
    cases = [_case("query-a"), _case("query-b"), _case("query-a")]
    cases[1].scores = {"boolean_metric": None}

    upload = _prepare(publisher, cases)
    items = _batches(upload)[0]["items"]
    results = _batches(upload)[0]["results"]

    assert upload == _prepare(publisher, cases)
    assert len({item["id"] for item in items}) == 3
    assert [(item["case_key"], item["trial"]) for item in items] == [
        ("query-a", "0"),
        ("query-b", "0"),
        ("query-a", "1"),
    ]
    assert {result["item_id"] for result in results} == {item["id"] for item in items}
    assert [sum(result["item_id"] == item["id"] for result in results) for item in items] == [2, 2, 2]
    experiment = cast(dict[str, object], upload["experiment"])
    assert experiment["expected_item_count"] == 3
    assert experiment["expected_result_count"] == 6
    payload = cast(dict[str, object], items[0]["payload"])
    assert (
        cast(dict[str, object], payload["metadata"])["braintrust_url"]
        == "https://braintrust.example.com/experiment/test"
    )


def test_prepare_omits_raw_logs_and_oversized_fields_without_mutating_braintrust_results() -> None:
    case = _case()
    original_output = {"raw_log": "local trace", "tool_result": "x" * (300 * 1024), "answer": "There are 3 events"}
    case.output = original_output.copy()
    case.expected = {"large_fixture": "x" * (300 * 1024)}

    item = _batches(_prepare(_publisher(), [case]))[0]["items"][0]

    payload = cast(dict[str, object], item["payload"])
    assert payload["output"] == {"answer": "There are 3 events"}
    assert "expected_output" not in payload
    metadata = cast(dict[str, object], payload["metadata"])
    assert set(cast(dict[str, object], metadata["omitted_fields"])) == {
        "output.raw_log",
        "output.tool_result",
        "expected_output",
    }
    assert case.output == original_output


@parameterized.expand([("result_count", 501, 0), ("encoded_bytes", 30, 100 * 1024)])
def test_prepare_batches_under_both_api_limits_without_losing_items(_name: str, count: int, output_length: int) -> None:
    cases = [_case(f"query-{index}") for index in range(count)]
    for case in cases:
        case.output = {"answer": "é" * output_length}

    batches = _batches(_prepare(_publisher(), cases))

    assert len(batches) > 1
    assert sum(len(batch["items"]) for batch in batches) == count
    assert sum(len(batch["results"]) for batch in batches) == 2 * count
    for batch in batches:
        assert len(batch["results"]) <= 1000
        assert len(json.dumps(batch, ensure_ascii=False, separators=(",", ":")).encode()) <= 4 * 1024 * 1024
        assert {result["item_id"] for result in batch["results"]} == {item["id"] for item in batch["items"]}


@parameterized.expand([("rate_limit", 429), ("server_error", 503), ("network_error", None)])
def test_publish_retries_identical_batches_and_only_completes_after_all_are_accepted(
    _name: str, failure_status: int | None
) -> None:
    publisher = _publisher()
    upload = _prepare(publisher, [_case(f"query-{index}") for index in range(501)])
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 2:
            if failure_status is None:
                raise httpx.ConnectError("connection lost", request=request)
            return httpx.Response(failure_status, headers={"Retry-After": "0"})
        return httpx.Response(202)

    client_factory = partial(httpx.AsyncClient, transport=httpx.MockTransport(respond))
    with (
        patch("products.posthog_ai.eval_harness.offline_results.httpx.AsyncClient", new=client_factory),
        patch("products.posthog_ai.eval_harness.offline_results.asyncio.sleep", new_callable=AsyncMock),
    ):
        url = asyncio.run(publisher.publish(upload))

    base = f"/api/projects/123/ai_observability/offline_experiments/{EXPERIMENT_ID}"
    assert [request.url.path for request in requests] == [
        "/api/projects/123/ai_observability/offline_experiments/",
        f"{base}/upload/",
        f"{base}/upload/",
        f"{base}/upload/",
        f"{base}/complete/",
    ]
    assert requests[1].content == requests[2].content
    assert requests[2].content != requests[3].content
    assert requests[0].headers["Authorization"] == "Bearer test-only-token"
    assert url.endswith(f"/ai-evals/evaluations/offline/experiments/{EXPERIMENT_ID}")


@parameterized.expand([("bad_request", 400), ("forbidden", 403), ("retry_exhausted", 503)])
def test_publish_does_not_complete_when_a_batch_is_rejected(_name: str, failure_status: int) -> None:
    publisher = _publisher()
    upload = _prepare(publisher, [_case()])
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(201 if len(requests) == 1 else failure_status, headers={"Retry-After": "0"})

    client_factory = partial(httpx.AsyncClient, transport=httpx.MockTransport(respond))
    with (
        patch("products.posthog_ai.eval_harness.offline_results.httpx.AsyncClient", new=client_factory),
        patch("products.posthog_ai.eval_harness.offline_results.asyncio.sleep", new_callable=AsyncMock),
        pytest.raises(OfflineUploadError, match=f"HTTP {failure_status}"),
    ):
        asyncio.run(publisher.publish(upload))

    assert len(requests) == (4 if failure_status == 503 else 2)
    assert all(request.url.path.endswith("/upload/") for request in requests[1:])
    assert len({request.content for request in requests[1:]}) == 1


@parameterized.expand([("original_destination", "123"), ("changed_destination", "456")])
def test_replay_uses_saved_versions_and_refuses_a_different_destination(_name: str, project_id: str) -> None:
    upload = json.loads(json.dumps(_prepare(_publisher(), [_case()])))
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200)

    environment = {
        "POSTHOG_OFFLINE_EVAL_API_KEY": "test-only-token",
        "POSTHOG_OFFLINE_EVAL_PROJECT_ID": project_id,
        "POSTHOG_OFFLINE_EVAL_SCORER_VERSIONS": "ignored-during-replay",
    }
    client_factory = partial(httpx.AsyncClient, transport=httpx.MockTransport(respond))
    with (
        patch.dict("os.environ", environment, clear=True),
        patch("products.posthog_ai.eval_harness.offline_results.httpx.AsyncClient", new=client_factory),
    ):
        settings = OfflineEvalSettings.from_env()
        assert settings is not None
        publisher = OfflineEvalPublisher(settings, OfflineEvalSuite(key="replay", scorer_kinds={}))
        if project_id == "123":
            asyncio.run(publisher.publish(upload))
            assert json.loads(requests[0].content) == upload["experiment"]
            assert json.loads(requests[1].content) == upload["batches"][0]
            assert requests[2].url.path.endswith("/complete/")
        else:
            with pytest.raises(OfflineUploadError, match="destination differs"):
                asyncio.run(publisher.publish(upload))
            assert requests == []


@parameterized.expand(
    [
        ("missing_key", {"POSTHOG_OFFLINE_EVAL_API_KEY": ""}),
        ("malformed_versions", {"POSTHOG_OFFLINE_EVAL_SCORER_VERSIONS": "not-json"}),
        (
            "missing_metric",
            {
                "POSTHOG_OFFLINE_EVAL_SCORER_VERSIONS": json.dumps(
                    {"boolean_metric": str(SCORER_VERSIONS["boolean_metric"])}
                )
            },
        ),
        (
            "duplicate_versions",
            {
                "POSTHOG_OFFLINE_EVAL_SCORER_VERSIONS": json.dumps(
                    dict.fromkeys(SCORER_VERSIONS, str(SCORER_VERSIONS["boolean_metric"]))
                )
            },
        ),
        ("insecure_host", {"POSTHOG_OFFLINE_EVAL_HOST": "http://posthog.example.com"}),
        ("malformed_host", {"POSTHOG_OFFLINE_EVAL_HOST": "https://["}),
        ("invalid_port", {"POSTHOG_OFFLINE_EVAL_HOST": "https://posthog.example.com:invalid"}),
        ("host_credentials", {"POSTHOG_OFFLINE_EVAL_HOST": "https://token@posthog.example.com"}),
    ]
)
def test_settings_reject_partial_or_ambiguous_configuration(_name: str, overrides: dict[str, str]) -> None:
    environment = {
        "POSTHOG_OFFLINE_EVAL_API_KEY": "test-only-token",
        "POSTHOG_OFFLINE_EVAL_PROJECT_ID": "123",
        "POSTHOG_OFFLINE_EVAL_SCORER_VERSIONS": json.dumps(
            {metric: str(version) for metric, version in SCORER_VERSIONS.items()}
        ),
        **overrides,
    }
    with patch.dict("os.environ", environment, clear=True), pytest.raises(OfflineUploadError):
        OfflineEvalSettings.from_env(SUITE)
