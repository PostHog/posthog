"""Scorers for the guided creation suite (``eval_guided_creation.py``).

They live apart from ``scorers.py`` because every one of them grades the same thing, the report the
agent writes after it creates a draft experiment, through the helpers below.

"The final message" means the report: the last message of the turn that first created the experiment.
In a single-turn case, or when no turn created one, it is the conversation's last message. So a case
where the agent creates the draft in turn 1 and only acknowledges the user's reply in turn 2 is still
graded on the report.

A scorer that doesn't apply to a case returns ``score=None``. The harness drops ``None`` from the
averages (``engines/braintrust_patches.py``), so the ``score=1.0`` plus ``skipped`` workaround in
``scorers.py`` isn't needed here. A missing final message scores ``0.0``, so a broken run can't pass.

Deterministic:

* ``ExperimentUrlInReport``: the ``_posthogUrl`` from ``experiment-create`` is in the report.
* ``FlagUrlInReport``: a ``/feature-flags/<id>`` URL for the experiment's own flag is in the report.
* ``ExecuteSqlCallsBeforeCreate``: how many ``execute-sql`` calls came before the first
  ``experiment-create``. Informational, so it never counts toward the averages.
* ``NoUnavailableToolMention``: the report doesn't mention the setup context tool, or any tool that
  isn't enabled.
* ``ReminderLinkedToExperiment``: a ``reminder-create`` call points at the new experiment.

Judged (the creation report unless stated):

* ``NewcomerPrimerUpFront``: definitions and best practices come before the first question, judged on
  the agent's opening rather than the report. Expected per case.
* ``CodeChangesSection``: code changes get their own section, one plain line per file, no diffs.
* ``NextExperimentSuggestion``: a next-experiment suggestion specific to this project.
* ``ClosingQuestionWithOptions``: the report ends with one question that offers next steps.
* ``RuntimeWithTraffic``: the expected runtime comes with the traffic it's based on.
* ``LowTrafficNote``: a low-traffic note that points to session replays and Replay Vision. Expected
  per case.
* ``PlacesLinked``: every PostHog place the report sends the user to has a URL.
"""

from __future__ import annotations

import re
import asyncio
import logging
from typing import Any
from urllib.parse import urlsplit

from braintrust import Score as BraintrustScore

from posthog.dataclasses import frozen

from products.posthog_ai.eval_harness.acp_log import parse_log
from products.posthog_ai.eval_harness.engines.types import ScorerResult
from products.posthog_ai.eval_harness.log_parser import LogParser, describe_tool_use, is_schema_discovery_call
from products.posthog_ai.eval_harness.scorers import BINARY_CHOICE_SCORES, JUDGE_MODEL, JudgedScorer
from products.posthog_ai.eval_harness.scorers.contract import AsyncOnlyScorerMixin, Score, Scorer

logger = logging.getLogger(__name__)

__all__ = [
    "ClosingQuestionWithOptions",
    "CodeChangesSection",
    "ExecuteSqlCallsBeforeCreate",
    "ExperimentUrlInReport",
    "FlagUrlInReport",
    "LowTrafficNote",
    "NewcomerPrimerUpFront",
    "NextExperimentSuggestion",
    "NoUnavailableToolMention",
    "PlacesLinked",
    "ReminderLinkedToExperiment",
    "RuntimeWithTraffic",
]

CREATE_TOOL = "experiment-create"
EXECUTE_SQL_TOOL = "execute-sql"
REMINDER_TOOL = "reminder-create"
QUESTION_TOOL = "AskUserQuestion"
FILE_EDIT_TOOLS = frozenset({"Edit", "MultiEdit", "Write", "NotebookEdit"})

# Same shape as the cli_mcp URL pattern: stop at whitespace and the delimiters that wrap a link in
# Markdown, JSON or TOON, and at a backslash, because tool results arrive JSON-escaped.
_URL_RE = re.compile(r"https?://[^\s\"'`)\]<>\\]+")
_EXPERIMENT_PATH_RE = re.compile(r"/experiments/(\d+)/?$")
# `/feature-flags/` is the app's route; the older `/feature_flags/` still redirects to it.
_FLAG_PATH_RE = re.compile(r"/feature[-_]flags/(\d+)/?$")
# The response lists `id` first, as JSON (`"id": 12`) or as TOON (`id: 12`).
_ID_FIELD_RE = re.compile(r'"id"\s*:\s*(\d+)|(?:^|\n)\s*id:\s*(\d+)')
_URL_TRAILING_PUNCTUATION = ".,;:!?"

_SETUP_CONTEXT_RE = re.compile(r"setup[\s_-]*context", re.IGNORECASE)
_TOOL_WORD_RE = re.compile(r"\b(?:tools?|connection|MCP)\b", re.IGNORECASE)
_UNAVAILABLE_RE = re.compile(
    r"\b(?:not|isn[’']t|wasn[’']t|aren[’']t)\s+(?:enabled|available|exposed)\b|\bunavailable\b|\bdisabled\b",
    re.IGNORECASE,
)
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|\n+")


@frozen
class CreatedExperiment:
    id: int | None
    url: str | None
    """The ``_posthogUrl`` from the create response, when the response carried one."""


@frozen
class Opening:
    text: str
    """Everything the agent wrote before the user had to answer it or the draft was created."""
    boundary: str
    """What ended the opening, in words the judge reads."""


def _parser(output: dict[str, Any] | None) -> LogParser | None:
    raw_log = (output or {}).get("raw_log")
    if not raw_log:
        return None
    return LogParser.cached(raw_log, initial_prompt=(output or {}).get("prompt", "") or "")


def _seed(output: dict[str, Any] | None) -> dict[str, Any]:
    seed = (output or {}).get("seed")
    return seed if isinstance(seed, dict) else {}


def _user_prompt(output: dict[str, Any] | None) -> str:
    prompt = (output or {}).get("prompt")
    return prompt if isinstance(prompt, str) else ""


def _urls(text: str) -> list[str]:
    return [url.rstrip(_URL_TRAILING_PUNCTUATION) for url in _URL_RE.findall(text or "")]


def _links_to(url: str, target: str) -> bool:
    """True when ``url`` is ``target`` itself or a tab, anchor or subpath of it."""
    target = target.rstrip(_URL_TRAILING_PUNCTUATION).rstrip("/")
    url = url.rstrip("/")
    return url == target or (url.startswith(target) and url[len(target)] in "?#/")


def _path_id(url: str, pattern: re.Pattern[str]) -> int | None:
    match = pattern.search(urlsplit(url).path)
    return int(match.group(1)) if match else None


def created_experiments(parser: LogParser) -> list[CreatedExperiment]:
    created: list[CreatedExperiment] = []
    for call in parser.get_tool_calls(CREATE_TOOL):
        if call.is_error:
            continue
        url = next((u for u in _urls(call.output) if _path_id(u, _EXPERIMENT_PATH_RE) is not None), None)
        experiment_id = _path_id(url, _EXPERIMENT_PATH_RE) if url else None
        if experiment_id is None and (match := _ID_FIELD_RE.search(call.output or "")):
            experiment_id = int(match.group(1) or match.group(2))
        created.append(CreatedExperiment(id=experiment_id, url=url))
    return created


def report_message(output: dict[str, Any] | None) -> str:
    """The last message of the turn that first created the experiment, else the last message."""
    turn_logs = (output or {}).get("turn_logs")
    if isinstance(turn_logs, list):
        for turn_log in turn_logs:
            if not isinstance(turn_log, str) or not turn_log:
                continue
            parser = LogParser.cached(turn_log)
            if any(not call.is_error for call in parser.get_tool_calls(CREATE_TOOL)):
                return parser.get_final_agent_message() or ""
    last_message = (output or {}).get("last_message")
    return last_message if isinstance(last_message, str) else ""


def _question_text(tool_input: dict[str, Any]) -> str:
    questions = tool_input.get("questions")
    if not isinstance(questions, list):
        return ""
    parts: list[str] = []
    for question in questions:
        if not isinstance(question, dict):
            continue
        options = question.get("options")
        labels = [o.get("label", "") for o in options if isinstance(o, dict)] if isinstance(options, list) else []
        parts.append(f"{question.get('question', '')} Options: {', '.join(label for label in labels if label)}")
    return " ".join(parts)


def opening(output: dict[str, Any] | None) -> Opening:
    """What the agent wrote before the user had to answer it, or before the draft if it asked nothing.

    The sandbox has no one to answer the question tool, so the agent server cancels the call and tells
    the agent to restate the question and end its turn. The opening is therefore the first turn, up to
    the first ``experiment-create`` call. A question tool call stays in the text where it happened.
    """
    turn_logs = (output or {}).get("turn_logs")
    first_turn = turn_logs[0] if isinstance(turn_logs, list) and turn_logs else None
    raw_log = first_turn if isinstance(first_turn, str) and first_turn else (output or {}).get("raw_log")
    parts: list[str] = []
    if raw_log:
        for message in parse_log(raw_log).messages:
            content = message.get("content")
            if message.get("role") != "assistant" or not isinstance(content, list):
                continue
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "text" and block.get("text"):
                    parts.append(block["text"])
                elif block.get("type") == "tool_use":
                    raw_input = block.get("input")
                    name, tool_input = describe_tool_use(
                        block.get("name"), raw_input if isinstance(raw_input, dict) else {}
                    )
                    if name == CREATE_TOOL:
                        return Opening(text="\n\n".join(parts), boundary="the agent creating the draft experiment")
                    if name == QUESTION_TOOL:
                        parts.append(f"[Asked with the question tool: {_question_text(tool_input)}]")
    return Opening(
        text="\n\n".join(parts),
        boundary="the end of the agent's first turn, where it waited for the user's reply",
    )


def changed_files(parser: LogParser) -> list[str]:
    files: list[str] = []
    for call in parser.get_tool_calls():
        if call.is_error or call.name not in FILE_EDIT_TOOLS:
            continue
        path = call.input.get("file_path") or call.input.get("notebook_path")
        if isinstance(path, str) and path and path not in files:
            files.append(path)
    return files


class ExperimentUrlInReport(Scorer):
    """Binary: is the ``_posthogUrl`` that ``experiment-create`` returned in the report?

    A tab or anchor on that URL counts. When the create response carried no URL, a link to the created
    experiment's id counts instead, and the metadata says so. ``None`` when no create succeeded:
    ``experiment_created_successfully`` covers that.
    """

    def _name(self) -> str:
        return "experiment_url_in_report"

    def _run_eval_sync(self, output: dict | None, expected: dict | None = None, **kwargs) -> Score:
        parser = _parser(output)
        if parser is None:
            return Score(name=self._name(), score=None, metadata={"reason": "No raw log"})
        created = created_experiments(parser)
        if not created:
            return Score(name=self._name(), score=None, metadata={"reason": f"{CREATE_TOOL} never succeeded"})
        report = report_message(output)
        if not report.strip():
            return Score(name=self._name(), score=0.0, metadata={"reason": "No final message"})
        report_urls = _urls(report)

        expected_urls = [experiment.url for experiment in created if experiment.url]
        if expected_urls:
            surfaced = [url for url in report_urls if any(_links_to(url, target) for target in expected_urls)]
            return Score(
                name=self._name(),
                score=1.0 if surfaced else 0.0,
                metadata={"expected_urls": expected_urls, "surfaced": surfaced, "url_source": "_posthogUrl"},
            )

        ids = {experiment.id for experiment in created if experiment.id is not None}
        if not ids:
            return Score(
                name=self._name(),
                score=None,
                metadata={"reason": f"{CREATE_TOOL} output carried neither a _posthogUrl nor an id"},
            )
        surfaced = [url for url in report_urls if _path_id(url, _EXPERIMENT_PATH_RE) in ids]
        return Score(
            name=self._name(),
            score=1.0 if surfaced else 0.0,
            metadata={"experiment_ids": sorted(ids), "surfaced": surfaced, "url_source": "experiment id"},
        )


class FlagUrlInReport(AsyncOnlyScorerMixin, Scorer):
    """Binary: does the report link the created experiment's own feature flag (``/feature-flags/<id>``)?

    The create response leaves out the flag's id, so the scorer reads it from the database through the
    case's ``seed.team_id``. That also covers device-id bucketing, where the agent creates the flag first.
    ``None`` when no create succeeded or the experiment can't be found.
    """

    def _name(self) -> str:
        return "flag_url_in_report"

    async def _run_eval_async(self, output: dict | None, expected: dict | None = None, **kwargs) -> Score:
        parser = _parser(output)
        if parser is None:
            return Score(name=self._name(), score=None, metadata={"reason": "No raw log"})
        experiment_ids = sorted({e.id for e in created_experiments(parser) if e.id is not None})
        if not experiment_ids:
            return Score(name=self._name(), score=None, metadata={"reason": f"{CREATE_TOOL} never succeeded"})
        team_id = _seed(output).get("team_id")
        if not isinstance(team_id, int):
            return Score(name=self._name(), score=0.0, metadata={"reason": "No seed.team_id, the case needs a seeder"})
        report = report_message(output)
        if not report.strip():
            return Score(name=self._name(), score=0.0, metadata={"reason": "No final message"})

        flag_ids = await asyncio.to_thread(self._flag_ids, team_id, experiment_ids)
        if not flag_ids:
            return Score(
                name=self._name(),
                score=None,
                metadata={"reason": "The created experiment is not in the database", "experiment_ids": experiment_ids},
            )
        surfaced = [url for url in _urls(report) if _path_id(url, _FLAG_PATH_RE) in flag_ids]
        return Score(
            name=self._name(),
            score=1.0 if surfaced else 0.0,
            metadata={"flag_ids": sorted(flag_ids), "surfaced": surfaced},
        )

    @staticmethod
    def _flag_ids(team_id: int, experiment_ids: list[int]) -> set[int]:
        from products.experiments.backend.models.experiment import Experiment

        return set(
            Experiment.objects.filter(team_id=team_id, id__in=experiment_ids).values_list("feature_flag_id", flat=True)
        )


class ExecuteSqlCallsBeforeCreate(Scorer):
    """Informational: how many ``execute-sql`` calls came before the first ``experiment-create`` call.

    A count isn't a 0 to 1 score, so ``score`` stays ``None`` and the average ignores it. The count goes
    to the reported result as a numeric value, to the score metadata, and to the run transcript.
    Attempts count, failed or not, and catalog lookups are counted separately in the metadata. Without
    a create call, the count covers the whole run.
    """

    def _name(self) -> str:
        return "execute_sql_calls_before_create"

    def _run_eval_sync(self, output: dict | None, expected: dict | None = None, **kwargs) -> Score:
        parser = _parser(output)
        if parser is None:
            return Score(name=self._name(), score=None, metadata={"reason": "No raw log"})
        all_calls = parser.get_tool_calls()
        creates = [call for call in all_calls if call.name == CREATE_TOOL]
        cutoff = min(call.position for call in creates) if creates else None
        before = [call for call in all_calls if cutoff is None or call.position < cutoff]
        sql_calls = [call for call in before if call.name == EXECUTE_SQL_TOOL]
        count = len(sql_calls)
        metadata: dict[str, Any] = {
            "execute_sql_calls_before_create": count,
            "failed_execute_sql_calls": sum(1 for call in sql_calls if call.is_error),
            "schema_discovery_calls": sum(1 for call in sql_calls if is_schema_discovery_call(call)),
            "tool_calls_before_create": len(before),
            "created": cutoff is not None,
        }
        case = kwargs.get("input")
        case_name = case.get("name") if isinstance(case, dict) else None
        logger.info("%s for case %s: %d (%s)", self._name(), case_name or "?", count, metadata)
        return Score(
            name=self._name(),
            score=None,
            metadata=metadata,
            result=ScorerResult(status="ok", value=count, metadata=metadata),
        )


class NoUnavailableToolMention(Scorer):
    """Binary: the report doesn't mention the setup context tool, or a tool that isn't enabled.

    A sentence fails when it names setup context in any spelling, or when it pairs "tool", "connection"
    or "MCP" with "not enabled", "not available", "unavailable" or "disabled". "The flag isn't enabled
    until you launch" passes, because it names no tool.
    """

    def _name(self) -> str:
        return "no_unavailable_tool_mention"

    def _run_eval_sync(self, output: dict | None, expected: dict | None = None, **kwargs) -> Score:
        report = report_message(output)
        if not report.strip():
            return Score(name=self._name(), score=0.0, metadata={"reason": "No final message"})
        mentions = [
            sentence.strip()
            for sentence in _SENTENCE_SPLIT_RE.split(report)
            if _SETUP_CONTEXT_RE.search(sentence)
            or (_TOOL_WORD_RE.search(sentence) and _UNAVAILABLE_RE.search(sentence))
        ]
        if mentions:
            return Score(name=self._name(), score=0.0, metadata={"mentions": mentions})
        return Score(name=self._name(), score=1.0, metadata={})


class ReminderLinkedToExperiment(Scorer):
    """Binary: when the agent sets a reminder, is it attached to the experiment it created?

    Passes when a successful ``reminder-create`` call has ``resource_type: experiment`` and the created
    experiment's id as ``resource_id``. ``None`` when no reminder was set. The two cases end before the
    agent offers next steps, so this scores only once a case answers the closing question, for example
    with a follow-up turn such as "Yes, set the reminder".
    """

    def _name(self) -> str:
        return "reminder_linked_to_experiment"

    def _run_eval_sync(self, output: dict | None, expected: dict | None = None, **kwargs) -> Score:
        parser = _parser(output)
        if parser is None:
            return Score(name=self._name(), score=None, metadata={"reason": "No raw log"})
        reminders = [call for call in parser.get_tool_calls(REMINDER_TOOL) if not call.is_error]
        if not reminders:
            return Score(name=self._name(), score=None, metadata={"reason": f"No successful {REMINDER_TOOL} call"})
        experiment_ids = {str(e.id) for e in created_experiments(parser) if e.id is not None}
        attached = [
            {"resource_type": call.input.get("resource_type"), "resource_id": call.input.get("resource_id")}
            for call in reminders
        ]
        linked = [
            reminder
            for reminder in attached
            if reminder["resource_type"] == "experiment" and str(reminder["resource_id"]).strip() in experiment_ids
        ]
        return Score(
            name=self._name(),
            score=1.0 if linked else 0.0,
            metadata={"reminders": attached, "experiment_ids": sorted(experiment_ids)},
        )


def apply_expectation(verdict: BraintrustScore, *, expect_present: bool) -> BraintrustScore:
    """Turn a judge's "is it there?" verdict into pass or fail for a case that expects it absent.

    Only a real judge choice flips. A judge error or a short-circuit keeps its score.
    """
    metadata = dict(verdict.metadata or {})
    if expect_present or "choice" not in metadata or verdict.score is None:
        return verdict
    return Score(
        name=verdict.name,
        score=1.0 - verdict.score,
        metadata={**metadata, "expected": "absent"},
    )


class _ReportJudge(JudgedScorer):
    """A yes/no judge of the creation report, with the user's prompt and the seeded project facts."""

    def _prepare(self, output: Any, expected: Any) -> dict[str, Any] | BraintrustScore:
        report = report_message(output)
        if not report.strip():
            return Score(name=self._name(), score=0.0, metadata={"reason": "No final message"})
        return {
            "output": {
                "prompt": _user_prompt(output),
                "message": report,
                "project": _seed(output).get("project_summary") or "(not provided)",
            }
        }


class _ExpectedPresenceJudge(_ReportJudge):
    """A report judge whose case says whether the content should be there (``expected[name]`` is a bool)."""

    def _expectation(self, expected: Any) -> bool | None:
        value = expected.get(self._name()) if isinstance(expected, dict) else None
        return value if isinstance(value, bool) else None

    def _prepare(self, output: Any, expected: Any) -> dict[str, Any] | BraintrustScore:
        if self._expectation(expected) is None:
            return Score(name=self._name(), score=None, metadata={"reason": "Not applicable to this case"})
        return super()._prepare(output, expected)

    async def _run_eval_async(self, output: Any, expected: Any = None, **kwargs: Any) -> BraintrustScore:
        verdict = await super()._run_eval_async(output, expected, **kwargs)
        expect_present = self._expectation(expected)
        if expect_present is None:
            return verdict
        return apply_expectation(verdict, expect_present=expect_present)


_REPORT_CONTEXT = """
The user asked:
<prompt>
{{output.prompt}}
</prompt>

Facts about the user's PostHog project:
<project>
{{output.project}}
</project>

The agent's message after it created the draft experiment:
<message>
{{output.message}}
</message>
""".strip()


class NewcomerPrimerUpFront(_ExpectedPresenceJudge):
    """Binary: did the opening carry short definitions and the main best practices?

    Judged on ``opening()``, not the report. ``expected["newcomer_primer_up_front"]`` is ``True`` for a
    newcomer, who should get them before the first question (or before the draft when nothing is asked),
    and ``False`` for an existing user, who shouldn't.
    """

    def __init__(self, **kwargs: Any):
        super().__init__(
            name="newcomer_primer_up_front",
            prompt_template="""
You are reviewing how an agent opened a conversation with a user who asked it to set up a PostHog experiment.

The user asked:
<prompt>
{{output.prompt}}
</prompt>

Below is everything the agent wrote before {{output.boundary}}:
<opening>
{{output.opening}}
</opening>

Does the opening include BOTH of these?
1. Short definitions, in plain words, of at least: a variant (and the control), bucketing (how people are assigned to a variant), and a device ID. One line each is enough. Describing only an effect, such as "a visitor keeps their variant when they sign in", is not a definition.
2. The main best practices for running an experiment: at least three of one hypothesis and one primary metric, working out the sample size or running time first, changing one thing at a time, not stopping early when it looks good, and finishing properly with a conclusion.

Answer `yes` only if both are there. Answer `no` if either is missing.
""".strip(),
            choice_scores=BINARY_CHOICE_SCORES,
            model=JUDGE_MODEL,
            max_completion_tokens=512,
            **kwargs,
        )

    def _prepare(self, output: Any, expected: Any) -> dict[str, Any] | BraintrustScore:
        expect_present = self._expectation(expected)
        if expect_present is None:
            return Score(name=self._name(), score=None, metadata={"reason": "Not applicable to this case"})
        if not (output or {}).get("raw_log"):
            return Score(name=self._name(), score=0.0, metadata={"reason": "No raw log"})
        opened = opening(output)
        if not opened.text.strip():
            # Nothing was said before the question or the draft, so the primer is certainly absent.
            return Score(
                name=self._name(),
                score=0.0 if expect_present else 1.0,
                metadata={"reason": f"The agent wrote nothing before {opened.boundary}"},
            )
        return {"output": {"prompt": _user_prompt(output), "opening": opened.text, "boundary": opened.boundary}}


class CodeChangesSection(_ReportJudge):
    """Binary: do the code changes get their own section, one plain line per file, with no diffs?

    ``None`` when the agent changed no files (Claude Code's file tools only).
    """

    def __init__(self, **kwargs: Any):
        super().__init__(
            name="code_changes_section",
            prompt_template=f"""
You are reviewing the message an agent wrote after it set up a PostHog experiment and changed code in the user's repository.

{_REPORT_CONTEXT}

The agent changed these files: {{{{output.files}}}}

Answer `yes` only if all of these hold:
1. The message has a separate section for the code changes, with its own heading or label, rather than mentioning them inside another section.
2. That section gives each changed file one short line that says in plain words what changed. Someone who doesn't write code could follow it.
3. The message shows no diffs and no blocks of the changed code.

Answer `no` if any of these fails.
""".strip(),
            choice_scores=BINARY_CHOICE_SCORES,
            model=JUDGE_MODEL,
            max_completion_tokens=512,
            **kwargs,
        )

    def _prepare(self, output: Any, expected: Any) -> dict[str, Any] | BraintrustScore:
        parser = _parser(output)
        files = changed_files(parser) if parser is not None else []
        if not files:
            return Score(name=self._name(), score=None, metadata={"reason": "The agent changed no files"})
        prepared = super()._prepare(output, expected)
        if isinstance(prepared, BraintrustScore):
            return prepared
        prepared["output"]["files"] = ", ".join(files)
        return prepared


class NextExperimentSuggestion(_ReportJudge):
    """Binary: does the report suggest a next experiment that is specific to this project?"""

    def __init__(self, **kwargs: Any):
        super().__init__(
            name="next_experiment_suggestion",
            prompt_template=f"""
You are reviewing the message an agent wrote after it set up a PostHog experiment.

{_REPORT_CONTEXT}

Answer `yes` only if the message suggests what to test in a future experiment, after this one, and the suggestion is specific to this project. It must build on something the agent learned here: the project's traffic, its past experiments, its events, or this test. For example: "with about 10 visitors a month only big differences show up, so next time test a bigger change, such as a new page layout".

Answer `no` if there is no suggestion for a future experiment, or if the suggestion is generic advice that would fit any project, such as "keep experimenting" or "test one change at a time".
""".strip(),
            choice_scores=BINARY_CHOICE_SCORES,
            model=JUDGE_MODEL,
            max_completion_tokens=512,
            **kwargs,
        )


class ClosingQuestionWithOptions(_ReportJudge):
    """Binary: does the report end with one question that offers next-step options?"""

    def __init__(self, **kwargs: Any):
        super().__init__(
            name="closing_question_with_options",
            prompt_template=f"""
You are reviewing how an agent ended its message after it set up a draft PostHog experiment.

{_REPORT_CONTEXT}

Answer `yes` only if the message ends with one question to the user that offers next steps as options to choose from: things the agent could do next, such as set a reminder to check the results, watch sessions with Replay Vision, ask users with a survey, end an older test, or launch. It needs at least two options, laid out so the user can pick one. A short closing line after the question is fine.

Answer `no` if:
- the message ends without a question, or with an open offer such as "let me know if you need anything" or "I can do the PostHog parts now if you like";
- the closing question offers a single yes or no action rather than options;
- the message ends with several separate questions.
""".strip(),
            choice_scores=BINARY_CHOICE_SCORES,
            model=JUDGE_MODEL,
            max_completion_tokens=512,
            **kwargs,
        )


class RuntimeWithTraffic(_ReportJudge):
    """Binary: does the report give the expected runtime together with the traffic behind it?"""

    def __init__(self, **kwargs: Any):
        super().__init__(
            name="runtime_with_traffic",
            prompt_template=f"""
You are reviewing the message an agent wrote after it set up a PostHog experiment.

{_REPORT_CONTEXT}

Answer `yes` only if the message says how long this experiment is expected to run (a number of days or weeks, or an end date) and, with it, the traffic that estimate is based on. For example: "about 40 days at about 20 visitors a day", or "about 2 weeks, based on about 3,000 visitors a week". Both the runtime and the traffic number must be there, and clearly linked.

Answer `no` if there is no runtime, if the runtime has no traffic number behind it, or if it is only a general rule such as "run it for at least two weeks".
""".strip(),
            choice_scores=BINARY_CHOICE_SCORES,
            model=JUDGE_MODEL,
            max_completion_tokens=512,
            **kwargs,
        )


class LowTrafficNote(_ExpectedPresenceJudge):
    """Binary: is there a low-traffic note that points to session replays and Replay Vision?

    ``expected["low_traffic_note"]`` is ``True`` for the low-traffic newcomer and ``False`` for the
    existing user, whose traffic is healthy.
    """

    def __init__(self, **kwargs: Any):
        super().__init__(
            name="low_traffic_note",
            prompt_template=f"""
You are reviewing the message an agent wrote after it set up a PostHog experiment.

{_REPORT_CONTEXT}

Does the message include a note that says both of these?
1. This project's traffic is low, so it will take a long time to reach a significant result, or it may never reach one.
2. The user can learn what people do in each variant from session replays and from Replay Vision. Both must be named.

Answer `yes` only if both parts are there. Answer `no` if either is missing.
""".strip(),
            choice_scores=BINARY_CHOICE_SCORES,
            model=JUDGE_MODEL,
            max_completion_tokens=512,
            **kwargs,
        )


class PlacesLinked(_ReportJudge):
    """Binary: does every PostHog place the report sends the user to come with a URL?"""

    def __init__(self, **kwargs: Any):
        super().__init__(
            name="places_linked",
            prompt_template=f"""
You are reviewing the message an agent wrote after it set up a PostHog experiment.

{_REPORT_CONTEXT}

Find every place in PostHog that the message tells the user to open, visit, check or use. For example: the experiment page, one of its tabs (Settings, Recordings, User feedback), the feature flag, session replays, health checks, a dashboard, an insight, or a project setting. A place counts when the user is told to go there or look at something there.

Answer `yes` only if each of those places has a URL in the message, as a Markdown link or a full URL. Also answer `yes` if the message sends the user to no PostHog place at all.

Answer `no` if at least one place has no URL.
""".strip(),
            choice_scores=BINARY_CHOICE_SCORES,
            model=JUDGE_MODEL,
            max_completion_tokens=512,
            **kwargs,
        )
