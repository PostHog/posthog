from __future__ import annotations

import sys
import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from unittest.mock import MagicMock

from products.posthog_ai.eval_harness import base
from products.posthog_ai.eval_harness.acp_log import GenerationDescriptor, ParsedLog
from products.posthog_ai.eval_harness.engines.types import AggregateScore, EvalSummary, NullCaseHooks
from products.posthog_ai.eval_harness.harness.reporting import ProgressReporter, SuiteRunResult
from products.posthog_ai.eval_harness.harness.transcript import RunTranscript
from products.posthog_ai.eval_harness.scorers import ExitCodeZero


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
