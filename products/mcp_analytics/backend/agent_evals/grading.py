import asyncio
import dataclasses
from collections.abc import Callable, Coroutine, Iterator, Mapping
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
    model: str | None = None  # the version that answered, when an alias was requested


type Grader = Callable[[Scenario, AgentTrial], Coroutine[Any, Any, Judgment]]


@frozen
class Verdict:
    grader: str
    passed: bool | None
    score: float | None
    rationale: str
    error: str | None = None
    model: str | None = None


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
    words = _words(command)
    if next(words, None) != "call":
        return None
    return next((word for word in words if word not in EXEC_CALL_FLAGS), None) or None


def _words(text: str) -> Iterator[str]:
    # The server's parseCommand trims like JavaScript and splits on the first literal space.
    while text := text.strip(_JS_WHITESPACE):
        word, _, text = text.partition(" ")
        yield word


# What JavaScript's String.prototype.trim removes. Python's str.strip also removes \x1c-\x1f and \x85.
_JS_WHITESPACE = "\t\n\x0b\x0c\r \xa0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000\ufeff"


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
    server_origin: str
    model: str
    effort: str | None
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
    return Verdict(
        grader=name, passed=judgment.passed, score=judgment.score, rationale=judgment.rationale, model=judgment.model
    )


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
        answered = [
            {v.grader: v.passed for v in grade.verdicts} for grade in report.grades if grade.outcome == "answered"
        ]
        compared = [passed for passed in answered if passed.get("judge") is not None and passed.get("jev") is not None]
        disagreements = sum(1 for passed in compared if passed["judge"] != passed["jev"])
        lines.append(f"judge and jev disagree on {disagreements} of {len(compared)} trials both graded")
    return "\n".join(lines)
