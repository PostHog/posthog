from __future__ import annotations

import json
import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from uuid import UUID

import pytest
from unittest.mock import AsyncMock, patch

import httpx
from parameterized import parameterized
from posthoganalytics.ai.evaluations import EvaluationItem
from pydantic import SecretStr

from products.posthog_ai.eval_harness.engines.types import CaseResult, EvalSummary, ExperimentResult, ScorerResult
from products.posthog_ai.eval_harness.offline_results import (
    OfflineEvalPublisher,
    OfflineEvalSettings,
    OfflineEvalSuite,
    OfflineEvalUpload,
    OfflineUploadError,
)
from products.posthog_ai.eval_harness.test.offline_api import OfflineServer

EXPERIMENT_ID = "00000000-0000-4000-8000-000000000001"
SCORER_VERSIONS = {
    "boolean_metric": UUID("00000000-0000-4000-8000-000000000002"),
    "numeric_metric": UUID("00000000-0000-4000-8000-000000000003"),
}
SUITE = OfflineEvalSuite(
    key="sql/test",
    project_id=123,
    scorer_kinds={"boolean_metric": "boolean", "numeric_metric": "numeric"},
    scorer_versions=SCORER_VERSIONS,
)
STARTED_AT = datetime(2026, 1, 1, tzinfo=UTC)


def _publisher(*, link_traces: bool = False, suite: OfflineEvalSuite = SUITE) -> OfflineEvalPublisher:
    return OfflineEvalPublisher(
        OfflineEvalSettings(project_id=123, api_key=SecretStr("test-only-token"), scorer_versions=SCORER_VERSIONS),
        suite,
        application_trace_ids_enabled=link_traces,
    )


def _case(name: str = "query") -> CaseResult:
    return CaseResult(
        input={"name": name, "prompt": "Count example events"}, output={}, scores=dict.fromkeys(SCORER_VERSIONS, 1.0)
    )


def _prepare(
    publisher: OfflineEvalPublisher, cases: list[CaseResult], metadata: dict[str, object] | None = None
) -> OfflineEvalUpload:
    return publisher.prepare(
        experiment_id=EXPERIMENT_ID,
        experiment_name="sql-test",
        started_at=STARTED_AT,
        result=ExperimentResult(
            summary=EvalSummary(
                engine_name="braintrust",
                experiment_name="sql-test",
                scores={},
                experiment_url="https://braintrust.example.com/experiment/test",
            ),
            results=cases,
        ),
        metadata={"agent_model": "test-model", "git_sha": "captured-revision", **(metadata or {})},
    )


def _items(upload: OfflineEvalUpload) -> list[EvaluationItem]:
    items: dict[str, EvaluationItem] = {}
    for result in upload.results:
        assert isinstance(result.item, EvaluationItem)
        items[result.item_id] = result.item
    return list(items.values())


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
    ]
)
def test_prepare_preserves_score_types_and_distinguishes_missing_from_skipped(
    _name: str, scores: dict[str, float | None], error: str | None, status: str, error_code: str | None
) -> None:
    case = _case()
    case.scores = scores
    case.error = error
    case.metadata = {"scorer_errors": {"boolean_metric": "Judge failed"}}

    results = [result.to_dict() for result in _prepare(_publisher(), [case]).results]

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
        assert results[0]["payload"]["error_message"] == "Judge failed"


def test_prepare_preserves_successful_scores_when_another_scorer_fails() -> None:
    case = _case()
    case.error = "Scorer errors: boolean_metric"
    case.error_kind = "scorer"
    case.scorer_results = {
        "boolean_metric": ScorerResult(status="error", error_code="scorer_error", error_message="Judge failed")
    }

    results = [result.to_dict() for result in _prepare(_publisher(), [case]).results]

    assert results[0]["status"] == "error"
    assert results[0]["error_code"] == "scorer_error"
    assert results[1]["status"] == "ok"
    assert results[1]["value"] == 1.0


def test_prepare_assigns_stable_trial_ids_and_uses_captured_revision() -> None:
    publisher = _publisher()
    cases = [_case("query-a"), _case("query-b"), _case("query-a")]
    cases[0].trial_index = 1
    cases[2].trial_index = 0
    cases[1].scores = {"boolean_metric": None}

    upload = _prepare(publisher, cases)
    reordered = _prepare(publisher, list(reversed(cases)))
    items = [item.to_dict() for item in _items(upload)]

    assert {item.id for item in _items(upload)} == {item.id for item in _items(reordered)}
    assert [(item["case_key"], item["trial"]) for item in items] == [
        ("query-a", "1"),
        ("query-b", "0"),
        ("query-a", "0"),
    ]
    assert upload.experiment["expected_item_count"] == 3
    assert upload.experiment["expected_result_count"] == 6
    assert upload.experiment["application_version"] == "captured-revision"
    assert upload.experiment["dataset_revision_identifier"] == "captured-revision"
    assert items[0]["payload"]["metadata"]["braintrust_url"] == "https://braintrust.example.com/experiment/test"


def test_prepare_omits_raw_logs_and_oversized_fields_without_mutating_results() -> None:
    case = _case()
    original_output = {"raw_log": "local trace", "tool_result": "x" * (1100 * 1024), "answer": "There are 3 events"}
    case.output = original_output.copy()
    case.expected = {"large_fixture": "x" * (1100 * 1024)}
    case.metadata["not_json"] = object()

    payload = _items(_prepare(_publisher(), [case]))[0].to_dict()["payload"]

    assert "output" not in payload
    assert "expected_output" not in payload
    assert set(payload["metadata"]["omitted_fields"]) == {
        "output.raw_log",
        "output",
        "expected_output",
        "metadata",
    }
    assert case.output == original_output


@parameterized.expand(
    [
        ("null_output_key", {"invalid\x00key": "value"}, {}, "output"),
        ("null_metadata_key", {}, {"invalid\x00key": "value"}, "metadata"),
        ("surrogate_metadata_key", {}, {"invalid\ud800key": "value"}, "metadata"),
        (
            "many_output_fields",
            {f"field-{index}-" + "k" * 512: "x" * 1024 for index in range(2000)},
            {},
            "output",
        ),
        (
            "aggregate_metadata",
            {"details": "x" * (240 * 1024)},
            {f"metadata-{index}": "x" * (60 * 1024) for index in range(8)},
            "metadata",
        ),
    ]
)
def test_prepare_bounds_payload_details_without_losing_scores(
    _name: str, output: dict[str, object], metadata: dict[str, object], omitted_field: str
) -> None:
    case = _case()
    case.input["prompt"] = "i" * (240 * 1024)
    case.expected = "e" * (240 * 1024)
    original_output = {**output, "answer": "There are 3 events"}
    case.output = original_output.copy()

    upload = _prepare(_publisher(), [case], metadata)
    payload = _items(upload)[0].to_dict()["payload"]
    omitted = payload["metadata"]["omitted_fields"]

    if omitted_field == "output":
        assert "output" not in payload
    else:
        assert payload["output"] == original_output
    assert payload["input"] == case.input
    assert payload["expected_output"] == case.expected
    assert all(result.to_dict()["status"] == "ok" for result in upload.results)
    assert omitted == [omitted_field]
    assert len(json.dumps(payload, ensure_ascii=False).encode("utf-8")) < 1024 * 1024
    assert case.output == original_output


@parameterized.expand([("linked", True), ("unlinked", False)])
def test_prepare_preserves_rich_results_and_dataset_references(_name: str, link_traces: bool) -> None:
    publisher = _publisher(link_traces=link_traces)
    publisher.suite = OfflineEvalSuite(
        key="sql/rich",
        project_id=123,
        scorer_kinds={"boolean_metric": "categorical", "numeric_metric": "numeric"},
        scorer_versions=SCORER_VERSIONS,
        experiment_options={
            "prompt_version": "prompt-2",
            "run_source": "scheduled",
        },
    )
    case = _case()
    case.metadata.update(
        trace_id="application-trace", dataset_item_identifier="case-1", dataset_item_version_identifier="v2"
    )
    case.scorer_results = {
        "boolean_metric": ScorerResult(
            status="ok",
            value=["correct"],
            reasoning="Matches expected answer",
            metadata={"confidence": 0.9},
            evaluator_trace_id="judge-trace",
            evaluated_at=STARTED_AT,
        ),
        "numeric_metric": ScorerResult(status="ok", value=35.0),
    }
    upload = _prepare(publisher, [case])
    item = _items(upload)[0].to_dict()
    outcome = upload.results[0].to_dict()
    assert item.get("application_trace_id") == ("application-trace" if link_traces else None)
    assert item["dataset_item_identifier"] == "case-1"
    assert item["dataset_item_version_identifier"] == "v2"
    assert "dataset_item_version_id" not in item
    assert outcome["value"] == ["correct"]
    assert outcome["payload"]["reasoning"] == "Matches expected answer"
    assert outcome["payload"]["metadata"] == {"confidence": 0.9}
    assert outcome.get("evaluator_trace_id") == ("judge-trace" if link_traces else None)
    assert outcome["evaluated_at"] == STARTED_AT.isoformat()
    assert upload.results[1].to_dict()["value"] == 35.0
    assert upload.experiment["dataset_source"] == "repository"
    assert upload.experiment["dataset_identifier"] == "sql/rich"
    assert upload.experiment["dataset_revision_identifier"] == "captured-revision"
    assert upload.experiment["prompt_version"] == "prompt-2"
    assert upload.experiment["run_source"] == "scheduled"

    case.scorer_results["numeric_metric"] = ScorerResult(status="not_applicable", reasoning="No applicable operation")
    assert _prepare(publisher, [case]).results[1].to_dict()["status"] == "not_applicable"


def test_prepare_rejects_hosted_dataset_configuration() -> None:
    publisher = _publisher()
    publisher.suite = replace(SUITE, experiment_options={"dataset_revision_id": EXPERIMENT_ID})

    with pytest.raises(OfflineUploadError, match="Hosted datasets are not supported"):
        _prepare(publisher, [_case()])


def test_prepare_rejects_empty_scorer_enrollment() -> None:
    publisher = _publisher()
    publisher.suite = replace(SUITE, scorer_kinds={})

    with pytest.raises(OfflineUploadError, match="must enroll at least one scorer"):
        _prepare(publisher, [_case()])


@parameterized.expand(
    [
        (
            "oversized_metadata",
            ScorerResult(status="ok", value=0.75, metadata={"details": "x" * (256 * 1024)}),
            "metadata",
        ),
        ("unsupported_metadata", ScorerResult(status="ok", value=0.75, metadata={"details": object()}), "metadata"),
        ("unsupported_reasoning", ScorerResult(status="ok", value=0.75, reasoning="\ud800"), "reasoning"),
        ("oversized_reasoning", ScorerResult(status="ok", value=0.75, reasoning="x" * (256 * 1024)), "reasoning"),
        (
            "invalid_trace",
            ScorerResult(status="ok", value=0.75, evaluator_trace_id="invalid\x00trace"),
            "evaluator_trace_id",
        ),
        (
            "naive_time",
            ScorerResult(status="ok", value=0.75, evaluated_at=STARTED_AT.replace(tzinfo=None)),
            "evaluated_at",
        ),
        (
            "diagnostic_room",
            ScorerResult(status="ok", value=0.75, reasoning="x" * (256 * 1024 - 256), metadata={"details": object()}),
            "metadata",
        ),
    ]
)
def test_prepare_preserves_valid_scores_when_optional_details_cannot_be_uploaded(
    _name: str, scorer_result: ScorerResult, omitted_field: str
) -> None:
    case = _case()
    case.scorer_results["numeric_metric"] = scorer_result

    result = _prepare(_publisher(link_traces=True), [case]).results[1].to_dict()

    assert result["status"] == "ok"
    assert result["value"] == 0.75
    assert "error_code" not in result
    assert result["payload"]["metadata"]["omitted_fields"] == [omitted_field]
    if scorer_result.reasoning is not None and omitted_field != "reasoning":
        assert result["payload"]["reasoning"] == scorer_result.reasoning


@parameterized.expand([("rate_limit", 429), ("server_error", 503), ("timeout", 408), ("network_error", None)])
def test_publish_retries_identical_batches_and_completes_after_all_acknowledgments(
    _name: str, failure_status: int | None
) -> None:
    publisher = _publisher()
    upload = _prepare(publisher, [_case(f"query-{index}") for index in range(501)])
    server = OfflineServer()
    attempts: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        attempts.append(request)
        if len(attempts) == 2:
            if failure_status is None:
                raise httpx.ConnectError("connection lost", request=request)
            return httpx.Response(failure_status, headers={"Retry-After": "0"})
        return server.respond(request)

    with (
        patch("httpx.AsyncClient", new=partial(httpx.AsyncClient, transport=httpx.MockTransport(respond))),
        patch("posthoganalytics.ai.evaluations._transport.asyncio.sleep", new_callable=AsyncMock),
    ):
        url = asyncio.run(publisher.publish(upload))

    assert len(attempts) == 5
    assert attempts[1].content == attempts[2].content
    assert attempts[2].content != attempts[3].content
    assert attempts[-1].url.path.endswith("/complete/")
    assert attempts[0].headers["Authorization"] == "Bearer test-only-token"
    assert len(server.items) == 501
    assert len(server.results) == 1002
    assert url.endswith(f"/ai-evals/evaluations/offline/experiments/{EXPERIMENT_ID}")


@parameterized.expand(
    [
        ("success", None),
        ("forbidden", 403),
        ("server_error", 503),
        ("lost_response", "lost_response"),
        ("interrupted", "interrupted"),
    ]
)
def test_publish_tags_completed_results_without_repeating_mutable_updates(
    _name: str, tag_error: int | str | None
) -> None:
    publisher = _publisher(suite=replace(SUITE, tags=("team:example", "component:example")))
    upload = _prepare(publisher, [_case()])
    server = OfflineServer()
    tag_requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        if request.method == "PATCH":
            tag_requests.append(request)
            assert server.status == "completed"
            if isinstance(tag_error, int):
                return httpx.Response(tag_error)
            response = server.respond(request)
            if tag_error == "lost_response":
                raise httpx.ReadError("Lost tag acknowledgment", request=request)
            if tag_error == "interrupted":
                raise asyncio.CancelledError
            return response
        return server.respond(request)

    with patch("httpx.AsyncClient", new=partial(httpx.AsyncClient, transport=httpx.MockTransport(respond))):
        assert asyncio.run(publisher.publish(upload)).endswith(EXPERIMENT_ID)
        if tag_error == "interrupted":
            with pytest.raises(asyncio.CancelledError):
                asyncio.run(publisher.tag(upload))
        else:
            asyncio.run(publisher.tag(upload))
        assert server.status == "completed"
        assert len(server.results) == 2
        assert "tags" not in server.experiment
        assert server.tags == ([] if isinstance(tag_error, int) else list(upload.tags))

        server.tags = ["edited-after-upload"]
        asyncio.run(publisher.publish(upload))
        asyncio.run(publisher.tag(upload))

    assert len(tag_requests) == 1
    assert json.loads(tag_requests[0].content) == {"tags": list(upload.tags)}
    assert server.tags == ["edited-after-upload"]


@parameterized.expand(
    [
        ("bad_request", 400),
        ("forbidden", 403),
        ("retry_exhausted", 503),
        ("invalid_ack", 200),
        ("long_retry_after", 429),
        ("unsafe_diagnostics", 400, False),
    ]
)
def test_publish_does_not_complete_without_confirmed_persistence(
    _name: str, failure_status: int, safe_diagnostics: bool = True
) -> None:
    publisher = _publisher()
    upload = _prepare(publisher, [_case()])
    server = OfflineServer()
    attempts: list[httpx.Request] = []
    code = {
        400: "invalid_input",
        403: "permission_denied",
        503: "unavailable",
        429: "throttled",
        200: "invalid_response",
    }[failure_status]
    private_detail = "do-not-log-example-evaluation-payload"
    retry_after = 45 if failure_status == 429 else 0

    def respond(request: httpx.Request) -> httpx.Response:
        attempts.append(request)
        if len(attempts) == 1 or request.url.path.endswith("/fail/"):
            return server.respond(request)
        return httpx.Response(
            failure_status,
            json={
                "code": code if safe_diagnostics else "invalid\n" + private_detail,
                "attr": "results.0.value" if safe_diagnostics else "results.0.value\n" + private_detail,
                "detail": private_detail,
                "errors": [{"code": "invalid_input", "attr": "results.0.value", "detail": private_detail}],
            },
            headers={"Retry-After": str(retry_after)},
        )

    with (
        patch("httpx.AsyncClient", new=partial(httpx.AsyncClient, transport=httpx.MockTransport(respond))),
        patch("posthoganalytics.ai.evaluations._transport.asyncio.sleep", new_callable=AsyncMock),
        pytest.raises(OfflineUploadError) as raised,
    ):
        asyncio.run(publisher.publish(upload))
    assert len(attempts) == (5 if failure_status == 503 else 3)
    assert all(request.url.path.endswith("/upload/") for request in attempts[1:-1])
    assert server.status == "failed"
    error = raised.value
    assert error.status == (None if failure_status == 200 else failure_status)
    assert error.code == (code if safe_diagnostics else None)
    assert error.attr == ("results.0.value" if safe_diagnostics and failure_status != 200 else None)
    assert error.persistence == ("unknown" if failure_status in (200, 503) else "rejected")
    assert error.retry_after == (None if failure_status == 200 else retry_after)
    assert error.acknowledged_item_count == error.acknowledged_result_count == error.completed_chunk_count == 0
    assert error.pending_result_count == 2
    assert error.failed_index == 0
    assert private_detail not in str(error)
    if failure_status == 403:
        assert "offline_evaluation_ingestion:write" in str(error)
    if failure_status == 429:
        assert "retry after 45s" in str(error)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("failure_path", "cleanup_error"), [("complete", None), ("upload", "api"), ("upload", "timeout")]
)
async def test_publish_preserves_original_error_when_closing_a_failed_experiment(
    monkeypatch: pytest.MonkeyPatch, failure_path: str, cleanup_error: str | None
) -> None:
    publisher = _publisher()
    server = OfflineServer()
    paths: list[str] = []
    loop = asyncio.get_running_loop()
    original_time = loop.time
    clock_offset = 0.0
    monkeypatch.setattr(loop, "time", lambda: original_time() + clock_offset)

    async def respond(request: httpx.Request) -> httpx.Response:
        nonlocal clock_offset
        paths.append(request.url.path)
        if request.url.path.endswith("/fail/"):
            if cleanup_error == "api":
                return httpx.Response(403, json={"code": "permission_denied"})
            if cleanup_error == "timeout":
                clock_offset += 10
                await asyncio.Event().wait()
        if request.url.path.endswith(f"/{failure_path}/"):
            return httpx.Response(400, json={"code": "invalid_input"})
        return server.respond(request)

    monkeypatch.setattr(httpx, "AsyncClient", partial(httpx.AsyncClient, transport=httpx.MockTransport(respond)))
    with pytest.raises(OfflineUploadError) as raised:
        await publisher.publish(_prepare(publisher, [_case()]))

    assert raised.value.status == 400
    assert raised.value.code == "invalid_input"
    assert paths[-1].endswith("/fail/")
    assert server.status == ("failed" if cleanup_error is None else "uploading")


@pytest.mark.parametrize("interrupted", [False, True])
def test_publish_preserves_partial_success_after_failure_or_interruption(interrupted: bool) -> None:
    publisher = _publisher()
    cases = [_case(f"query-{index}") for index in range(501)]
    cases[0].output = {"large_integer": 2**80}
    upload = _prepare(publisher, cases)
    server = OfflineServer()
    attempts: list[httpx.Request] = []
    reject = True

    def respond(request: httpx.Request) -> httpx.Response:
        attempts.append(request)
        if reject and request.url.path.endswith("/upload/") and server.results:
            if interrupted:
                raise asyncio.CancelledError
            return httpx.Response(400)
        return server.respond(request)

    with patch("httpx.AsyncClient", new=partial(httpx.AsyncClient, transport=httpx.MockTransport(respond))):
        with pytest.raises(asyncio.CancelledError if interrupted else OfflineUploadError) as raised:
            asyncio.run(publisher.publish(upload))
        assert len(server.results) == 1000
        if interrupted:
            assert server.status == "uploading"
            reject = False
            asyncio.run(publisher.publish(upload))
            assert len(server.results) == 1002
            assert len(server.items) == 501
            assert attempts[0].content == attempts[3].content
            assert attempts[1].content == attempts[4].content
        else:
            error = raised.value
            assert isinstance(error, OfflineUploadError)
            assert error.acknowledged_item_count == 500
            assert error.acknowledged_result_count == 1000
            assert error.completed_chunk_count == 1
            assert error.pending_result_count == 2
            assert error.failed_index == 1000
            assert "acknowledged 500 items and 1000 results" in str(error)
            assert "2 results await acknowledgment" in str(error)
            assert server.status == "failed"
            assert len(server.items) == 500
    first_item = json.loads(attempts[1].content)["items"][0]
    assert first_item["payload"]["output"]["large_integer"] == 2**80


@parameterized.expand([("project", "https://us.posthog.com", 456), ("host", "https://eu.posthog.com", 123)])
def test_publish_refuses_a_different_destination(_name: str, host: str, project_id: int) -> None:
    publisher = _publisher()
    upload = replace(_prepare(publisher, [_case()]), host=host, project_id=project_id)
    server = OfflineServer()
    with (
        patch("httpx.AsyncClient", new=partial(httpx.AsyncClient, transport=httpx.MockTransport(server.respond))),
        pytest.raises(OfflineUploadError, match="destination differs"),
    ):
        asyncio.run(publisher.publish(upload))
    assert server.requests == []


@parameterized.expand(
    [
        ("us_ingestion", "https://us.i.posthog.com", "https://us.posthog.com"),
        ("eu_ingestion", "https://eu.i.posthog.com/", "https://eu.posthog.com"),
        ("legacy_app", "https://app.posthog.com", "https://us.posthog.com"),
        ("default_port", " https://US.I.POSTHOG.COM:443/ ", "https://us.posthog.com"),
        ("app", "https://us.posthog.com", "https://us.posthog.com"),
        ("custom", "https://posthog.example.com:8443", "https://posthog.example.com:8443"),
        ("custom_cloud_port", "https://us.i.posthog.com:8443", "https://us.i.posthog.com:8443"),
        ("ipv6", "https://[::1]:8443", "https://[::1]:8443"),
        ("localhost", "http://localhost:8010", "http://localhost:8010"),
        ("loopback", "http://127.0.0.1:8010/", "http://127.0.0.1:8010"),
        ("loopback_ipv6", "http://[::1]:8010", "http://[::1]:8010"),
    ]
)
def test_publish_uses_the_same_origin_for_requests_and_result_links(_name: str, host: str, origin: str) -> None:
    environment = {
        "POSTHOG_OFFLINE_EVAL_API_KEY": "test-only-token",
        "POSTHOG_OFFLINE_EVAL_HOST": host,
    }
    with patch.dict("os.environ", environment, clear=True):
        settings = OfflineEvalSettings.from_env(SUITE)
    assert settings is not None
    assert settings.host == origin
    publisher = OfflineEvalPublisher(settings, SUITE)
    upload = _prepare(publisher, [_case()])
    server = OfflineServer()

    with patch("httpx.AsyncClient", new=partial(httpx.AsyncClient, transport=httpx.MockTransport(server.respond))):
        url = asyncio.run(publisher.publish(upload))

    assert all(str(request.url).startswith(f"{origin}/api/") for request in server.requests)
    assert url == f"{origin}/project/123/ai-evals/evaluations/offline/experiments/{EXPERIMENT_ID}"


def test_local_config_routes_uploads_to_local_project_and_scorer_versions(tmp_path: Path) -> None:
    local_versions = {
        str(SCORER_VERSIONS["boolean_metric"]): "00000000-0000-4000-8000-000000000004",
        str(SCORER_VERSIONS["numeric_metric"]): "00000000-0000-4000-8000-000000000005",
    }
    config = tmp_path / "local.json"
    config.write_text(json.dumps({"project_id": 456, "scorer_versions": local_versions}))
    with patch.dict(
        "os.environ",
        {
            "POSTHOG_OFFLINE_EVAL_API_KEY": "test-only-token",
            "POSTHOG_OFFLINE_EVAL_HOST": "http://localhost:8010",
            "POSTHOG_OFFLINE_EVAL_LOCAL_CONFIG": str(config),
        },
        clear=True,
    ):
        settings = OfflineEvalSettings.from_env(SUITE)
    assert settings is not None
    publisher = OfflineEvalPublisher(settings, SUITE)
    upload = _prepare(publisher, [_case()])
    server = OfflineServer()

    with patch("httpx.AsyncClient", new=partial(httpx.AsyncClient, transport=httpx.MockTransport(server.respond))):
        url = asyncio.run(publisher.publish(upload))

    assert all(str(request.url).startswith("http://localhost:8010/api/projects/456/") for request in server.requests)
    assert [str(result.scorer_version_id) for result in upload.results] == list(local_versions.values())
    assert url == f"http://localhost:8010/project/456/ai-evals/evaluations/offline/experiments/{EXPERIMENT_ID}"
    assert SUITE.project_id == 123
    assert SUITE.scorer_versions == SCORER_VERSIONS


@pytest.mark.parametrize(
    "contents,host",
    [
        (None, "http://localhost:8010"),
        ("invalid json", "http://localhost:8010"),
        ('{"project_id": 0, "scorer_versions": {}}', "http://localhost:8010"),
        ('{"project_id": 456, "scorer_versions": {}}', "http://localhost:8010"),
        ('{"project_id": 456, "scorer_versions": {"invalid": "invalid"}}', "http://localhost:8010"),
        (
            json.dumps(
                {
                    "project_id": 456,
                    "scorer_versions": {str(version): str(version) for version in SCORER_VERSIONS.values()},
                }
            ),
            "https://us.posthog.com",
        ),
        (
            json.dumps(
                {
                    "project_id": 456,
                    "scorer_versions": dict.fromkeys(
                        map(str, SCORER_VERSIONS.values()), "00000000-0000-4000-8000-000000000004"
                    ),
                }
            ),
            "http://localhost:8010",
        ),
    ],
    ids=[
        "missing_file",
        "invalid_json",
        "invalid_project",
        "missing_versions",
        "invalid_uuid",
        "cloud_host",
        "duplicate_versions",
    ],
)
def test_invalid_local_config_never_falls_back_to_catalog(tmp_path: Path, contents: str | None, host: str) -> None:
    config = tmp_path / "local.json"
    if contents is not None:
        config.write_text(contents)
    with (
        patch.dict(
            "os.environ",
            {
                "POSTHOG_OFFLINE_EVAL_API_KEY": "test-only-token",
                "POSTHOG_OFFLINE_EVAL_HOST": host,
                "POSTHOG_OFFLINE_EVAL_LOCAL_CONFIG": str(config),
            },
            clear=True,
        ),
        pytest.raises(OfflineUploadError),
    ):
        OfflineEvalSettings.from_env(SUITE)


def test_settings_use_each_suite_destination_with_only_an_api_key() -> None:
    environment = {"POSTHOG_OFFLINE_EVAL_API_KEY": "test-only-token"}
    with patch.dict("os.environ", environment, clear=True):
        for project_id, (metric, version) in enumerate(SCORER_VERSIONS.items(), start=123):
            suite = OfflineEvalSuite(
                key=metric,
                project_id=project_id,
                scorer_kinds={metric: "numeric"},
                scorer_versions={metric: version},
            )
            settings = OfflineEvalSettings.from_env(suite)
            assert settings is not None
            upload = _prepare(OfflineEvalPublisher(settings, suite), [_case()])
            assert upload.project_id == project_id
            assert [result.scorer_version_id for result in upload.results] == [str(version)]


@parameterized.expand(
    [
        ("invalid_project", replace(SUITE, project_id=0)),
        (
            "missing_metric",
            replace(SUITE, scorer_versions={"boolean_metric": SCORER_VERSIONS["boolean_metric"]}),
        ),
        (
            "duplicate_versions",
            replace(SUITE, scorer_versions=dict.fromkeys(SCORER_VERSIONS, SCORER_VERSIONS["boolean_metric"])),
        ),
    ]
)
def test_settings_reject_invalid_suite_configuration(_name: str, suite: OfflineEvalSuite) -> None:
    with (
        patch.dict("os.environ", {"POSTHOG_OFFLINE_EVAL_API_KEY": "test-only-token"}, clear=True),
        pytest.raises(OfflineUploadError),
    ):
        OfflineEvalSettings.from_env(suite)


@parameterized.expand(
    [
        ("blank_key", {"POSTHOG_OFFLINE_EVAL_API_KEY": " "}),
        ("key_newline", {"POSTHOG_OFFLINE_EVAL_API_KEY": "test-only-token\n"}),
        ("key_internal_space", {"POSTHOG_OFFLINE_EVAL_API_KEY": "test-only token"}),
        ("key_leading_tab", {"POSTHOG_OFFLINE_EVAL_API_KEY": "\ttest-only-token"}),
        ("insecure_host", {"POSTHOG_OFFLINE_EVAL_HOST": "http://posthog.example.com"}),
        ("loopback_suffix", {"POSTHOG_OFFLINE_EVAL_HOST": "http://localhost.example.com:8010"}),
        ("loopback_credentials", {"POSTHOG_OFFLINE_EVAL_HOST": "http://localhost@posthog.example.com:8010"}),
        ("malformed_host", {"POSTHOG_OFFLINE_EVAL_HOST": "https://["}),
        ("invalid_port", {"POSTHOG_OFFLINE_EVAL_HOST": "https://posthog.example.com:invalid"}),
        ("host_credentials", {"POSTHOG_OFFLINE_EVAL_HOST": "https://token@posthog.example.com"}),
    ]
)
def test_settings_reject_invalid_environment(_name: str, overrides: dict[str, str]) -> None:
    environment = {
        "POSTHOG_OFFLINE_EVAL_API_KEY": "test-only-token",
        **overrides,
    }
    with patch.dict("os.environ", environment, clear=True), pytest.raises(OfflineUploadError):
        OfflineEvalSettings.from_env(SUITE)


@parameterized.expand(
    [
        ("dataset_identifier_type", "dataset_item_identifier", 42, "dataset_item_identifier"),
        (
            "dataset_version_identifier",
            "dataset_item_version_identifier",
            "bad\x00version",
            "dataset_item_version_identifier",
        ),
        ("trace_identifier", "trace_id", "bad\x00trace", "application_trace_id"),
        ("long_case_key", "name", "x" * 256, "case_key"),
    ]
)
def test_prepare_preserves_every_case_when_optional_item_references_are_invalid(
    _name: str, field: str, value: str | int, omitted_field: str
) -> None:
    healthy, malformed = _case("healthy"), _case("malformed")
    if field == "name":
        malformed.input["name"] = value
    else:
        malformed.metadata[field] = value
    malformed.metadata["dataset_item_identifier"] = malformed.metadata.get("dataset_item_identifier", "valid-case")

    upload = _prepare(_publisher(link_traces=True), [healthy, malformed])

    assert len(_items(upload)) == 2
    assert len(upload.results) == 4
    assert all(result.to_dict()["status"] == "ok" for result in upload.results)
    assert _items(upload)[0].to_dict()["case_key"] == "healthy"
    item = _items(upload)[1].to_dict()
    assert omitted_field not in item
    assert omitted_field in item["payload"]["metadata"]["omitted_fields"]
    if omitted_field != "dataset_item_identifier":
        assert item["dataset_item_identifier"] == "valid-case"
