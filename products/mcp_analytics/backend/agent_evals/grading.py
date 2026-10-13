import asyncio
import dataclasses
from collections.abc import Callable, Coroutine, Mapping
from typing import Any

from pydantic import TypeAdapter

from posthog.dataclasses import frozen

from products.mcp_analytics.backend.agent_evals.agent_loop import AgentTrial
from products.mcp_analytics.backend.agent_evals.scenarios import Scenario

EXEC_TOOL = "exec"
CALL_VERB = "call"
UNKNOWN_VERB = "unknown"


@frozen
class EffectiveCall:
    verb: str
    tool: str | None  # None for discovery verbs, which describe a tool without running it
    is_error: bool


@frozen
class Verdict:
    grader: str
    passed: bool | None  # None: not gradable, so it stays out of pass rates
    score: float | None
    rationale: str


def verdict(grader: str, passed: bool | None, score: float | None, rationale: str) -> Verdict:
    return Verdict(grader=grader, passed=passed, score=score, rationale=rationale)


type Grader = Callable[[Scenario, AgentTrial], Coroutine[Any, Any, Verdict]]


def effective_calls(trial: AgentTrial) -> tuple[EffectiveCall, ...]:
    """Mirrors EFFECTIVE_TOOL_SQL: the CLI-mode dispatcher `exec` hides the tool behind `call`."""
    calls: list[EffectiveCall] = []
    for record in trial.tool_calls:
        if record.name != EXEC_TOOL:
            calls.append(EffectiveCall(verb=CALL_VERB, tool=record.name, is_error=record.is_error))
            continue
        verb, tool = _parse_exec(record.input)
        calls.append(EffectiveCall(verb=verb, tool=tool, is_error=record.is_error))
    return tuple(calls)


def _parse_exec(tool_input: object) -> tuple[str, str | None]:
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    words = command.split() if isinstance(command, str) else []
    if not words:
        return UNKNOWN_VERB, None
    if words[0] != CALL_VERB:
        return words[0], None
    operands = [word for word in words[1:] if not word.startswith("--")]
    return (CALL_VERB, operands[0]) if operands else (UNKNOWN_VERB, None)


async def expected_tools_grader(scenario: Scenario, trial: AgentTrial) -> Verdict:
    if not scenario.expected_tools:
        return verdict("expected_tools", None, None, "scenario lists no expected tools")
    called = {call.tool for call in effective_calls(trial)}
    missing = [tool for tool in scenario.expected_tools if tool not in called]
    if missing:
        return verdict("expected_tools", False, 0.0, f"missing tools: {', '.join(missing)}")
    return verdict("expected_tools", True, 1.0, "every expected tool was called")


@frozen
class TrialGrade:
    scenario_id: str
    trial: int
    outcome: str
    verdicts: tuple[Verdict, ...]


@frozen
class GradedReport:
    server_url: str
    model: str
    effort: str
    started_at: str
    graders: tuple[str, ...]
    grades: tuple[TrialGrade, ...]

    def to_dict(self) -> dict[str, object]:
        return dataclasses.asdict(self)


async def grade_trial(scenario: Scenario, trial: AgentTrial, graders: Mapping[str, Grader]) -> TrialGrade:
    """The outcome gate: only an answered trial reaches a grader, because only it has an answer to grade."""
    if trial.outcome == "answered":
        verdicts = await asyncio.gather(*(grader(scenario, trial) for grader in graders.values()))
    elif trial.outcome == "mcp_error":
        verdicts = [verdict(name, None, None, "mcp_error: infrastructure failure") for name in graders]
    else:
        verdicts = [verdict(name, False, None, trial.outcome) for name in graders]
    return TrialGrade(scenario_id=scenario.id, trial=trial.trial, outcome=trial.outcome, verdicts=tuple(verdicts))


def parse_trials(raw_trials: object) -> tuple[AgentTrial, ...]:
    return TypeAdapter(tuple[AgentTrial, ...]).validate_python(raw_trials)


def format_grade_summary(report: GradedReport) -> str:
    by_scenario: dict[str, list[TrialGrade]] = {}
    for grade in report.grades:
        by_scenario.setdefault(grade.scenario_id, []).append(grade)
    lines = [f"graded {len(report.grades)} trials with {', '.join(report.graders)}"]
    for scenario_id, grades in by_scenario.items():
        rates = []
        for name in report.graders:
            passes = [v.passed for g in grades for v in g.verdicts if v.grader == name and v.passed is not None]
            rates.append(f"{name} {sum(passes)}/{len(passes)}")
        lines.append(f"  {scenario_id}: {', '.join(rates)}")
    if {"judge", "jev"} <= set(report.graders):
        disagreements = sum(1 for grade in report.grades if _disagree(grade, "judge", "jev"))
        lines.append(f"judge and jev disagree on {disagreements} of {len(report.grades)} trials")
    return "\n".join(lines)


def _disagree(grade: TrialGrade, first: str, second: str) -> bool:
    passed = {v.grader: v.passed for v in grade.verdicts}
    return passed.get(first) is not None and passed.get(second) is not None and passed[first] != passed[second]
