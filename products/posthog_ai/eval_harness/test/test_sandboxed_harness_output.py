from __future__ import annotations

import sys
import json
import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Literal

import pytest
from unittest.mock import AsyncMock, MagicMock

import httpx

from products.posthog_ai.eval_harness import base, log_sink
from products.posthog_ai.eval_harness.acp_log import GenerationDescriptor, ParsedLog
from products.posthog_ai.eval_harness.config import AgentArtifacts, SandboxedEvalCase
from products.posthog_ai.eval_harness.engines.types import (
    AggregateScore,
    CaseResult,
    EvalSummary,
    ExperimentResult,
    NullCaseHooks,
)
from products.posthog_ai.eval_harness.harness.cli import SkillDelivery
from products.posthog_ai.eval_harness.harness.reporting import ProgressReporter, SuiteRunResult
from products.posthog_ai.eval_harness.harness.transcript import RunTranscript
from products.posthog_ai.eval_harness.offline_results import OfflineEvalSuite
from products.posthog_ai.eval_harness.scorers import ExitCodeZero
from products.posthog_ai.evals.sql import eval_sql as sql_eval
from products.tasks.backend.facade.agents import CustomPromptSandboxContext


def test_run_transcript_captures_both_streams_and_prints_its_path_last(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    transcript = RunTranscript.create(tmp_path)

    with transcript.capture():
        sys.stderr.write("stderr line\n")
        sys.stdout.write("stdout line")
    transcript.finish()

    captured = capsys.readouterr()
    transcript_lines = transcript.path.read_text(encoding="utf-8").splitlines()

    assert captured.out.splitlines() == [
        "stdout line",
        "Full run transcript (stdout and stderr):",
        str(transcript.path),
    ]
    assert captured.err.splitlines() == ["stderr line"]
    assert transcript_lines == [
        "stderr line",
        "stdout line",
        "Full run transcript (stdout and stderr):",
        str(transcript.path),
    ]
    assert (tmp_path / "latest.log").resolve() == transcript.path


@pytest.mark.asyncio
async def test_reporter_output_is_labeled_and_reserves_pass_for_the_run(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    reporter = ProgressReporter(total_suites=1)
    reporter.print_run_header(
        provider="docker",
        agent_runtime="codex",
        agent_model="gpt-5",
        max_sandboxes=4,
        trials=1,
        case_timeout_seconds=900,
    )
    await reporter.suite_started("cli_mcp/eval_workflow::eval_verify_event_before_query")
    await reporter.experiment_started("sandboxed-cli-mcp-verify-event-cli", 1, tmp_path)
    await reporter.case_done(
        "sandboxed-cli-mcp-verify-event-cli",
        "trends_pageview_verifies_first",
        duration_seconds=396.4,
    )
    await reporter.record_summary(
        "sandboxed-cli-mcp-verify-event-cli",
        EvalSummary(
            engine_name="Braintrust",
            experiment_name="sandboxed-cli-mcp-verify-event-cli",
            scores={
                "exit_code_zero": AggregateScore("exit_code_zero", 1.0),
                "called_target_tool": AggregateScore("called_target_tool", 0.0),
            },
            experiment_url="https://experiments.example/e",
        ),
    )
    await reporter.record_posthog_evaluations_url(
        "sandboxed-cli-mcp-verify-event-cli", "bd8b7f0d-7cc3-4ea3-a3a6-53be0d9e6eb4"
    )
    await reporter.suite_finished(
        SuiteRunResult(
            suite_id="cli_mcp/eval_workflow::eval_verify_event_before_query",
            status="passed",
            duration_seconds=404.6,
        )
    )
    reporter.print_final_summary(
        [
            SuiteRunResult(
                suite_id="cli_mcp/eval_workflow::eval_verify_event_before_query",
                status="passed",
                duration_seconds=404.6,
            )
        ],
        exit_code=0,
        fail_under=0.4,
        duration_seconds=404.6,
    )

    output = capsys.readouterr().out

    assert "CASE DONE" in output
    assert "EXPERIMENT DONE" in output
    assert "SUITE DONE" in output
    assert "Status: PASS" in output
    assert "Score gate: met (50.0% >= 40.0%)" in output
    assert "Suites: 1 done, 0 crashed" in output
    assert "Cases: 1 done, 0 timed out, 0 errors" in output
    assert "Experiment: sandboxed-cli-mcp-verify-event-cli" in output
    assert "exit_code_zero: 100.0%" in output
    assert "called_target_tool: 0.0%" in output
    assert "PostHog: https://us.posthog.com/" in output
    assert "Braintrust: https://experiments.example/e" in output
    assert f"Agent logs: {tmp_path}" in output
    assert output.count("PASS") == 1


def test_tool_call_spans_carry_the_resolved_tool_and_its_arguments() -> None:
    trends_query = {"kind": "TrendsQuery", "series": [{"kind": "EventsNode", "event": "$pageview"}]}
    parsed = ParsedLog(
        generations=[
            GenerationDescriptor(
                output_content=[
                    {
                        "type": "tool_use",
                        "id": "1",
                        "name": "mcp__posthog__exec",
                        "input": {"command": f"call query-trends {json.dumps(trends_query)}"},
                    }
                ],
            )
        ]
    )

    spans = _collect_spans(parsed)

    assert spans == [("tool_call: query-trends", [{"tool": "query-trends", "input": trends_query}])]


def test_exec_commands_wrapping_no_inner_tool_stay_under_the_raw_name() -> None:
    parsed = ParsedLog(
        generations=[
            GenerationDescriptor(
                output_content=[
                    {
                        "type": "tool_use",
                        "id": "1",
                        "name": "mcp__posthog__exec",
                        "input": {"command": "schema query-trends series"},
                    }
                ],
            )
        ]
    )

    spans = _collect_spans(parsed)

    assert spans == [("tool_call: exec", [{"tool": "exec", "input": {"command": "schema query-trends series"}}])]


def test_tool_call_spans_are_split_when_one_agent_message_has_multiple_calls() -> None:
    parsed = ParsedLog(
        generations=[
            GenerationDescriptor(
                output_content=[
                    {"type": "tool_use", "id": "1", "name": "query-retention", "input": {}},
                    {"type": "tool_use", "id": "2", "name": "execute-sql", "input": {}},
                ],
            )
        ]
    )

    spans = _collect_spans(parsed)

    assert spans == [
        ("tool_call: query-retention", [{"tool": "query-retention", "input": {}}]),
        ("tool_call: execute-sql", [{"tool": "execute-sql", "input": {}}]),
    ]


def _collect_spans(parsed: ParsedLog) -> list[tuple[str, Any]]:
    collected: list[tuple[str, Any]] = []

    class _Span:
        def __init__(self, name: str) -> None:
            self.name = name

        def log(self, *, input: Any = None, output: Any = None, metadata: Any = None) -> None:
            if input is not None:
                collected.append((self.name, input))

    class _Hooks(NullCaseHooks):
        @contextmanager
        def start_span(self, name: str, kind: Any) -> Iterator[_Span]:
            yield _Span(name)

    base._log_conversation_spans(_Hooks(), parsed)
    return collected


def test_sandboxed_eval_run_adds_exit_code_scorer(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(base, "build_case_dir", MagicMock(return_value=tmp_path))
    ctx = MagicMock(posthog_client=None, case_filter=None)
    custom_scorer = MagicMock()

    run = base._SandboxedEvalRun(
        experiment_name="experiment",
        cases=[],
        scorers=[custom_scorer],
        ctx=ctx,
        is_public=False,
        no_send_logs=True,
    )

    assert isinstance(run.active_scorers[0], ExitCodeZero)
    assert run.active_scorers[1] is custom_scorer

    with pytest.raises(ValueError, match="ExitCodeZero is added by the sandboxed eval harness"):
        base._SandboxedEvalRun(
            experiment_name="experiment",
            cases=[],
            scorers=[ExitCodeZero()],
            ctx=ctx,
            is_public=False,
            no_send_logs=True,
        )


@pytest.mark.parametrize(
    "enrolled,no_send_logs,configuration,http_status",
    [
        (True, False, "valid", 200),
        (True, False, "valid", 403),
        (True, False, "partial", 200),
        (True, False, "absent", 200),
        (True, True, "valid", 200),
        (False, False, "valid", 200),
    ],
)
@pytest.mark.asyncio
async def test_sandboxed_eval_publishes_existing_results_without_disrupting_reporting(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    enrolled: bool,
    no_send_logs: bool,
    configuration: Literal["valid", "partial", "absent"],
    http_status: int,
) -> None:
    for key in ("API_KEY", "PROJECT_ID", "SCORER_VERSIONS", "HOST"):
        monkeypatch.delenv(f"POSTHOG_OFFLINE_EVAL_{key}", raising=False)
    monkeypatch.delenv("EXPORT_EVAL_RESULTS", raising=False)
    monkeypatch.setattr(log_sink, "LOGS_ROOT", tmp_path)
    monkeypatch.setattr(log_sink, "INDEX_FILE", tmp_path / "runs.jsonl")
    version_id = "00000000-0000-4000-8000-000000000001"
    if configuration != "absent":
        monkeypatch.setenv("POSTHOG_OFFLINE_EVAL_API_KEY", "fake-offline-test-key")
    if configuration == "valid":
        monkeypatch.setenv("POSTHOG_OFFLINE_EVAL_HOST", "https://posthog.example.com")
        monkeypatch.setenv("POSTHOG_OFFLINE_EVAL_PROJECT_ID", "123")
        monkeypatch.setenv("POSTHOG_OFFLINE_EVAL_SCORER_VERSIONS", json.dumps({"exit_code_zero": version_id}))

    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(http_status, json={})

    client_type = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kwargs: client_type(transport=httpx.MockTransport(respond), **kwargs)
    )
    result = ExperimentResult(
        summary=EvalSummary(
            engine_name="braintrust",
            experiment_name="offline-pilot",
            scores={"exit_code_zero": AggregateScore("exit_code_zero", 1.0)},
            experiment_url="https://braintrust.example.com/experiment/test",
        ),
        results=[
            CaseResult(
                input={"name": "example-case", "prompt": "Run the task"},
                output={"last_message": "Done"},
                scores={"exit_code_zero": 1.0},
            )
        ],
    )
    engine = MagicMock(run_experiment=AsyncMock(return_value=result))
    event_client = MagicMock()
    reporter = ProgressReporter(total_suites=1)
    ctx = MagicMock(
        posthog_client=None,
        posthog_evaluation_client=event_client,
        case_filter=None,
        agent_model="test-model",
        agent_runtime="claude",
        skill_delivery="bundled",
        trials=1,
        engine=engine,
        reporter=reporter,
    )

    returned = await base.SandboxedEval(
        experiment_name="offline-pilot",
        cases=[SandboxedEvalCase(name="example-case", prompt="Run the task")],
        scorers=[],
        ctx=ctx,
        is_public=not no_send_logs,
        no_send_logs=no_send_logs,
        offline_suite=OfflineEvalSuite(key="example/suite", scorer_kinds={"exit_code_zero": "boolean"})
        if enrolled
        else None,
    )

    assert returned is result
    engine.run_experiment.assert_awaited_once()
    engine_spec = engine.run_experiment.call_args.args[0]
    assert engine_spec.no_send_logs is no_send_logs
    assert reporter.mean_score() == 1.0
    if no_send_logs:
        event_client.capture.assert_not_called()
    else:
        event_client.capture.assert_called_once()
        captured = event_client.capture.call_args.kwargs
        assert captured["event"] == "$ai_evaluation"
        assert captured["properties"]["$ai_metric_name"] == "exit_code_zero"
        assert captured["properties"]["$ai_score"] == 1.0

    reporter.print_final_summary([], exit_code=0, fail_under=None, duration_seconds=0)
    output = capsys.readouterr().out
    assert "Braintrust: https://braintrust.example.com/experiment/test" in output
    assert "exit_code_zero: 100.0%" in output
    saved_path = tmp_path / "offline-pilot" / "latest" / "posthog-offline-upload.json"
    if enrolled and not no_send_logs and configuration == "valid":
        saved = json.loads(saved_path.read_text())
        assert json.loads(requests[0].content) == saved["experiment"]
        assert saved["batches"][0]["results"][0]["scorer_version_id"] == version_id
        assert saved["batches"][0]["results"][0]["value"] is True
        if http_status == 200:
            assert len(requests) == 3
            assert json.loads(requests[1].content) == saved["batches"][0]
            assert requests[2].url.path.endswith("/complete/")
            assert "PostHog: https://posthog.example.com/project/123/" in output
        else:
            assert len(requests) == 1
            assert "upload failed: PostHog upload returned HTTP 403" in output
            assert "Saved requests:" in output
    else:
        assert requests == []
        assert not saved_path.exists()
        if enrolled and not no_send_logs:
            assert "PostHog offline: disabled:" in output
            assert "POSTHOG_OFFLINE_EVAL_" in output
        else:
            assert "POSTHOG OFFLINE" not in output


@pytest.mark.asyncio
async def test_sql_suite_enrolls_every_scorer_in_offline_publishing(monkeypatch: pytest.MonkeyPatch) -> None:
    run = AsyncMock()
    monkeypatch.setattr(sql_eval, "SandboxedPublicEval", run)

    await sql_eval.eval_sql(MagicMock())

    run.assert_awaited_once()
    suite = run.call_args.kwargs["offline_suite"]
    assert suite.key == "sql/eval_sql::eval_sql"
    assert suite.scorer_kinds == {
        "exit_code_zero": "boolean",
        "no_persistent_insight_save": "boolean",
        "execute_sql_called": "boolean",
        "answer_tool_not_typed_query": "boolean",
        "querying_posthog_data_skill_loaded": "boolean",
        "sql_schema_alignment": "numeric",
        "sql_result_message_alignment": "numeric",
    }
    configured_names = {scorer._name() for scorer in run.call_args.kwargs["scorers"]}
    assert set(suite.scorer_kinds) == {"exit_code_zero", *configured_names}


@pytest.mark.parametrize(
    "delivery,origin,has_original,expected_origin",
    [
        ("exec", None, True, "eval"),
        ("exec", None, False, "eval"),
        ("bundled", None, True, None),
        ("bundled", None, False, None),
        ("exec", "eval", True, "eval"),
        ("exec", "slack", True, "slack"),
        ("exec", "posthog_ai", True, "posthog_ai"),
        ("exec", "posthog-code", True, "posthog-code"),
        ("bundled", "slack", True, "slack"),
    ],
)
@pytest.mark.asyncio
async def test_sandboxed_eval_skill_delivery_sets_the_agent_origin(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    delivery: SkillDelivery,
    origin: str | None,
    has_original: bool,
    expected_origin: str | None,
) -> None:
    monkeypatch.setattr(base, "build_case_dir", MagicMock(return_value=tmp_path))
    sandbox_context = CustomPromptSandboxContext(team_id=1, user_id=2)
    ctx = MagicMock(
        posthog_client=None,
        case_filter=None,
        skill_delivery=delivery,
        sandbox_slots=asyncio.Semaphore(1),
        team_setup_slots=asyncio.Semaphore(1),
        per_case_timeout_seconds=30,
    )
    ctx.demo_data.make_context.return_value = sandbox_context
    ctx.provider_strategy.keeps_sandboxes.return_value = False
    setup = MagicMock(return_value={"seeded": True})
    case = SandboxedEvalCase(name="ordinary-case", prompt="Run the task", interaction_origin=origin, setup=setup)
    run = base._SandboxedEvalRun(
        experiment_name="skill-delivery-test",
        cases=[case] if has_original else [],
        scorers=[],
        ctx=ctx,
        is_public=False,
        no_send_logs=True,
    )
    launch = AsyncMock(return_value=base.EvalCaseResult(artifacts=AgentArtifacts(exit_code=0)))
    monkeypatch.setattr(base, "run_eval_case", launch)
    monkeypatch.setattr(base, "reclaim_kernels", AsyncMock())

    _, seed = await run._run_sandbox_window(case, case if has_original else None)

    launched_context = launch.call_args.args[1]
    assert launched_context.interaction_origin == expected_origin
    assert ctx.demo_data.make_context.call_args.kwargs["disable_bundled_skills"] == (delivery == "exec")
    if has_original:
        assert setup.call_args.args[0].interaction_origin == expected_origin
        assert seed == {"seeded": True}
    else:
        assert seed == {}
