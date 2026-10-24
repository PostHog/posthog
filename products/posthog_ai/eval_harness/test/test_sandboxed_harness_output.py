from __future__ import annotations

import io
import os
import sys
import json
import asyncio
import logging
import warnings
import importlib
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from functools import partial
from pathlib import Path
from threading import Event, Thread, get_ident
from typing import Any, Literal
from uuid import UUID

import pytest
from unittest.mock import AsyncMock, MagicMock

from django.db import OperationalError

import httpx
from botocore.exceptions import ClientError
from clickhouse_driver.errors import ErrorCodes, NetworkError, ServerException
from psycopg import OperationalError as PsycopgOperationalError
from psycopg.errors import AdminShutdown, InvalidPassword

from posthog.exceptions import ClickHouseAtCapacity, ClickHouseQueryMemoryLimitExceeded, ClickHouseQueryTimeOut

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
from products.posthog_ai.eval_harness.harness import reporting
from products.posthog_ai.eval_harness.harness.cli import SkillDelivery
from products.posthog_ai.eval_harness.harness.discovery import EvalSuite, discover_suites
from products.posthog_ai.eval_harness.harness.offline_delivery import OfflineEvalDelivery
from products.posthog_ai.eval_harness.harness.reporting import ProgressReporter, SuiteRunResult
from products.posthog_ai.eval_harness.harness.requirements import SuiteKind
from products.posthog_ai.eval_harness.harness.transcript import RunTranscript
from products.posthog_ai.eval_harness.harness.trial_stats import ScorerTrialStats
from products.posthog_ai.eval_harness.offline_results import OfflineEvalSuite
from products.posthog_ai.eval_harness.one_shot import OneShotEval
from products.posthog_ai.eval_harness.scorers import ExitCodeZero
from products.posthog_ai.eval_harness.test.offline_api import OfflineServer
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


@pytest.mark.parametrize("verbose", [False, True])
@pytest.mark.parametrize("blocked_operation", ["write", "flush"])
def test_logging_continues_while_progress_output_is_blocked(
    tmp_path: Path, verbose: bool, blocked_operation: str
) -> None:
    blocked = Event()
    release = Event()
    logged = Event()
    stdout = MagicMock(wraps=io.StringIO())

    def wait_for_release(*_args: object) -> None:
        blocked.set()
        release.wait()

    getattr(stdout, blocked_operation).side_effect = wait_for_release
    transcript = RunTranscript(tmp_path / "run.log", stdout, io.StringIO())
    handler = transcript.logging_handler(verbose=verbose)

    def log() -> None:
        handler.handle(logging.LogRecord("eval", logging.INFO, "", 0, "poll continues", (), None))
        logged.set()

    progress = Thread(target=transcript._stdout.write_console, args=("CASE PHASE agent\n",))
    logging_worker = Thread(target=log)
    progress.start()
    try:
        assert blocked.wait(timeout=5)
        logging_worker.start()
        assert logged.wait(timeout=5)
        assert "poll continues" in transcript.path.read_text()
    finally:
        release.set()
        progress.join(timeout=5)
        if logging_worker.ident is not None:
            logging_worker.join(timeout=5)
        handler.close()
        transcript.finish()


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
    await reporter.record_posthog_offline_result(
        "sandboxed-cli-mcp-verify-event-cli",
        "uploaded",
        url="https://us.posthog.com/project/2/ai-evals/evaluations/offline/experiments/bd8b7f0d-7cc3-4ea3-a3a6-53be0d9e6eb4",
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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "stats, expected",
    [
        pytest.param(
            ScorerTrialStats(
                name="s",
                cases=10,
                trials=3,
                mean=0.7,
                ci_low=0.61,
                ci_high=0.83,
                complete_cases=9,
                short_cases=1,
                pass_all=0.4,
                pass_any=0.85,
                flaky_cases=4,
            ),
            "    s: 72.0% (95% CI 61.0-83.0%)\n"
            "      pass^3 40.0% | pass@3 85.0% | 4/9 cases flaky | 1 cases short of 3 trials\n",
            id="multiple_trials",
        ),
        pytest.param(
            ScorerTrialStats(
                name="s",
                cases=10,
                trials=1,
                mean=0.7,
                ci_low=0.61,
                ci_high=0.83,
                complete_cases=10,
                short_cases=0,
                pass_all=None,
                pass_any=None,
                flaky_cases=0,
            ),
            "    s: 72.0% (95% CI 61.0-83.0%)\n  Braintrust",
            id="single_trial",
        ),
        pytest.param(
            ScorerTrialStats(
                name="s",
                cases=10,
                trials=3,
                mean=0.7,
                ci_low=0.61,
                ci_high=0.83,
                complete_cases=0,
                short_cases=10,
                pass_all=None,
                pass_any=None,
                flaky_cases=0,
            ),
            "      pass^3 n/a | pass@3 n/a | 0/0 cases flaky | 10 cases short of 3 trials\n",
            id="no_case_completed_every_trial",
        ),
    ],
)
async def test_reporter_shows_the_engine_score_with_trial_stats(
    stats: ScorerTrialStats, expected: str, capsys: pytest.CaptureFixture[str]
) -> None:
    reporter = ProgressReporter(total_suites=1)
    await reporter.record_summary(
        "exp",
        EvalSummary(engine_name="Braintrust", experiment_name="exp", scores={"s": AggregateScore("s", 0.72)}),
        trial_stats=[stats],
    )
    reporter.print_final_summary([], exit_code=0, fail_under=None, duration_seconds=1.0)

    assert expected in capsys.readouterr().out


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
    "suite_kind,enrolled,no_send_logs,send_to_posthog,posthog_enabled,configuration,http_status,delivery_state",
    [
        ("sandboxed", True, False, None, True, "valid", 200, "ready"),
        ("sandboxed", True, False, None, True, "valid", 403, "ready"),
        ("sandboxed", True, False, None, True, "invalid", 200, "ready"),
        ("sandboxed", True, False, None, True, "absent", 200, "ready"),
        ("sandboxed", True, True, None, False, "valid", 200, "ready"),
        ("sandboxed", False, False, None, True, "valid", 200, "ready"),
        ("one-shot", True, False, None, True, "valid", 200, "ready"),
        ("sandboxed", True, False, None, True, "valid", 200, "unavailable"),
        ("sandboxed", True, False, None, True, "valid", 200, "closed"),
        ("sandboxed", True, True, True, True, "valid", 200, "ready"),
        ("one-shot", True, True, True, True, "valid", 200, "ready"),
        ("sandboxed", True, False, False, False, "valid", 200, "ready"),
        ("sandboxed", True, True, True, True, "absent", 200, "ready"),
        ("sandboxed", False, True, True, True, "valid", 200, "ready"),
    ],
)
@pytest.mark.asyncio
async def test_sandboxed_eval_publishes_existing_results_without_disrupting_reporting(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    suite_kind: Literal["sandboxed", "one-shot"],
    enrolled: bool,
    no_send_logs: bool,
    send_to_posthog: bool | None,
    posthog_enabled: bool,
    configuration: Literal["valid", "invalid", "absent"],
    http_status: int,
    delivery_state: Literal["ready", "unavailable", "closed"],
) -> None:
    for key in ("API_KEY", "HOST", "LOCAL_CONFIG"):
        monkeypatch.delenv(f"POSTHOG_OFFLINE_EVAL_{key}", raising=False)
    monkeypatch.setenv("EXPORT_EVAL_RESULTS", "1")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(log_sink, "LOGS_ROOT", tmp_path)
    monkeypatch.setattr(log_sink, "INDEX_FILE", tmp_path / "runs.jsonl")
    version_id = "00000000-0000-4000-8000-000000000001"
    if configuration != "absent":
        monkeypatch.setenv("POSTHOG_OFFLINE_EVAL_API_KEY", "fake-offline-test-key" if configuration == "valid" else " ")
    if configuration == "valid":
        monkeypatch.setenv("POSTHOG_OFFLINE_EVAL_HOST", "https://posthog.example.com")

    requests: list[httpx.Request] = []
    server = OfflineServer()
    release_upload = asyncio.Event()

    async def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        await release_upload.wait()
        return server.respond(request) if http_status == 200 else httpx.Response(http_status, json={})

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
                output={"last_message": "Done", "large_integer": 2**64},
                scores={"exit_code_zero": 1.0},
            )
        ],
    )
    engine = MagicMock(run_experiment=AsyncMock(return_value=result))
    reporter = ProgressReporter(total_suites=1)
    delivery = OfflineEvalDelivery(reporter)
    if delivery_state == "closed":
        await delivery.drain()
    ctx = MagicMock(
        posthog_client=None,
        case_filter=None,
        agent_model="test-model",
        agent_runtime="claude",
        skill_delivery="bundled",
        reasoning_effort=None,
        trials=1,
        git_sha="test-sha",
        git_dirty=False,
        engine=engine,
        reporter=reporter,
        offline_delivery=delivery if delivery_state != "unavailable" else None,
    )

    run_eval = base.SandboxedEval if suite_kind == "sandboxed" else partial(OneShotEval, task=AsyncMock())
    returned = await asyncio.wait_for(
        run_eval(
            experiment_name="offline-pilot",
            cases=[SandboxedEvalCase(name="example-case", prompt="Run the task")],
            scorers=[],
            ctx=ctx,
            is_public=not no_send_logs,
            no_send_logs=no_send_logs,
            send_to_posthog=send_to_posthog,
            offline_suite=OfflineEvalSuite(
                key="example/suite",
                project_id=123,
                scorer_kinds={"exit_code_zero": "boolean"},
                scorer_versions={"exit_code_zero": UUID(version_id)},
            )
            if enrolled
            else None,
        ),
        timeout=5,
    )

    assert returned is result
    export_path = tmp_path / "offline-pilot" / "latest" / "case_results.jsonl"
    assert json.loads(export_path.read_text())["scores"] == {"exit_code_zero": 1.0}
    assert not release_upload.is_set()
    release_upload.set()
    await delivery.drain()
    engine.run_experiment.assert_awaited_once()
    engine_spec = engine.run_experiment.call_args.args[0]
    assert engine_spec.no_send_logs is no_send_logs
    assert engine_spec.record_scorer_results is (enrolled and posthog_enabled and configuration == "valid")
    assert reporter.mean_score() == 1.0
    reporter.print_final_summary([], exit_code=0, fail_under=None, duration_seconds=0)
    output = capsys.readouterr().out
    assert "Braintrust: https://braintrust.example.com/experiment/test" in output
    assert "exit_code_zero: 100.0%" in output
    assert not (tmp_path / "offline-pilot" / "latest" / "posthog-offline-upload.json").exists()
    if enrolled and posthog_enabled and configuration == "valid" and delivery_state == "ready":
        declaration = json.loads(requests[0].content)
        assert declaration["name"] == "offline-pilot"
        assert declaration["expected_item_count"] == 1
        assert declaration["expected_result_count"] == 1
        if http_status == 200:
            assert len(requests) == 3
            batch = json.loads(requests[1].content)
            assert batch["results"][0]["scorer_version_id"] == version_id
            assert batch["results"][0]["value"] is True
            assert batch["results"][0]["item_id"] == batch["items"][0]["id"]
            assert batch["items"][0]["payload"]["output"]["large_integer"] == 2**64
            assert requests[2].url.path.endswith("/complete/")
            assert "PostHog: https://posthog.example.com/project/123/" in output
        else:
            assert len(requests) == 1
            assert "PostHog:" not in output
            assert "upload failed:" in output
            assert "403" in output
            assert "Results were not saved for retry." in output
    else:
        assert requests == []
        assert "PostHog:" not in output
        if delivery_state != "ready":
            reason = (
                "background delivery is unavailable" if delivery_state == "unavailable" else "queue is full or closed"
            )
            assert reason in output
            assert "Results were not saved for retry." in output
        elif enrolled and posthog_enabled:
            assert "PostHog offline: disabled:" in output
            assert "POSTHOG_OFFLINE_EVAL_" in output
        else:
            assert "POSTHOG OFFLINE" not in output


@pytest.mark.parametrize(
    "discovered",
    [
        suite
        for suite in discover_suites()
        if suite.fn.__module__.startswith(("products.posthog_ai.evals.", "products.slack_app.evals."))
        and hasattr(importlib.import_module(suite.fn.__module__), "offline_suite")
    ],
    ids=lambda suite: suite.id,
)
@pytest.mark.asyncio
async def test_suite_enrolls_every_scorer_in_offline_publishing(
    monkeypatch: pytest.MonkeyPatch, discovered: EvalSuite
) -> None:
    domain, module_name, suite_kind = discovered.domain, discovered.module_name, discovered.kind
    module = importlib.import_module(discovered.fn.__module__)
    if domain == "taxonomic_filter":
        monkeypatch.setattr(module, "system_one_configured", lambda: True)
        if module_name == "eval_event_match":
            monkeypatch.setattr(module, "EVENT_MATCH_MODEL", MagicMock())
        else:
            monkeypatch.setattr(module, "fetch_search_intent_prompt", MagicMock())
    run = AsyncMock()
    runner_kind = "OneShot" if suite_kind == SuiteKind.ONE_SHOT else "Sandboxed"
    runner_visibility = "Private" if discovered.no_send_logs else "Public"
    monkeypatch.setattr(module, f"{runner_kind}{runner_visibility}Eval", run)

    await discovered.fn(MagicMock(skill_delivery="bundled"))

    run.assert_awaited_once()
    suite = run.call_args.kwargs["offline_suite"]
    assert suite.key == discovered.id
    component = (
        f"slack-app/{module_name.removeprefix('eval_').replace('_', '-')}"
        if domain == "slack_app"
        else f"posthog-ai/{domain.replace('_', '-')}"
    )
    assert suite.tags == ("team:surfaces", f"component:{component}")
    if domain == "experiments":
        assert run.call_args.kwargs["send_to_posthog"] is True
        assert set(suite.scorer_kinds.values()) == {"boolean"}
    elif domain == "sql":
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
    if suite_kind == SuiteKind.SANDBOXED:
        configured_names.add("exit_code_zero")
    assert set(suite.scorer_kinds) == set(suite.scorer_versions) == configured_names


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
    assert launched_context.system_prompt == (
        dict(base.PromptService.build()) if expected_origin == "posthog_ai" else None
    )
    assert ctx.demo_data.make_context.call_args.kwargs["disable_bundled_skills"] == (delivery == "exec")
    if has_original:
        assert setup.call_args.args[0].interaction_origin == expected_origin
        assert seed == {"seeded": True}
    else:
        assert seed == {}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "stage,error,failures,retries,recovers",
    [
        pytest.param("clone", NetworkError("Temporary connection failure"), 1, 2, True, id="clone_recovers"),
        pytest.param("seed", NetworkError("Temporary connection failure"), 2, 2, True, id="seed_recovers"),
        pytest.param("seed", AdminShutdown("Database restart"), 1, 2, True, id="postgres_restart"),
        pytest.param("clone", AdminShutdown("Database restart"), 1, 2, True, id="postgres_clone_restart"),
        pytest.param(
            "clone", PsycopgOperationalError("connection failed: Connection refused"), 1, 2, True, id="postgres_refused"
        ),
        pytest.param(
            "seed",
            PsycopgOperationalError("server closed the connection unexpectedly"),
            1,
            2,
            True,
            id="postgres_socket_closed",
        ),
        pytest.param("seed", PsycopgOperationalError("timeout expired"), 1, 2, True, id="postgres_timeout"),
        pytest.param(
            "seed",
            PsycopgOperationalError('FATAL: password authentication failed for user "example"'),
            1,
            2,
            False,
            id="postgres_authentication_without_sqlstate",
        ),
        pytest.param(
            "seed",
            PsycopgOperationalError('invalid sslmode value: "example"'),
            1,
            2,
            False,
            id="postgres_configuration_without_sqlstate",
        ),
        pytest.param(
            "seed",
            PsycopgOperationalError('Connection refused\nFATAL: database "example" does not exist'),
            1,
            2,
            False,
            id="postgres_mixed_permanent_failure",
        ),
        pytest.param("seed", InvalidPassword("Invalid test credentials"), 1, 2, False, id="postgres_authentication"),
        pytest.param(
            "seed", ServerException("Busy", code=ErrorCodes.MEMORY_LIMIT_EXCEEDED), 1, 2, True, id="clickhouse_busy"
        ),
        pytest.param("clone", ClickHouseAtCapacity(), 1, 2, True, id="clickhouse_wrapped_capacity"),
        pytest.param("seed", ClickHouseQueryTimeOut(), 1, 2, True, id="clickhouse_wrapped_timeout"),
        pytest.param("seed", ClickHouseQueryMemoryLimitExceeded(), 1, 2, True, id="clickhouse_wrapped_memory"),
        pytest.param(
            "seed",
            ClientError(
                {
                    "ResponseMetadata": {
                        "HTTPStatusCode": 503,
                        "RequestId": "test-request",
                        "HostId": "test-host",
                        "HTTPHeaders": {},
                        "RetryAttempts": 0,
                    }
                },
                "GetObject",
            ),
            1,
            2,
            True,
            id="storage_outage",
        ),
        pytest.param(
            "seed",
            ClientError(
                {
                    "ResponseMetadata": {
                        "HTTPStatusCode": 403,
                        "RequestId": "test-request",
                        "HostId": "test-host",
                        "HTTPHeaders": {},
                        "RetryAttempts": 0,
                    }
                },
                "GetObject",
            ),
            1,
            2,
            False,
            id="storage_authentication",
        ),
        pytest.param("seed", NetworkError("Temporary connection failure"), 3, 2, False, id="retry_limit"),
        pytest.param("seed", NetworkError("Temporary connection failure"), 1, 0, False, id="retries_disabled"),
        pytest.param("seed", ValueError("Invalid setup"), 1, 2, False, id="setup_bug"),
        pytest.param(
            "seed",
            PsycopgOperationalError("Unclassified connection failure"),
            1,
            2,
            False,
            id="unknown_postgres_failure",
        ),
        pytest.param("agent", NetworkError("Agent connection failure"), 1, 2, False, id="agent_does_not_retry"),
    ],
)
async def test_case_setup_retries_use_fresh_data_and_report_one_outcome(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    stage: Literal["clone", "seed", "agent"],
    error: Exception,
    failures: int,
    retries: int,
    recovers: bool,
) -> None:
    monkeypatch.setattr(base, "build_case_dir", MagicMock(return_value=tmp_path))
    reporter = ProgressReporter(total_suites=1)
    ctx = MagicMock(
        posthog_client=None,
        case_filter=None,
        skill_delivery="bundled",
        sandbox_slots=asyncio.Semaphore(1),
        team_setup_slots=asyncio.Semaphore(1),
        per_case_timeout_seconds=30,
        infrastructure_retries=retries,
        reporter=reporter,
    )
    ctx.provider_strategy.keeps_sandboxes.return_value = False
    contexts = [CustomPromptSandboxContext(team_id=team, user_id=1) for team in range(1, retries + 2)]
    failure = error
    if isinstance(error, PsycopgOperationalError) and stage == "seed":
        failure = OperationalError("Synthetic database failure")
        failure.__cause__ = error
    broken_workers: set[int] = set()

    def setup_step[Result](results: Iterator[Result | Exception], *_args: object, **_kwargs: object) -> Result:
        if get_ident() in broken_workers:
            raise PsycopgOperationalError("the connection is closed")
        result = next(results)
        if isinstance(result, Exception):
            if isinstance(error, PsycopgOperationalError):
                broken_workers.add(get_ident())
            raise result
        return result

    def close_worker_connections() -> None:
        broken_workers.discard(get_ident())

    monkeypatch.setattr(base, "close_old_connections", close_worker_connections)
    clone_results: list[CustomPromptSandboxContext | Exception] = [
        *([failure] * failures if stage == "clone" else []),
        *contexts,
    ]
    ctx.demo_data.make_context.side_effect = partial(setup_step, iter(clone_results))
    seed = MagicMock(side_effect=partial(setup_step, iter(([failure] * failures if stage == "seed" else []) + [{}])))
    case = SandboxedEvalCase(name="case", prompt="Run the task", setup=seed)
    run = base._SandboxedEvalRun(
        experiment_name="setup-retries",
        cases=[case],
        scorers=[],
        ctx=ctx,
        is_public=False,
        no_send_logs=True,
    )
    launch = AsyncMock(
        side_effect=failure if stage == "agent" else None,
        return_value=base.EvalCaseResult(artifacts=AgentArtifacts(exit_code=0)),
    )
    monkeypatch.setattr(base, "run_eval_case", launch)
    cleanup = AsyncMock()
    monkeypatch.setattr(base, "reclaim_kernels", cleanup)
    monkeypatch.setattr(run, "_post_process", AsyncMock(return_value={"score": 0.0}))

    async def backoff(_delay: float) -> None:
        assert ctx.team_setup_slots._value == 1
        assert launch.call_count == 0
        if stage == "seed":
            assert cleanup.await_count == seed.call_count

    monkeypatch.setattr(base.asyncio, "sleep", backoff)
    hooks = NullCaseHooks()
    if recovers:
        assert await run._task({"name": "case", "prompt": case.prompt}, hooks) == {"score": 0.0}
        assert launch.call_count == 1
        assert hooks.metadata["setup_attempts"] == failures + 1
        assert hooks.metadata["setup_retry_errors"] == [type(failure).__name__] * failures
    else:
        with pytest.raises(type(failure)):
            await run._task({"name": "case", "prompt": case.prompt}, hooks)
        assert launch.call_count == (1 if stage == "agent" else 0)
    if stage == "seed":
        seeded_teams = [call.args[0].team_id for call in seed.call_args_list]
        assert len(seeded_teams) == len(set(seeded_teams))
    output = capsys.readouterr().out
    retry_count = failures if recovers else (retries if stage == "seed" and isinstance(error, NetworkError) else 0)
    assert output.count("CASE RETRY") == retry_count
    assert output.count("CASE READY" if recovers else "CASE ERROR") == 1
    assert reporter.has_case_errors() is (not recovers)
    assert ctx.sandbox_slots._value == ctx.team_setup_slots._value == 1
    assert not broken_workers


@pytest.mark.asyncio
@pytest.mark.parametrize("agent_error", [None, RuntimeError("agent failed"), asyncio.CancelledError()])
@pytest.mark.parametrize("reporting_phase", ["agent", "cleanup"])
async def test_kernel_cleanup_preserves_case_outcome_when_progress_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, agent_error: BaseException | None, reporting_phase: str
) -> None:
    monkeypatch.setattr(base, "build_case_dir", MagicMock(return_value=tmp_path))
    ctx = MagicMock(posthog_client=None, case_filter=None, sandbox_slots=asyncio.Semaphore(1))
    ctx.per_case_timeout_seconds = 30
    ctx.provider_strategy.keeps_sandboxes.return_value = False
    case = SandboxedEvalCase(name="case", prompt="Run the task")
    run = base._SandboxedEvalRun("cleanup", [case], [], ctx, is_public=False, no_send_logs=True)
    context = CustomPromptSandboxContext(team_id=1, user_id=2)
    monkeypatch.setattr(
        run, "_prepare_case", AsyncMock(return_value=base._SandboxedCaseSetup(context=context, seed={}))
    )

    async def report_phase(_trial_id: str, phase: str) -> None:
        if phase == reporting_phase:
            raise BrokenPipeError("closed output")

    ctx.reporter.case_phase = AsyncMock(side_effect=report_phase)
    hooks = NullCaseHooks()
    hooks.metadata["trial_id"] = "trial"
    result = base.EvalCaseResult(artifacts=AgentArtifacts(exit_code=0))
    monkeypatch.setattr(base, "run_eval_case", AsyncMock(return_value=result, side_effect=agent_error))
    cleanup = AsyncMock()
    monkeypatch.setattr(base, "reclaim_kernels", cleanup)

    if agent_error is None:
        actual, _ = await run._run_sandbox_window(case, case, hooks)
        assert actual is result
    else:
        with pytest.raises(type(agent_error)) as raised:
            await run._run_sandbox_window(case, case, hooks)
        assert raised.value is agent_error

    cleanup.assert_awaited_once_with(1, keep=False)
    assert ctx.sandbox_slots._value == 1


@pytest.mark.asyncio
async def test_sandboxed_trials_keep_separate_logs_and_trace_roots(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("EXPORT_EVAL_RESULTS", raising=False)
    monkeypatch.setattr(base, "build_case_dir", lambda *_: tmp_path)
    ctx = MagicMock(posthog_client=None, reporter=ProgressReporter(total_suites=1))
    ctx.trials = 3
    run = base._SandboxedEvalRun("trials", [], [], ctx, is_public=False, no_send_logs=True)
    run.posthog_client = MagicMock()
    results = []
    for index in range(3):
        trial_id = f"trial-{index}"
        hooks = NullCaseHooks()
        hooks.metadata["trial_id"] = trial_id
        raw_log = json.dumps(
            {
                "notification": {
                    "method": "session/update",
                    "params": {
                        "update": {
                            "sessionUpdate": "agent_message_chunk",
                            "content": {"type": "text", "text": str(index)},
                        }
                    },
                }
            }
        )
        output = await run._post_process(
            SandboxedEvalCase(name="same-case", prompt="Run the task"),
            hooks,
            base.EvalCaseResult(artifacts=AgentArtifacts(exit_code=0), raw_log=raw_log, trace_id=f"trace-{index}"),
            {},
        )
        results.append(
            CaseResult(input={"name": "same-case"}, output=output, scores={"score": index / 2}, metadata=hooks.metadata)
        )
    await run._finalize(
        ExperimentResult(
            summary=EvalSummary(engine_name="stub", experiment_name="trials", scores={}),
            results=list(reversed(results)),
        )
    )
    for index in range(3):
        summary = (tmp_path / f"same-case.trial-trial-{index}.summary.txt").read_text()
        assert f"trace_id: trace-{index}" in summary
        assert json.loads(summary.split("=== scores ===\n")[1]) == {"score": index / 2}
    roots = [
        call.kwargs["properties"]
        for call in run.posthog_client.capture.call_args_list
        if call.kwargs.get("event") == "$ai_trace"
    ]
    assert [root["$ai_trace_id"] for root in roots] == ["trace-2", "trace-1", "trace-0"]


@pytest.mark.parametrize("verbose", [False, True])
@pytest.mark.parametrize("structured", [False, True])
def test_console_detail_does_not_remove_transcript_logs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], verbose: bool, structured: bool
) -> None:
    transcript = RunTranscript.create(tmp_path)
    handler = transcript.logging_handler(verbose=verbose)
    handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    info = logging.LogRecord(
        "products.posthog_ai.eval_harness.example",
        logging.INFO,
        "",
        0,
        {"event": "agent detail"} if structured else "agent detail",
        (),
        None,
    )
    try:
        raise ValueError("service unavailable\nconnection details")
    except ValueError:
        error = logging.LogRecord(
            "products.posthog_ai.eval_harness.example",
            logging.ERROR,
            "",
            0,
            {"event": "case error"} if structured else "case error",
            (),
            sys.exc_info(),
        )
    dependency_warning = logging.LogRecord("dependency", logging.WARNING, "", 0, "optional dependency detail", (), None)
    dependency_error = logging.LogRecord("dependency", logging.ERROR, "", 0, "optional service detail", (), None)
    runner_warning = logging.LogRecord(
        "products.posthog_ai.eval_harness.example", logging.WARNING, "", 0, "Setup will retry", (), None
    )
    with transcript.capture(verbose=verbose), warnings.catch_warnings():
        warnings.simplefilter("always")
        warnings.warn("optional Python dependency detail", UserWarning, stacklevel=1)
        sys.stdout.write("SDK progress detail\n")
        reporting._emit("CASE PHASE example :: case [trial 1] agent")
        handler.handle(dependency_warning)
        handler.handle(dependency_error)
        handler.handle(runner_warning)
        handler.handle(info)
        handler.handle(error)
    handler.close()
    transcript.finish()
    output = capsys.readouterr()
    saved = transcript.path.read_text()
    assert "CASE PHASE example :: case [trial 1] agent" in output.out
    assert "Setup will retry" in output.err
    assert "optional service detail" in saved
    assert ("optional service detail" in output.err) is verbose
    assert "optional dependency detail" in saved
    assert "optional Python dependency detail" in saved
    assert "SDK progress detail" in saved
    assert ("SDK progress detail" in output.out) is verbose
    assert ("optional Python dependency detail" in output.err) is verbose
    assert ("optional dependency detail" in output.err) is verbose
    assert "agent detail" in saved
    assert "ValueError: service unavailable" in saved
    assert "ValueError: service unavailable" in output.err
    assert ("connection details" in output.err) is verbose
    assert "case error" in output.err
    assert ("agent detail" in output.err) is verbose
    assert ("Traceback" in output.err) is verbose
    assert output.out.splitlines()[-1] == saved.splitlines()[-1] == str(transcript.path)


@pytest.mark.parametrize("verbose", [False, True])
@pytest.mark.parametrize("interactive", [False, True])
def test_native_child_output_stays_in_transcript_and_file_descriptors_restore(
    tmp_path: Path, capfd: pytest.CaptureFixture[str], verbose: bool, interactive: bool
) -> None:
    transcript = RunTranscript.create(tmp_path)
    console: list[str] = []
    with transcript.capture(verbose=verbose, console_output=console.append if interactive else None):
        subprocess.run(
            [sys.executable, "-c", "import os; os.write(1, b'native stdout\\n'); os.write(2, b'native stderr')"],
            check=True,
        )
        reporting._emit("SETUP START example service")
    os.write(1, b"descriptors restored\n")
    transcript.finish()
    output = capfd.readouterr()
    saved = transcript.path.read_text()
    assert "native stdout" not in output.out
    assert "native stderr" not in output.err
    assert ("SETUP START example service" in output.out) is (not interactive)
    assert ("SETUP START example service\n" in console) is interactive
    assert "descriptors restored" in output.out
    assert "native stdout\nnative stderr" in saved
    assert saved.count("SETUP START example service") == 1
    assert output.out.splitlines()[-1] == saved.splitlines()[-1] == str(transcript.path)


@pytest.mark.asyncio
@pytest.mark.parametrize("scoring_error", [None, "scorer failed"])
async def test_progress_tracks_trials_and_keeps_scoring_distinct(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str], scoring_error: str | None
) -> None:
    loop_thread = get_ident()
    emit = reporting._emit

    def worker_emit(text: str) -> None:
        assert get_ident() != loop_thread
        emit(text)

    monkeypatch.setattr(reporting, "_emit", worker_emit)
    now = [10.0]
    monkeypatch.setattr(reporting.time, "monotonic", lambda: now[0])
    reporter = ProgressReporter(total_suites=1)
    await reporter.experiment_started("suite", 3, tmp_path)
    phases = await reporter.case_started("suite", "same-case", "trial-1", 0)
    await reporter.case_started("suite", "same-case", "trial-2", 1)
    now[0] = 15.0
    await reporter.case_phase("trial-1", "setup")
    now[0] = 25.0
    await reporter.case_phase("trial-1", "agent")
    now[0] = 45.0
    await reporter.case_done("suite", "same-case", duration_seconds=35, trial_id="trial-1")
    await reporter.report_progress()
    output = capsys.readouterr().out
    assert "CASE READY" in output
    assert "scoring pending" in output
    assert "executions 1/3" in output
    assert "queued=1" in output and "scoring=1" in output
    assert "oldest: suite :: same-case [trial 1] (scoring" in output
    assert phases == {"queued": 5.0, "setup": 10.0, "agent": 20.0}
    now[0] = 50.0
    await reporter.case_scored("trial-1", error=scoring_error)
    assert ("CASE ERROR" if scoring_error else "CASE DONE") in capsys.readouterr().out
    assert reporter.has_case_errors() is (scoring_error is not None)
    await reporter.finish_experiment("suite")
    await reporter.report_progress()
    assert "scoring=0" in capsys.readouterr().out
    assert phases["scoring"] == 5.0


@pytest.mark.asyncio
async def test_periodic_progress_stops_with_its_context(monkeypatch: pytest.MonkeyPatch) -> None:
    loop = asyncio.get_running_loop()
    reporter = ProgressReporter(total_suites=1)
    sleeping = asyncio.Event()
    release = asyncio.Event()
    emitted = asyncio.Event()
    cancelled = asyncio.Event()
    lines: list[str] = []

    async def pause(delay: float) -> None:
        assert delay == 30
        sleeping.set()
        try:
            await release.wait()
            release.clear()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    def capture(text: str) -> None:
        lines.append(text)
        loop.call_soon_threadsafe(emitted.set)

    monkeypatch.setattr(reporting.asyncio, "sleep", pause)
    monkeypatch.setattr(reporting, "_emit", capture)
    async with reporter.live_updates():
        await sleeping.wait()
        sleeping.clear()
        release.set()
        await emitted.wait()
        await sleeping.wait()
    assert len(lines) == 1 and lines[0].startswith("PROGRESS")
    assert cancelled.is_set()
