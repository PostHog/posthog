import asyncio
import dataclasses
from collections.abc import Callable, Coroutine, Mapping
from typing import Any

from posthog.dataclasses import frozen

from products.mcp_analytics.backend.agent_evals.agent_loop import AgentTrial
from products.mcp_analytics.backend.agent_evals.scenarios import Scenario

EXEC_TOOL = "exec"
# The flags the server's parseCallFlags strips before the inner tool name.
EXEC_CALL_FLAGS = frozenset({"--json", "--confirm"})


@frozen
class Judgment:
    passed: bool | None  # None: nothing to grade, so it stays out of pass rates
    score: float | None
    rationale: str


type Grader = Callable[[Scenario, AgentTrial], Coroutine[Any, Any, Judgment]]


@frozen
class Verdict:
    grader: str
    passed: bool | None
    score: float | None
    rationale: str
    error: str | None = None


def called_tools(trial: AgentTrial) -> frozenset[str]:
    """The tools a trial called, with PostHog's `exec` dispatcher unwrapped to the tool behind `call`.

    Discovery verbs such as `learn` or `info` only describe a tool, so they name none. An attempt
    counts whether or not it errored, because the grader asks whether the agent reached for the tool.
    """
    tools: set[str] = set()
    for record in trial.tool_calls:
        if record.name != EXEC_TOOL:
            tools.add(record.name)
        elif target := _exec_call_target(record.input):
            tools.add(target)
    return frozenset(tools)


def _exec_call_target(tool_input: object) -> str | None:
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    if not isinstance(command, str):
        return None
    verb, rest = _split_verb(command)
    if verb != "call":
        return None
    target, rest = _split_verb(rest)
    while target in EXEC_CALL_FLAGS:
        target, rest = _split_verb(rest)
    return target or None


def _split_verb(text: str) -> tuple[str, str]:
    # The server's parseCommand splits on the first literal space, so a tab or newline stays in the verb.
    verb, _, rest = text.strip().partition(" ")
    return verb, rest.strip()


async def expected_tools_grader(scenario: Scenario, trial: AgentTrial) -> Judgment:
    if not scenario.expected_tools:
        return Judgment(passed=None, score=None, rationale="scenario lists no expected tools")
    missing = [tool for tool in scenario.expected_tools if tool not in called_tools(trial)]
    if missing:
        return Judgment(passed=False, score=0.0, rationale=f"missing tools: {', '.join(missing)}")
    return Judgment(passed=True, score=1.0, rationale="every expected tool was called")


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
    grader_models: dict[str, str]
    grades: tuple[TrialGrade, ...]

    def to_dict(self) -> dict[str, object]:
        return dataclasses.asdict(self)


async def grade_trial(scenario: Scenario, trial: AgentTrial, graders: Mapping[str, Grader]) -> TrialGrade:
    """The outcome gate: only an answered trial reaches a grader, because only it has an answer to grade."""
    if trial.outcome == "answered":
        verdicts = await asyncio.gather(
            *(_run_grader(name, grader, scenario, trial) for name, grader in graders.items())
        )
    elif trial.outcome == "mcp_error":
        verdicts = [
            Verdict(grader=name, passed=None, score=None, rationale="mcp_error: infrastructure failure")
            for name in graders
        ]
    else:
        verdicts = [Verdict(grader=name, passed=False, score=None, rationale=trial.outcome) for name in graders]
    return TrialGrade(scenario_id=scenario.id, trial=trial.trial, outcome=trial.outcome, verdicts=tuple(verdicts))


async def _run_grader(name: str, grader: Grader, scenario: Scenario, trial: AgentTrial) -> Verdict:
    try:
        judgment = await grader(scenario, trial)
    except Exception as error:
        # One failed call must not discard the verdicts already paid for in the rest of the run.
        return Verdict(
            grader=name, passed=None, score=None, rationale="grader failed", error=f"{type(error).__name__}: {error}"
        )
    return Verdict(grader=name, passed=judgment.passed, score=judgment.score, rationale=judgment.rationale)


def format_grade_summary(report: GradedReport) -> str:
    graders = tuple(report.grader_models)
    by_scenario: dict[str, list[TrialGrade]] = {}
    for grade in report.grades:
        by_scenario.setdefault(grade.scenario_id, []).append(grade)
    lines = [f"graded {len(report.grades)} trials with {', '.join(graders)}"]
    for scenario_id, grades in by_scenario.items():
        rates = []
        for name in graders:
            verdicts = [v for g in grades for v in g.verdicts if v.grader == name]
            passes = [v.passed for v in verdicts if v.passed is not None]
            errors = sum(1 for v in verdicts if v.error)
            rates.append(f"{name} {sum(passes)}/{len(passes)}" + (f" ({errors} errors)" if errors else ""))
        lines.append(f"  {scenario_id}: {', '.join(rates)}")
    if {"judge", "jev"} <= set(graders):
        # Only answered trials reached the graders; the gate's verdicts on the rest would agree by construction.
        pairs = [_pair(grade, "judge", "jev") for grade in report.grades if grade.outcome == "answered"]
        compared = [pair for pair in pairs if None not in pair]
        disagreements = sum(1 for first, second in compared if first != second)
        lines.append(f"judge and jev disagree on {disagreements} of {len(compared)} trials both graded")
    return "\n".join(lines)


def _pair(grade: TrialGrade, first: str, second: str) -> tuple[bool | None, bool | None]:
    passed = {v.grader: v.passed for v in grade.verdicts}
    return passed.get(first), passed.get(second)
