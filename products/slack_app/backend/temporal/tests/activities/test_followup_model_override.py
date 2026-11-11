"""Tests for the model switch a follow-up can ask a run for.

The precedence rules themselves live in
``products/slack_app/backend/tests/services/test_run_preferences.py``. What is
covered here is what the follow-up path does with the answer: which asks reach the
agent server, which are refused in the thread, and what a resumed run is pinned to.
"""

from types import SimpleNamespace

import pytest
from unittest.mock import MagicMock, patch

from products.slack_app.backend.services.model_catalogue import ModelChoice
from products.slack_app.backend.services.slack_settings import AIPreferences
from products.slack_app.backend.temporal.activities.task_creation import (
    _apply_followup_model_override,
    _run_preference_state,
    _stop_run_for_runtime_handoff,
)
from products.slack_app.backend.temporal.types import SlackAppModelOverride

CATALOGUE = (
    ModelChoice("claude", "claude-sonnet-4-6", "Claude Sonnet 4.6", ("low", "medium", "high")),
    ModelChoice("claude", "claude-fable-5", "Claude Fable 5", ("low", "medium", "high", "xhigh", "max")),
    ModelChoice("codex", "gpt-5.6-sol", "GPT-5.6 Sol", ("low", "medium", "high", "xhigh", "max")),
)

RUNNING_STATE = {"runtime_adapter": "claude", "model": "claude-sonnet-4-6", "reasoning_effort": "medium"}


@pytest.fixture
def catalogue():
    with patch(
        "products.slack_app.backend.services.run_preferences.available_model_choices",
        return_value=CATALOGUE,
    ):
        yield


@pytest.fixture
def apply_config():
    with patch("products.tasks.backend.facade.api.apply_task_run_model_config", return_value=True) as mock:
        yield mock


def _run(state=None):
    return SimpleNamespace(
        id="run-1", task_id="task-1", team_id=7, state=state if state is not None else dict(RUNNING_STATE)
    )


def _slack():
    return SimpleNamespace(client=MagicMock())


def _posted_text(slack) -> str:
    return slack.client.chat_postMessage.call_args.kwargs["text"]


class TestApplyFollowupModelOverride:
    @pytest.mark.parametrize("applied", [True, False], ids=["agent_server_accepts", "agent_server_refuses"])
    def test_switches_the_running_agent_without_announcing_it(self, catalogue, apply_config, applied):
        """The footer under the next reply reads the model back out of the run's state,
        so a switch that lands needs no line of its own, and one that doesn't must not
        claim otherwise."""
        apply_config.return_value = applied
        slack = _slack()
        _apply_followup_model_override(
            slack,
            "C1",
            "111.1",
            task_run=_run(),
            task_id="task-1",
            override=SlackAppModelOverride(model="claude-fable-5", reasoning_effort="xhigh"),
            actor_user=SimpleNamespace(id=42),
        )
        assert apply_config.call_args.kwargs == {
            "model": "claude-fable-5",
            "reasoning_effort": "xhigh",
            "actor_user_id": 42,
        }
        slack.client.chat_postMessage.assert_not_called()

    def test_refuses_a_model_from_the_other_runtime_without_touching_the_run(self, catalogue, apply_config):
        """The harness is the process the sandbox started with, so this one can only be
        answered — and it has to be, or the author is left thinking it was honoured."""
        slack = _slack()
        _apply_followup_model_override(
            slack,
            "C1",
            "111.1",
            task_run=_run(),
            task_id="task-1",
            override=SlackAppModelOverride(model="gpt-5.6-sol"),
            actor_user=SimpleNamespace(id=42),
        )
        apply_config.assert_not_called()
        assert "*GPT-5.6 Sol*" in _posted_text(slack)

    @pytest.mark.parametrize(
        "override",
        [
            None,
            SlackAppModelOverride(model="claude-sonnet-4-6", reasoning_effort="medium"),
        ],
        ids=["no_request", "already_on_it"],
    )
    def test_stays_quiet_when_nothing_changes(self, catalogue, apply_config, override):
        slack = _slack()
        _apply_followup_model_override(
            slack,
            "C1",
            "111.1",
            task_run=_run(),
            task_id="task-1",
            override=override,
            actor_user=SimpleNamespace(id=42),
        )
        apply_config.assert_not_called()
        slack.client.chat_postMessage.assert_not_called()


class TestStopRunForRuntimeHandoff:
    @pytest.mark.parametrize(
        "override,flag_enabled,cancel_outcome,expected,captured_outcome",
        [
            (SlackAppModelOverride(model="gpt-5.6-sol"), True, "accepted", True, None),
            (SlackAppModelOverride(model="gpt-5.6-sol"), True, "already_terminal", True, None),
            (SlackAppModelOverride(model="gpt-5.6-sol"), True, "unavailable", False, "stop_failed"),
            (SlackAppModelOverride(model="gpt-5.6-sol"), False, "accepted", False, "flag_off"),
            (SlackAppModelOverride(model="claude-fable-5"), True, "accepted", False, None),
            (SlackAppModelOverride(reasoning_effort="high"), True, "accepted", False, None),
        ],
        ids=[
            "stopped",
            "already_finished",
            "workflow_unreachable",
            "flag_off",
            "same_runtime",
            "effort_only",
        ],
    )
    def test_hands_off_only_when_the_live_run_is_stopped(
        self, catalogue, override, flag_enabled, cancel_outcome, expected, captured_outcome
    ):
        slack = _slack()
        with (
            patch(
                "products.slack_app.backend.feature_flags.is_slack_app_runtime_handoff_enabled",
                return_value=flag_enabled,
            ),
            patch(
                "products.tasks.backend.facade.cancellation.cancel_task_run",
                return_value=(cancel_outcome, None),
            ) as cancel,
            patch("products.slack_app.backend.analytics.capture_slack_event") as capture,
        ):
            handed_off = _stop_run_for_runtime_handoff(
                MagicMock(),
                slack,
                "C1",
                "111.1",
                task_run=_run(),
                override=override,
                actor_user=SimpleNamespace(id=42, distinct_id="user-42"),
                slack_user_id="U1",
            )

        assert bool(handed_off) is expected
        assert [c.kwargs["outcome"] for c in capture.call_args_list] == ([captured_outcome] if captured_outcome else [])
        if expected:
            assert cancel.call_args.kwargs["source"] == "slack_runtime_handoff"
            assert "*GPT-5.6 Sol*" in _posted_text(slack)
        else:
            slack.client.chat_postMessage.assert_not_called()


class TestRunPreferenceState:
    @pytest.mark.parametrize(
        "prefs,expected",
        [
            (
                AIPreferences(runtime_adapter="codex", model="gpt-5.6-sol", reasoning_effort="high"),
                {
                    "runtime_adapter": "codex",
                    "provider": "openai",
                    "model": "gpt-5.6-sol",
                    "reasoning_effort": "high",
                },
            ),
            # What was never resolved is left out rather than written as None, so the
            # agent server keeps its own default for it.
            (
                AIPreferences(runtime_adapter="claude", model="claude-fable-5", reasoning_effort=None),
                {"runtime_adapter": "claude", "provider": "anthropic", "model": "claude-fable-5"},
            ),
        ],
        ids=["full_triple", "no_effort_resolved"],
    )
    def test_pins_the_successor_run_to_what_resolved(self, prefs, expected):
        """A run created straight off a task writes these itself — without them the new
        sandbox falls back to whatever the agent server defaults to."""
        with patch(
            "products.slack_app.backend.facade.run_preferences.resolve_run_preferences",
            return_value=prefs,
        ):
            state = _run_preference_state(model_override=None)
        assert state == expected
