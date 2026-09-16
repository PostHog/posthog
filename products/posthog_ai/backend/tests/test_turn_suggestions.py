from datetime import date

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from parameterized import parameterized

from products.posthog_ai.backend.turn_suggestions.classifier import (
    NotebookDraft,
    ScoutCadence,
    ScoutDraft,
    TurnIntent,
    TurnVerdict,
    render_turn_prompt,
)
from products.posthog_ai.backend.turn_suggestions.service import (
    TURN_SUGGESTION_METHOD,
    TurnSuggestionOutcome,
    generate_turn_suggestion,
)
from products.posthog_ai.backend.turn_suggestions.transcript import build_turn_transcript
from products.tasks.backend.models import Task

SERVICE = "products.posthog_ai.backend.turn_suggestions.service"


def _notification(method: str, params: dict) -> dict:
    return {"type": "notification", "notification": {"method": method, "params": params}}


def _user_message(text: str) -> dict:
    return _notification("_posthog/user_message", {"content": text})


def _agent_text(text: str) -> dict:
    return _notification(
        "session/update",
        {"update": {"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": text}}},
    )


def _exec_tool_call(tool_call_id: str, command: str, status: str = "in_progress") -> dict:
    return _notification(
        "session/update",
        {
            "update": {
                "sessionUpdate": "tool_call",
                "toolCallId": tool_call_id,
                "title": "exec",
                "serverName": "posthog",
                "toolName": "exec",
                "status": status,
                "rawInput": {"command": command},
                "_meta": {"claudeCode": {"toolName": "mcp__posthog__exec"}},
            }
        },
    )


def _tool_call_update(tool_call_id: str, status: str, raw_input: dict | None = None) -> dict:
    update: dict = {"sessionUpdate": "tool_call_update", "toolCallId": tool_call_id, "status": status}
    if raw_input is not None:
        update["rawInput"] = raw_input
    return _notification("session/update", {"update": update})


def _metric_turn() -> list[dict]:
    return [
        _user_message(
            "<posthog_untrusted_context>\n- dashboard: 12\n</posthog_untrusted_context>\nHow many signups did we get this week?"
        ),
        _exec_tool_call(
            "t1", 'call --json query-trends {"series":[{"event":"signed_up"}],"dateRange":{"date_from":"-7d"}}'
        ),
        _tool_call_update("t1", "completed"),
        _agent_text("You had 412 signups this week, up 8% on last week."),
        _notification("_posthog/turn_complete", {"stopReason": "end_turn"}),
    ]


def _verdict(recurring: bool = True, intent: TurnIntent = TurnIntent.METRIC_STATE) -> TurnVerdict:
    return TurnVerdict(
        intent=intent,
        recurring=recurring,
        confidence=0.92,
        title="Get this every week in Slack",
        description="A scout can rerun this count each week and post the result.",
        scout=ScoutDraft(
            display_name="Weekly signups",
            description="Counts signed_up events for the last 7 days.",
            body="# Weekly signups\n\nQuery `signed_up` for the last 7 days...",
            cadence=ScoutCadence.WEEKLY,
        )
        if recurring
        else None,
        notebook=NotebookDraft(
            title="Why signups dropped on Tuesday", summary="A checkout error cut Tuesday's signups by a third."
        )
        if intent == TurnIntent.DIAGNOSTIC
        else None,
    )


class TestBuildTurnTranscript(SimpleTestCase):
    def test_resolves_exec_wrapped_tools_and_strips_context_blocks(self):
        transcript = build_turn_transcript(_metric_turn())

        assert transcript.human_messages == ("How many signups did we get this week?",)
        assert transcript.assistant_text == "You had 412 signups this week, up 8% on last week."
        assert [(call.name, call.status, call.from_posthog) for call in transcript.tool_calls] == [
            ("query-trends", "completed", True)
        ]
        assert transcript.tool_calls[0].args_preview.startswith('{"series"')

    @parameterized.expand(
        [
            ("discovery_verb", "search signups", None),
            ("flag_before_subtool", "call --confirm --json insight-create {}", "insight-create"),
            ("unknown_verb", "frobnicate x", "unknown"),
        ]
    )
    def test_exec_command_grammar(self, _name: str, command: str, expected_name: str | None):
        transcript = build_turn_transcript([_user_message("q"), _exec_tool_call("t1", command)])

        names = [call.name for call in transcript.tool_calls]
        assert names == ([] if expected_name is None else [expected_name])

    def test_exec_command_arriving_in_a_later_update_is_resolved(self):
        entries = [
            _user_message("q"),
            _notification(
                "session/update",
                {
                    "update": {
                        "sessionUpdate": "tool_call",
                        "toolCallId": "t1",
                        "serverName": "posthog",
                        "toolName": "exec",
                        "status": "pending",
                        "rawInput": {},
                    }
                },
            ),
            _tool_call_update("t1", "completed", {"command": 'call execute-sql {"query":"SELECT 1"}'}),
        ]

        transcript = build_turn_transcript(entries)

        assert [(call.name, call.status) for call in transcript.tool_calls] == [("execute-sql", "completed")]

    def test_only_the_turn_after_the_last_user_message_is_kept(self):
        entries = [
            *_metric_turn(),
            _user_message("Why did it drop on Tuesday?"),
            _exec_tool_call("t2", "call query-session-recordings-list {}", status="completed"),
            _agent_text("Tuesday's drop lines up with a checkout error."),
        ]

        transcript = build_turn_transcript(entries)

        assert len(transcript.human_messages) == 2
        assert transcript.last_human_message == "Why did it drop on Tuesday?"
        assert [call.name for call in transcript.tool_calls] == ["query-session-recordings-list"]
        assert transcript.assistant_text == "Tuesday's drop lines up with a checkout error."

    def test_session_prompt_counts_turns_when_no_user_message_frames_exist(self):
        entries = [
            _notification("session/prompt", {"prompt": [{"type": "text", "text": "How many users today?"}]}),
            _agent_text("120."),
        ]

        transcript = build_turn_transcript(entries)

        assert transcript.human_messages == ("How many users today?",)

    def test_prompt_rendering_lists_resolved_tools(self):
        prompt = render_turn_prompt(build_turn_transcript(_metric_turn()), today=date(2026, 9, 16))

        assert "How many signups did we get this week?" in prompt
        assert "- query-trends [completed]: " in prompt
        assert "posthog_untrusted_context" not in prompt


class TestGenerateTurnSuggestion(BaseTest):
    def setUp(self):
        super().setUp()
        task = Task.objects.create(
            team=self.team,
            title="t",
            description="d",
            origin_product=Task.OriginProduct.POSTHOG_AI,
            created_by=self.user,
        )
        self.task_run = task.create_run(mode="interactive")

        self.stream = patch(f"{SERVICE}.read_task_run_stream_entries", return_value=_metric_turn())
        self.publish = patch(f"{SERVICE}.publish_task_run_stream_notification", return_value=True)
        self.classify = patch(f"{SERVICE}.classify_turn", return_value=_verdict())
        self.scouts = patch(f"{SERVICE}.scout_creation_available", return_value=True)
        self.flag = patch(f"{SERVICE}.feature_enabled_or_false", return_value=True)
        self.capture = patch(f"{SERVICE}.ph_scoped_capture")
        self.redis = patch(f"{SERVICE}.get_client", return_value=MagicMock(set=MagicMock(return_value=True)))
        self.mocks = {
            name: patcher.start()
            for name, patcher in {
                "stream": self.stream,
                "publish": self.publish,
                "classify": self.classify,
                "scouts": self.scouts,
                "flag": self.flag,
                "capture": self.capture,
                "redis": self.redis,
            }.items()
        }
        for patcher in (self.stream, self.publish, self.classify, self.scouts, self.flag, self.capture, self.redis):
            self.addCleanup(patcher.stop)

    def test_publishes_a_scout_suggestion_for_a_recurring_first_turn(self):
        outcome = generate_turn_suggestion(str(self.task_run.id))

        assert outcome.status == "emitted"
        run_id, method, params = self.mocks["publish"].call_args.args
        assert run_id == str(self.task_run.id)
        assert method == TURN_SUGGESTION_METHOD
        assert params["turnIndex"] == 0
        assert params["kind"] == "scout"
        assert params["scout"] == {
            "displayName": "Weekly signups",
            "description": "Counts signed_up events for the last 7 days.",
            "body": "# Weekly signups\n\nQuery `signed_up` for the last 7 days...",
            "cadence": "weekly",
        }
        transcript = self.mocks["classify"].call_args.args[0]
        assert transcript.last_human_message == "How many signups did we get this week?"

    def test_diagnostic_verdict_publishes_a_notebook_suggestion(self):
        self.mocks["classify"].return_value = _verdict(recurring=False, intent=TurnIntent.DIAGNOSTIC)

        outcome = generate_turn_suggestion(str(self.task_run.id))

        assert outcome == TurnSuggestionOutcome(status="emitted", reason="notebook")
        _, _, params = self.mocks["publish"].call_args.args
        assert params["kind"] == "notebook"
        assert "scout" not in params
        assert params["notebook"] == {
            "title": "Why signups dropped on Tuesday",
            "summary": "A checkout error cut Tuesday's signups by a third.",
        }

    def test_diagnostic_turn_without_tool_calls_is_not_offered_a_notebook(self):
        self.mocks["classify"].return_value = _verdict(recurring=False, intent=TurnIntent.DIAGNOSTIC)
        self.mocks["stream"].return_value = [_user_message("Why did signups drop?"), _agent_text("Hard to say.")]

        outcome = generate_turn_suggestion(str(self.task_run.id))

        assert outcome.reason == "no_offer:diagnostic"
        self.mocks["publish"].assert_not_called()

    def test_verdict_without_an_offer_is_recorded_but_not_published(self):
        self.mocks["classify"].return_value = _verdict(recurring=False, intent=TurnIntent.KNOWLEDGE)

        outcome = generate_turn_suggestion(str(self.task_run.id))

        assert outcome.status == "skipped"
        assert outcome.reason == "no_offer:knowledge"
        self.mocks["publish"].assert_not_called()
        capture = self.mocks["capture"].return_value.__enter__.return_value
        assert capture.call_args.kwargs["properties"]["emitted"] is False
        assert capture.call_args.kwargs["properties"]["offer"] is None

    def test_follow_up_turns_never_reach_the_classifier(self):
        self.mocks["stream"].return_value = [*_metric_turn(), _user_message("And last month?"), _agent_text("1,600.")]

        outcome = generate_turn_suggestion(str(self.task_run.id))

        assert outcome.reason == "not_first_turn"
        self.mocks["classify"].assert_not_called()
        self.mocks["publish"].assert_not_called()

    @parameterized.expand([("scouts", "scouts_unavailable"), ("flag", "flag_off")])
    def test_unavailable_target_or_flag_skips_before_classifying(self, gate: str, reason: str):
        self.mocks[gate].return_value = False

        outcome = generate_turn_suggestion(str(self.task_run.id))

        assert outcome.reason == reason
        self.mocks["classify"].assert_not_called()

    def test_second_report_of_the_same_turn_is_deduplicated(self):
        self.mocks["redis"].return_value.set.return_value = False

        outcome = generate_turn_suggestion(str(self.task_run.id))

        assert outcome.reason == "already_classified"
        self.mocks["classify"].assert_not_called()
