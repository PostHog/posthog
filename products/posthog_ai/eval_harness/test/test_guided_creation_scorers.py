from __future__ import annotations

import json
import asyncio
import itertools
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from unittest.mock import patch

from braintrust import Score as BraintrustScore

from products.posthog_ai.evals.experiments.guided_creation_scorers import (
    CodeChangesSection,
    ExecuteSqlCallsBeforeCreate,
    ExperimentUrlInReport,
    FlagUrlInReport,
    NewcomerPrimerUpFront,
    NoUnavailableToolMention,
    ReminderLinkedToExperiment,
    apply_expectation,
    opening,
    report_message,
)
from products.posthog_ai.evals.experiments.seeders import (
    AA_TEST_FLAG_KEY,
    NEWCOMER_AA_TEST_AGE_DAYS,
    newcomer_events,
    newcomer_visits,
)

EXPERIMENT_URL = "https://us.posthog.com/project/7/experiments/42"
FLAG_URL = "https://us.posthog.com/project/7/feature-flags/9"
CREATE_OUTPUT = json.dumps(
    {"id": 42, "name": "Homepage headline", "feature_flag_key": "homepage-headline", "_posthogUrl": EXPERIMENT_URL}
)
SQL_QUERY = {"query": "SELECT count() FROM events WHERE event = '$pageview'"}
DISCOVERY_QUERY = {"query": "SELECT column_name FROM system.information_schema.columns"}

# Unique call ids keep every built log distinct, so LogParser's process-wide cache never mixes two tests.
_call_ids = itertools.count()


def _update(update: dict[str, Any]) -> str:
    return json.dumps(
        {
            "notification": {"method": "session/update", "params": {"update": update}},
            "timestamp": "2026-10-21T00:00:00Z",
        }
    )


def _text(text: str) -> list[str]:
    return [_update({"sessionUpdate": "agent_message", "content": {"type": "text", "text": text}})]


def _tool(
    name: str, raw_input: dict[str, Any] | None = None, raw_output: str = "ok", *, failed: bool = False
) -> list[str]:
    call_id = f"call-{next(_call_ids)}"
    return [
        _update(
            {
                "sessionUpdate": "tool_call",
                "toolCallId": call_id,
                "rawInput": raw_input or {},
                "_meta": {"claudeCode": {"toolName": name}},
            }
        ),
        _update(
            {
                "sessionUpdate": "tool_call_update",
                "toolCallId": call_id,
                "status": "failed" if failed else "completed",
                "rawOutput": raw_output,
            }
        ),
    ]


def _create(raw_output: str = CREATE_OUTPUT, *, failed: bool = False) -> list[str]:
    return _tool("mcp__posthog__experiment-create", {"name": "Homepage headline"}, raw_output, failed=failed)


def _log(*steps: list[str]) -> str:
    return "\n".join(line for step in steps for line in step)


def _output(*steps: list[str], last_message: str, seed: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "raw_log": _log(*steps),
        "prompt": "Set up a homepage experiment",
        "last_message": last_message,
        "seed": seed or {},
    }


def _two_turn_output(turn1: list[list[str]], turn2: list[list[str]], *, last_message: str) -> dict[str, Any]:
    turn1_log, turn2_log = _log(*turn1), _log(*turn2)
    return {
        "raw_log": f"{turn1_log}\n{turn2_log}",
        "prompt": "Set up a homepage experiment",
        "last_message": last_message,
        "turn_logs": [turn1_log, turn2_log],
        "turn_prompts": ["Set up a homepage experiment", "Go with what you recommend"],
        "seed": {"team_id": 7},
    }


@pytest.mark.parametrize(
    "message,expected_score",
    [
        (f"Your draft is ready: [open it]({EXPERIMENT_URL}).", 1.0),
        (f"Watch the recordings at {EXPERIMENT_URL}?tab=recordings", 1.0),
        ("Your draft is ready. Open the experiment page to review it.", 0.0),
        ("See https://us.posthog.com/project/7/experiments/421", 0.0),
    ],
    ids=["markdown-link", "tab-link", "no-link", "other-experiment"],
)
def test_experiment_url_in_report(message: str, expected_score: float) -> None:
    score = ExperimentUrlInReport()._run_eval_sync(_output(_create(), _text(message), last_message=message))
    assert score.score == expected_score


def test_experiment_url_skips_without_a_successful_create() -> None:
    output = _output(_create(failed=True), _text("I couldn't create it."), last_message="I couldn't create it.")
    assert ExperimentUrlInReport()._run_eval_sync(output).score is None


def test_experiment_url_falls_back_to_the_id_when_the_output_has_no_url() -> None:
    message = f"Draft ready: {EXPERIMENT_URL}"
    output = _output(_create("id: 42\nname: Homepage headline"), _text(message), last_message=message)
    score = ExperimentUrlInReport()._run_eval_sync(output)
    assert score.score == 1.0
    assert score.metadata["url_source"] == "experiment id"


def test_report_is_the_creation_turn_when_a_later_turn_only_acknowledges() -> None:
    report = f"Draft ready: {EXPERIMENT_URL}"
    output = _two_turn_output(
        [_create(), _text(report)],
        [_text("It's already created, nothing else to do.")],
        last_message="It's already created, nothing else to do.",
    )
    assert report_message(output) == report
    assert ExperimentUrlInReport()._run_eval_sync(output).score == 1.0


@pytest.mark.parametrize(
    "message,expected_score",
    [
        (f"Your flag: {FLAG_URL}", 1.0),
        ("Your flag: https://us.posthog.com/project/7/feature_flags/9", 1.0),
        ("Your flag: https://us.posthog.com/project/7/feature-flags/90", 0.0),
        ("Your flag is homepage-headline.", 0.0),
    ],
    ids=["flag-url", "legacy-path", "other-flag", "key-only"],
)
def test_flag_url_in_report(message: str, expected_score: float) -> None:
    output = _output(_create(), _text(message), last_message=message, seed={"team_id": 7})
    with patch.object(FlagUrlInReport, "_flag_ids", return_value={9}) as lookup:
        score = asyncio.run(FlagUrlInReport()._run_eval_async(output))
    assert score.score == expected_score
    lookup.assert_called_once_with(7, [42])


def test_flag_url_skips_without_a_successful_create() -> None:
    output = _output(_text("Nothing created."), last_message="Nothing created.", seed={"team_id": 7})
    assert asyncio.run(FlagUrlInReport()._run_eval_async(output)).score is None


def test_flag_url_fails_without_a_seeded_team() -> None:
    output = _output(_create(), _text(FLAG_URL), last_message=FLAG_URL)
    assert asyncio.run(FlagUrlInReport()._run_eval_async(output)).score == 0.0


def test_execute_sql_count_stops_at_the_first_create() -> None:
    output = _output(
        _tool("mcp__posthog__execute-sql", DISCOVERY_QUERY),
        _tool("mcp__posthog__execute-sql", SQL_QUERY),
        _tool("mcp__posthog__execute-sql", SQL_QUERY, failed=True),
        _tool("mcp__posthog__read-data-schema"),
        _create(),
        _tool("mcp__posthog__execute-sql", SQL_QUERY),
        last_message="done",
    )
    score = ExecuteSqlCallsBeforeCreate()._run_eval_sync(output)
    assert score.score is None
    assert score.result is not None and score.result.value == 3
    assert score.metadata["schema_discovery_calls"] == 1
    assert score.metadata["failed_execute_sql_calls"] == 1
    assert score.metadata["tool_calls_before_create"] == 4


def test_execute_sql_count_covers_the_whole_run_without_a_create() -> None:
    output = _output(_tool("mcp__posthog__execute-sql", SQL_QUERY), last_message="done")
    score = ExecuteSqlCallsBeforeCreate()._run_eval_sync(output)
    assert score.result is not None and score.result.value == 1
    assert score.metadata["created"] is False


@pytest.mark.parametrize(
    "message,expected_score",
    [
        ("PostHog's setup-context tool isn't enabled on this connection, so I ran my own queries.", 0.0),
        ("I couldn't read the setup context, so these are guesses.", 0.0),
        ("The Replay Vision tool is not available here.", 0.0),
        ("The feature flag isn't enabled until you launch. Then both variants go live.", 1.0),
        ("Your draft is ready, with a 50/50 split.", 1.0),
    ],
    ids=["roast-wording", "setup-context-spaced", "unavailable-tool", "flag-not-enabled", "clean"],
)
def test_no_unavailable_tool_mention(message: str, expected_score: float) -> None:
    score = NoUnavailableToolMention()._run_eval_sync(_output(_create(), _text(message), last_message=message))
    assert score.score == expected_score


@pytest.mark.parametrize(
    "reminder_input,expected_score",
    [
        ({"resource_type": "experiment", "resource_id": "42", "scheduled_at": "2026-11-04T09:00:00Z"}, 1.0),
        ({"resource_type": "experiment", "resource_id": 42}, 1.0),
        ({"resource_type": "feature_flag", "resource_id": "42"}, 0.0),
        ({"resource_type": "experiment", "resource_id": "7"}, 0.0),
        ({"name": "Check the experiment"}, 0.0),
    ],
    ids=["linked", "numeric-id", "wrong-type", "wrong-id", "unattached"],
)
def test_reminder_linked_to_experiment(reminder_input: dict[str, Any], expected_score: float) -> None:
    output = _output(_create(), _tool("mcp__posthog__reminder-create", reminder_input), last_message="Reminder set.")
    assert ReminderLinkedToExperiment()._run_eval_sync(output).score == expected_score


def test_reminder_skips_without_a_reminder() -> None:
    assert ReminderLinkedToExperiment()._run_eval_sync(_output(_create(), last_message="done")).score is None


def test_opening_keeps_the_first_turn_up_to_the_draft() -> None:
    question = {
        "questions": [
            {"question": "How should visitors be assigned?", "options": [{"label": "User ID"}, {"label": "Device ID"}]}
        ]
    }
    output = _two_turn_output(
        [
            _text("A variant is one version of the page."),
            _tool("AskUserQuestion", question, "cancelled", failed=True),
            _text("How should visitors be assigned: user ID or device ID?"),
        ],
        [_text("Creating the draft."), _create(), _text("Draft ready.")],
        last_message="Draft ready.",
    )
    opened = opening(output)
    assert "A variant is one version of the page." in opened.text
    assert "[Asked with the question tool: How should visitors be assigned? Options: User ID, Device ID]" in opened.text
    assert "user ID or device ID?" in opened.text
    assert "Creating the draft." not in opened.text
    assert "first turn" in opened.boundary


def test_opening_stops_at_the_create_call_in_a_single_turn() -> None:
    output = _output(_text("Here is the plan."), _create(), _text("Draft ready."), last_message="Draft ready.")
    opened = opening(output)
    assert opened.text == "Here is the plan."
    assert "creating the draft" in opened.boundary


@pytest.mark.parametrize(
    "expect_present,expected_score",
    [(True, 0.0), (False, 1.0)],
    ids=["newcomer-needs-a-primer", "existing-user-needs-none"],
)
def test_primer_short_circuits_when_the_agent_said_nothing_first(expect_present: bool, expected_score: float) -> None:
    output = _output(_create(), _text("Draft ready."), last_message="Draft ready.")
    prepared = NewcomerPrimerUpFront()._prepare(output, {"newcomer_primer_up_front": expect_present})
    assert isinstance(prepared, BraintrustScore)
    assert prepared.score == expected_score


def test_primer_skips_a_case_without_an_expectation() -> None:
    output = _output(_text("Hello."), _create(), last_message="Draft ready.")
    prepared = NewcomerPrimerUpFront()._prepare(output, {})
    assert isinstance(prepared, BraintrustScore)
    assert prepared.score is None


@pytest.mark.parametrize(
    "verdict_score,metadata,expect_present,expected_score",
    [
        (1.0, {"choice": "yes"}, True, 1.0),
        (1.0, {"choice": "yes"}, False, 0.0),
        (0.0, {"choice": "no"}, False, 1.0),
        (0.0, {"reason": "judge error: timeout"}, False, 0.0),
    ],
    ids=["present-as-expected", "present-but-unwanted", "absent-as-expected", "judge-error-stays-failed"],
)
def test_apply_expectation(
    verdict_score: float, metadata: dict[str, Any], expect_present: bool, expected_score: float
) -> None:
    verdict = BraintrustScore(name="low_traffic_note", score=verdict_score, metadata=metadata)
    assert apply_expectation(verdict, expect_present=expect_present).score == expected_score


def test_code_changes_section_skips_when_no_files_changed() -> None:
    output = _output(_create(), _text("Draft ready."), last_message="Draft ready.")
    prepared = CodeChangesSection()._prepare(output, {})
    assert isinstance(prepared, BraintrustScore)
    assert prepared.score is None


def test_code_changes_section_lists_the_changed_files_for_the_judge() -> None:
    output = _output(
        _tool("Edit", {"file_path": "src/pages/index.tsx", "old_string": "a", "new_string": "b"}),
        _tool("Edit", {"file_path": "src/pages/index.tsx", "old_string": "c", "new_string": "d"}),
        _tool("Write", {"file_path": "src/lib/headline.ts", "content": "x"}),
        _tool("Edit", {"file_path": "src/broken.ts"}, failed=True),
        _create(),
        _text("Draft ready."),
        last_message="Draft ready.",
    )
    prepared = CodeChangesSection()._prepare(output, {})
    assert isinstance(prepared, dict)
    assert prepared["output"]["files"] == "src/pages/index.tsx, src/lib/headline.ts"


def test_newcomer_visits_hold_about_ten_visitors_a_month() -> None:
    now = datetime(2026, 10, 27, 12, tzinfo=UTC)
    visits = newcomer_visits(now=now)
    assert visits == newcomer_visits(now=now)
    for window_start in range(0, 240, 30):
        in_window = [
            v
            for v in visits
            if now - timedelta(days=window_start + 30) <= v.started_at < now - timedelta(days=window_start)
        ]
        assert len(in_window) == 10


def test_newcomer_events_expose_the_aa_flag_only_once_the_test_started() -> None:
    now = datetime(2026, 10, 27, 12, tzinfo=UTC)
    aa_started_at = now - timedelta(days=NEWCOMER_AA_TEST_AGE_DAYS)
    for visit in newcomer_visits(now=now):
        events = newcomer_events(visit)
        exposures = [e for e in events if e.event == "$feature_flag_called"]
        if visit.started_at >= aa_started_at:
            assert [e.properties["$feature_flag"] for e in exposures] == [AA_TEST_FLAG_KEY]
        else:
            assert exposures == []
        assert next(e for e in events if e.event != "$feature_flag_called").properties["$pathname"] == "/"
        assert ("signed_up" in {e.event for e in events}) == visit.signed_up
