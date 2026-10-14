from __future__ import annotations

import json
import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from uuid import UUID

import pytest
from unittest.mock import AsyncMock, patch

import httpx
from parameterized import parameterized
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
SUITE = OfflineEvalSuite(key="sql/test", scorer_kinds={"boolean_metric": "boolean", "numeric_metric": "numeric"})
STARTED_AT = datetime(2026, 1, 1, tzinfo=UTC)


def _publisher(*, link_traces: bool = False) -> OfflineEvalPublisher:
    return OfflineEvalPublisher(
        OfflineEvalSettings(project_id=123, api_key=SecretStr("test-only-token"), scorer_versions=SCORER_VERSIONS),
        SUITE,
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
    items = [item.to_dict() for item in upload.items]

    assert {item.id for item in upload.items} == {item.id for item in reordered.items}
    assert [(item["case_key"], item["trial"]) for item in items] == [
        ("query-a", "1"),
        ("query-b", "0"),
        ("query-a", "0"),
    ]
    assert {result.item_id for result in upload.results} == {item.id for item in upload.items}
    assert upload.experiment["expected_item_count"] == 3
    assert upload.experiment["expected_result_count"] == 6
    assert upload.experiment["application_version"] == "captured-revision"
    assert upload.experiment["dataset_revision_identifier"] == "captured-revision"
    assert items[0]["payload"]["metadata"]["braintrust_url"] == "https://braintrust.example.com/experiment/test"


def test_prepare_omits_raw_logs_and_oversized_fields_without_mutating_results() -> None:
    case = _case()
    original_output = {"raw_log": "local trace", "tool_result": "x" * (1100 * 1024), "answer": "There are 3 events"}
    case.output = original_output.copy()
    case.expected = {"large_fixture": "x" * (300 * 1024)}
    case.metadata["not_json"] = object()

    payload = _prepare(_publisher(), [case]).items[0].to_dict()["payload"]

    assert payload["output"] == {"answer": "There are 3 events"}
    assert "expected_output" not in payload
    assert set(payload["metadata"]["omitted_fields"]) == {
        "output.raw_log",
        "output.tool_result",
        "expected_output",
        "metadata.case",
    }
    assert case.output == original_output


@parameterized.expand(
    [
        ("null_output_key", {"invalid\x00key": "x" * (300 * 1024)}, {}),
        ("null_metadata_key", {}, {"invalid\x00key": "value"}),
        ("surrogate_metadata_key", {}, {"invalid\ud800key": "value"}),
        (
            "many_output_fields",
            {f"field-{index}-" + "k" * 512: "x" * 1024 for index in range(2000)},
            {},
        ),
        (
            "aggregate_metadata",
            {"details": "x" * (240 * 1024)},
            {f"metadata-{index}": "x" * (60 * 1024) for index in range(8)},
        ),
    ]
)
def test_prepare_bounds_payload_details_without_losing_scores(
    _name: str, output: dict[str, object], metadata: dict[str, object]
) -> None:
    case = _case()
    case.input["prompt"] = "i" * (240 * 1024)
    case.expected = "e" * (240 * 1024)
    original_output = {**output, "answer": "There are 3 events"}
    case.output = original_output.copy()

    encode_json = json.dumps
    encoding_calls = 0

    def bounded_encode_json(value: object, **kwargs: Any) -> str:
        nonlocal encoding_calls
        encoding_calls += 1
        assert encoding_calls <= 8 * len(original_output) + 500
        return encode_json(value, **kwargs)

    with patch.object(json, "dumps", bounded_encode_json):
        upload = _prepare(_publisher(), [case], metadata)
    payload = upload.items[0].to_dict()["payload"]
    omitted = payload["metadata"]["omitted_fields"]

    assert payload["output"]["answer"] == "There are 3 events"
    assert payload["input"] == case.input
    assert payload["expected_output"] == case.expected
    assert all(result.to_dict()["status"] == "ok" for result in upload.results)
    assert omitted
    assert all("\x00" not in key and len(key) <= 128 for key in omitted)
    assert len(json.dumps(omitted, ensure_ascii=False).encode("utf-8")) < 32 * 1024
    assert len(json.dumps(payload, ensure_ascii=False).encode("utf-8")) < 1024 * 1024
    assert case.output == original_output


@parameterized.expand([("hosted_linked", True, True), ("hosted_unlinked", False, True), ("external", True, False)])
def test_prepare_preserves_rich_results_and_dataset_references(_name: str, link_traces: bool, hosted: bool) -> None:
    publisher = _publisher(link_traces=link_traces)
    publisher.suite = OfflineEvalSuite(
        key="sql/rich",
        scorer_kinds={"boolean_metric": "categorical", "numeric_metric": "numeric"},
        experiment_options={
            "dataset_revision_id": EXPERIMENT_ID if hosted else None,
            "prompt_version": "prompt-2",
            "run_source": "scheduled",
        },
    )
    case = _case()
    case.metadata.update(
        trace_id="application-trace", dataset_item_identifier="case-1", dataset_item_version_identifier="v2"
    )
    case.metadata["dataset_item_version_id"] = str(UUID(int=10))
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
    item = upload.items[0].to_dict()
    outcome = upload.results[0].to_dict()
    assert item.get("application_trace_id") == ("application-trace" if link_traces else None)
    if hosted:
        assert item["dataset_item_version_id"] == str(UUID(int=10))
        assert "dataset_item_identifier" not in item
        assert "dataset_item_version_identifier" not in item
    else:
        assert item["dataset_item_identifier"] == "case-1"
        assert item["dataset_item_version_identifier"] == "v2"
        assert "dataset_item_version_id" not in item
    assert outcome["value"] == ["correct"]
    assert outcome["payload"]["reasoning"] == "Matches expected answer"
    assert outcome["payload"]["metadata"] == {"confidence": 0.9}
    assert outcome.get("evaluator_trace_id") == ("judge-trace" if link_traces else None)
    assert outcome["evaluated_at"] == STARTED_AT.isoformat()
    assert upload.results[1].to_dict()["value"] == 35.0
    if hosted:
        assert upload.experiment["dataset_revision_id"] == EXPERIMENT_ID
        assert "dataset_source" not in upload.experiment
        assert "dataset_identifier" not in upload.experiment
        assert "dataset_revision_identifier" not in upload.experiment
    else:
        assert upload.experiment["dataset_source"] == "repository"
        assert upload.experiment["dataset_identifier"] == "sql/rich"
        assert upload.experiment["dataset_revision_identifier"] == "captured-revision"
    assert upload.experiment["prompt_version"] == "prompt-2"
    assert upload.experiment["run_source"] == "scheduled"

    case.scorer_results["numeric_metric"] = ScorerResult(status="not_applicable", reasoning="No applicable operation")
    assert _prepare(publisher, [case]).results[1].to_dict()["status"] == "not_applicable"


@parameterized.expand([("missing", None), ("malformed", "not-a-uuid"), ("wrong_type", 42)])
def test_prepare_rejects_missing_or_invalid_required_hosted_references(_name: str, version_id: object) -> None:
    publisher = _publisher()
    publisher.suite = replace(SUITE, experiment_options={"dataset_revision_id": EXPERIMENT_ID})
    healthy, malformed = _case("healthy"), _case("malformed")
    healthy.metadata["dataset_item_version_id"] = str(UUID(int=10))
    malformed.metadata["dataset_item_version_id"] = version_id

    with pytest.raises(
        OfflineUploadError, match="Hosted dataset case 'malformed' requires a valid dataset_item_version_id"
    ):
        _prepare(publisher, [healthy, malformed])


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
            ScorerResult(status="ok", value=0.75, reasoning="x" * (256 * 1024 - 40), metadata={"details": object()}),
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
    assert omitted_field in result["payload"]["metadata"]["omitted_fields"]


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
        if len(attempts) == 1:
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
    assert len(attempts) == (5 if failure_status == 503 else 2)
    assert all(request.url.path.endswith("/upload/") for request in attempts[1:])
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


def test_saved_upload_replays_partial_success_without_duplicate_results_or_integer_loss(tmp_path: Path) -> None:
    publisher = _publisher()
    cases = [_case(f"query-{index}") for index in range(501)]
    cases[0].output = {"large_integer": 2**80}
    upload = _prepare(publisher, cases)
    path = tmp_path / "upload.json"
    upload.save(path)
    assert "test-only-token" not in path.read_text()
    server = OfflineServer()
    attempts: list[httpx.Request] = []
    reject = True

    def respond(request: httpx.Request) -> httpx.Response:
        attempts.append(request)
        if reject and request.url.path.endswith("/upload/") and server.results:
            return httpx.Response(400)
        return server.respond(request)

    with patch("httpx.AsyncClient", new=partial(httpx.AsyncClient, transport=httpx.MockTransport(respond))):
        with pytest.raises(OfflineUploadError) as raised:
            asyncio.run(publisher.publish(upload))
        assert len(server.results) == 1000
        error = raised.value
        assert error.acknowledged_item_count == 500
        assert error.acknowledged_result_count == 1000
        assert error.completed_chunk_count == 1
        assert error.pending_result_count == 2
        assert error.failed_index == 1000
        assert "acknowledged 500 items and 1000 results" in str(error)
        assert "2 results await acknowledgment" in str(error)
        reject = False
        replay = OfflineEvalUpload.load(path)
        asyncio.run(publisher.publish(replay))
    assert len(server.results) == 1002
    assert len(server.items) == 501
    first_item = json.loads(attempts[1].content)["items"][0]
    assert first_item["payload"]["output"]["large_integer"] == 2**80
    assert replay.to_dict() == upload.to_dict()
    assert attempts[0].content == attempts[3].content
    assert attempts[1].content == attempts[4].content


def test_atomic_save_preserves_previous_upload_when_replace_fails(tmp_path: Path) -> None:
    path = tmp_path / "upload.json"
    upload = _prepare(_publisher(), [_case()])
    upload.save(path)
    previous = path.read_bytes()
    with patch.object(Path, "replace", side_effect=OSError("disk unavailable")), pytest.raises(OSError):
        replace(upload, experiment_name="new-name").save(path)
    assert path.read_bytes() == previous
    assert list(tmp_path.iterdir()) == [path]


@parameterized.expand([("original_destination", "123"), ("changed_destination", "456")])
def test_legacy_replay_uses_saved_versions_and_refuses_a_different_destination(_name: str, project_id: str) -> None:
    prepared = _prepare(_publisher(), [_case()]).to_dict()
    legacy = {
        "host": prepared["host"],
        "project_id": prepared["project_id"],
        "experiment": prepared["experiment"],
        "batches": [{"items": prepared["items"], "results": prepared["results"]}],
    }
    with TemporaryDirectory() as directory:
        path = Path(directory) / "legacy.json"
        path.write_text(json.dumps(legacy))
        upload = OfflineEvalUpload.load(path)
    server = OfflineServer()
    environment = {
        "POSTHOG_OFFLINE_EVAL_API_KEY": "test-only-token",
        "POSTHOG_OFFLINE_EVAL_PROJECT_ID": project_id,
        "POSTHOG_OFFLINE_EVAL_SCORER_VERSIONS": "ignored-during-replay",
    }
    with (
        patch.dict("os.environ", environment, clear=True),
        patch("httpx.AsyncClient", new=partial(httpx.AsyncClient, transport=httpx.MockTransport(server.respond))),
    ):
        settings = OfflineEvalSettings.from_env()
        assert settings is not None
        publisher = OfflineEvalPublisher(settings, OfflineEvalSuite(key="replay", scorer_kinds={}))
        if project_id == "123":
            asyncio.run(publisher.publish(upload))
            assert json.loads(server.requests[0].content) == legacy["experiment"]
            assert json.loads(server.requests[1].content) == {
                "items": prepared["items"],
                "results": prepared["results"],
            }
        else:
            with pytest.raises(OfflineUploadError, match="destination differs"):
                asyncio.run(publisher.publish(upload))
            assert server.requests == []


def test_settings_accept_a_shared_scorer_map_for_multiple_suites() -> None:
    environment = {
        "POSTHOG_OFFLINE_EVAL_API_KEY": "test-only-token",
        "POSTHOG_OFFLINE_EVAL_PROJECT_ID": "123",
        "POSTHOG_OFFLINE_EVAL_SCORER_VERSIONS": json.dumps(
            {metric: str(version) for metric, version in SCORER_VERSIONS.items()}
        ),
    }
    with patch.dict("os.environ", environment, clear=True):
        for metric, version in SCORER_VERSIONS.items():
            suite = OfflineEvalSuite(key=metric, scorer_kinds={metric: "numeric"})
            settings = OfflineEvalSettings.from_env(suite)
            assert settings is not None
            assert settings.scorer_versions[metric] == version


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


@parameterized.expand(
    [
        ("dataset_identifier_type", "dataset_item_identifier", 42, "dataset_item_identifier"),
        (
            "dataset_version_identifier",
            "dataset_item_version_identifier",
            "bad\x00version",
            "dataset_item_version_identifier",
        ),
        ("dataset_version_uuid", "dataset_item_version_id", "not-a-uuid", "dataset_item_version_id"),
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

    assert len(upload.items) == 2
    assert len(upload.results) == 4
    assert all(result.to_dict()["status"] == "ok" for result in upload.results)
    assert upload.items[0].to_dict()["case_key"] == "healthy"
    item = upload.items[1].to_dict()
    assert omitted_field not in item
    assert omitted_field in item["payload"]["metadata"]["omitted_fields"]
    if omitted_field != "dataset_item_identifier":
        assert item["dataset_item_identifier"] == "valid-case"
    with TemporaryDirectory() as directory:
        path = Path(directory) / "upload.json"
        upload.save(path)
        assert OfflineEvalUpload.load(path).to_dict() == upload.to_dict()
