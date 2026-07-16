from __future__ import annotations

import json

import pytest

from braintrust_core.score import Score, Scorer

from products.posthog_ai.evals.cli_mcp.skill_distribution_scorers import (
    ExpectedSkillDiscovered,
    ExpectedSkillLoaded,
    NoBundledSkillBypass,
    NoExecSkillBypass,
    SkillLoadedBeforeTool,
    SkillSearchFirst,
    skill_distribution_expectations,
)

SKILL = "querying-posthog-data"
QUALIFIED_SKILL = f"posthog:{SKILL}"
EXEC_EXPECTED = skill_distribution_expectations(SKILL, ["execute-sql"], "exec")
BUNDLED_EXPECTED = skill_distribution_expectations(SKILL, ["execute-sql"], "bundled")


def _acp_line(update: dict) -> str:
    return json.dumps(
        {
            "notification": {"method": "session/update", "params": {"update": update}},
            "timestamp": "2026-01-01T00:00:00Z",
        }
    )


def _tool_call(call_id: str, tool_name: str, raw_input: dict, output: str = "ok", *, failed: bool = False) -> list[str]:
    return [
        _acp_line(
            {
                "sessionUpdate": "tool_call",
                "toolCallId": call_id,
                "_meta": {"claudeCode": {"toolName": tool_name}},
                "rawInput": raw_input,
            }
        ),
        _acp_line(
            {
                "sessionUpdate": "tool_call_update",
                "toolCallId": call_id,
                "status": "failed" if failed else "completed",
                "rawOutput": output,
            }
        ),
    ]


def _exec(call_id: str, command: str, output: str = "ok", *, failed: bool = False) -> list[str]:
    return _tool_call(call_id, "mcp__posthog__exec", {"command": command}, output, failed=failed)


def _output(*calls: list[str]) -> dict[str, object]:
    return {"raw_log": "\n".join(line for call in calls for line in call), "prompt": "analyze revenue"}


def _score(scorer: Scorer, output: dict[str, object], expected: dict[str, dict[str, object]] = EXEC_EXPECTED) -> Score:
    return scorer._run_eval_sync(output, expected=expected)


def _happy_path() -> dict[str, object]:
    return _output(
        _exec("search", 'learn -s "paid bill revenue by plan"', f'{{"name":"{QUALIFIED_SKILL}"}}'),
        _exec("load", f"learn {QUALIFIED_SKILL}", "# Querying data"),
        _exec("query", "call execute-sql {}", "[]"),
    )


@pytest.mark.parametrize(
    "scorer",
    [
        SkillSearchFirst(),
        ExpectedSkillDiscovered(),
        ExpectedSkillLoaded(),
        SkillLoadedBeforeTool(),
        NoBundledSkillBypass(),
    ],
)
def test_skill_distribution_scorers_accept_the_exec_distribution_path(scorer: Scorer) -> None:
    assert _score(scorer, _happy_path()).score == 1.0


@pytest.mark.parametrize(
    "earlier_call,expected_score",
    [
        (_exec("info", "info execute-sql"), 0.0),
        (_exec("failed-info", "info execute-sql", failed=True), 1.0),
        (_exec("guide", "learn analytics"), 1.0),
    ],
)
def test_skill_search_must_precede_successful_non_learning_exec_commands(
    earlier_call: list[str], expected_score: float
) -> None:
    output = _output(earlier_call, _exec("search", "learn -s revenue", QUALIFIED_SKILL))
    assert _score(SkillSearchFirst(), output).score == expected_score


def test_skill_search_must_not_be_parallelized_with_non_learning_exec_commands() -> None:
    search = _exec("search", "learn -s revenue", QUALIFIED_SKILL)
    data_call = _exec("data", 'call read-data-schema {"query":{"kind":"events"}}')
    output: dict[str, object] = {
        "raw_log": "\n".join([search[0], data_call[0], search[1], data_call[1]]),
        "prompt": "analyze revenue",
    }

    assert _score(SkillSearchFirst(), output).score == 0.0


@pytest.mark.parametrize(
    "output,scorer",
    [
        (_output(_exec("search", "learn -s revenue", "posthog:other-skill")), ExpectedSkillDiscovered()),
        (
            _output(_exec("search", "learn -s revenue", f"{QUALIFIED_SKILL}-extended")),
            ExpectedSkillDiscovered(),
        ),
        (
            _output(
                _exec("search", "learn -s revenue", "posthog:other-skill"),
                _exec("load", f"learn {QUALIFIED_SKILL}"),
            ),
            ExpectedSkillLoaded(),
        ),
        (
            _output(
                _exec("search", "learn -s revenue", QUALIFIED_SKILL),
                _exec("query", "call execute-sql {}"),
                _exec("load", f"learn {QUALIFIED_SKILL}"),
            ),
            SkillLoadedBeforeTool(),
        ),
    ],
)
def test_skill_distribution_scorers_reject_missing_discovery_or_wrong_order(
    output: dict[str, object], scorer: Scorer
) -> None:
    assert _score(scorer, output).score == 0.0


@pytest.mark.parametrize(
    "bypass_call,expected_score",
    [
        (_tool_call("native", "Skill", {"skill": "querying-posthog-data"}), 0.0),
        (
            _tool_call(
                "read",
                "Read",
                {"file_path": "/root/.claude/skills/querying-posthog-data/SKILL.md"},
            ),
            0.0,
        ),
        (_tool_call("failed-native", "Skill", {"skill": "querying-posthog-data"}, failed=True), 1.0),
    ],
)
def test_bundled_skill_bypass_counts_only_successful_calls(bypass_call: list[str], expected_score: float) -> None:
    assert _score(NoBundledSkillBypass(), _output(bypass_call)).score == expected_score


@pytest.mark.parametrize(
    "load_call",
    [
        _tool_call("native", "Skill", {"skill": SKILL}),
        _tool_call(
            "read",
            "Read",
            {"file_path": f"/root/.claude/skills/{SKILL}/SKILL.md"},
        ),
        _tool_call(
            "shell",
            "Bash",
            {"command": f"sed -n '1,200p' /root/.agents/skills/{SKILL}/SKILL.md"},
        ),
    ],
)
def test_bundled_distribution_accepts_native_skill_loading_paths(load_call: list[str]) -> None:
    output = _output(load_call, _exec("query", "call execute-sql {}", "[]"))

    for scorer in (ExpectedSkillLoaded(), SkillLoadedBeforeTool(), NoExecSkillBypass()):
        assert _score(scorer, output, BUNDLED_EXPECTED).score == 1.0


@pytest.mark.parametrize(
    "output,scorer",
    [
        (_output(_tool_call("wrong", "Skill", {"skill": "other-skill"})), ExpectedSkillLoaded()),
        (_output(_tool_call("failed", "Skill", {"skill": SKILL}, failed=True)), ExpectedSkillLoaded()),
        (
            _output(
                _exec("query", "call execute-sql {}", "[]"),
                _tool_call("native", "Skill", {"skill": SKILL}),
            ),
            SkillLoadedBeforeTool(),
        ),
    ],
)
def test_bundled_distribution_rejects_wrong_failed_or_late_skill_loads(
    output: dict[str, object], scorer: Scorer
) -> None:
    assert _score(scorer, output, BUNDLED_EXPECTED).score == 0.0


@pytest.mark.parametrize(
    "command,failed,expected_score",
    [
        ("learn -s revenue", False, 0.0),
        ("learn skills", False, 0.0),
        (f"learn {QUALIFIED_SKILL}", False, 0.0),
        ("learn project:team-retention", False, 0.0),
        ("learn analytics", False, 1.0),
        ("learn -s revenue", True, 1.0),
    ],
)
def test_exec_skill_bypass_counts_only_successful_distribution_commands(
    command: str, failed: bool, expected_score: float
) -> None:
    output = _output(_exec("learn", command, failed=failed))

    assert _score(NoExecSkillBypass(), output, BUNDLED_EXPECTED).score == expected_score


@pytest.mark.parametrize(
    "scorer,expected",
    [
        (SkillSearchFirst(), BUNDLED_EXPECTED),
        (ExpectedSkillDiscovered(), BUNDLED_EXPECTED),
        (NoBundledSkillBypass(), BUNDLED_EXPECTED),
        (NoExecSkillBypass(), EXEC_EXPECTED),
    ],
)
def test_delivery_specific_scorers_skip_the_other_arm(scorer: Scorer, expected: dict[str, dict[str, object]]) -> None:
    assert _score(scorer, _happy_path(), expected).score is None
