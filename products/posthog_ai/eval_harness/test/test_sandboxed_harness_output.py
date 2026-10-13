from __future__ import annotations

import sys
import json
import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from functools import partial
from pathlib import Path
from threading import get_ident
from typing import Any, Literal

import pytest
from unittest.mock import AsyncMock, MagicMock

from django.db import OperationalError

from botocore.exceptions import ClientError
from clickhouse_driver.errors import ErrorCodes, NetworkError, ServerException
from psycopg import OperationalError as PsycopgOperationalError
from psycopg.errors import AdminShutdown, InvalidPassword

from posthog.exceptions import ClickHouseAtCapacity, ClickHouseQueryMemoryLimitExceeded, ClickHouseQueryTimeOut

from products.posthog_ai.eval_harness import base
from products.posthog_ai.eval_harness.acp_log import GenerationDescriptor, ParsedLog
from products.posthog_ai.eval_harness.config import AgentArtifacts, SandboxedEvalCase
from products.posthog_ai.eval_harness.engines.types import AggregateScore, EvalSummary, NullCaseHooks
from products.posthog_ai.eval_harness.harness.cli import SkillDelivery
from products.posthog_ai.eval_harness.harness.reporting import ProgressReporter, SuiteRunResult
from products.posthog_ai.eval_harness.harness.transcript import RunTranscript
from products.posthog_ai.eval_harness.harness.trial_stats import ScorerTrialStats
from products.posthog_ai.eval_harness.scorers import ExitCodeZero
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
            "    s: 72.0% (95% CI 61.0-83.0%)\n  PostHog",
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
    await reporter.record_posthog_evaluations_url("exp", "bd8b7f0d-7cc3-4ea3-a3a6-53be0d9e6eb4")
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
    assert output.count("CASE DONE" if recovers else "CASE ERROR") == 1
    assert reporter.has_case_errors() is (not recovers)
    assert ctx.sandbox_slots._value == ctx.team_setup_slots._value == 1
    assert not broken_workers
