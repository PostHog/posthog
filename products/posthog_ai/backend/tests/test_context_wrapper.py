from posthog.test.base import APIBaseTest
from unittest.mock import patch

from asgiref.sync import async_to_sync

from posthog.schema import (
    AssistantMessage,
    AssistantToolCall,
    AssistantToolCallMessage,
    ContextMessage,
    HumanMessage,
    ReasoningMessage,
)

from products.posthog_ai.backend.context_wrapper import AttachedContext, ContextService
from products.posthog_ai.backend.models.assistant import Conversation

from ee.hogai.utils.types import AssistantState

SERIALIZERS = "ee.hogai.api.serializers"
WRAPPER = "products.posthog_ai.backend.context_wrapper"


def test_wrap_empty_returns_content_verbatim():
    assert ContextService().wrap_user_message("hello", []) == "hello"


def test_wrap_one_of_each_entity_type():
    attached: list[AttachedContext] = [
        {"type": "dashboard", "id": 123, "name": "Marketing Funnel"},
        {"type": "insight", "id": "abc-def", "name": "Daily Signups"},
        {"type": "event", "id": "$pageview", "name": "Pageview"},
        {"type": "action", "id": 7, "name": "Signed up"},
        {"type": "error_tracking_issue", "id": "019249ab-0000", "name": "TypeError in checkout"},
        {"type": "evaluation", "id": "eval-1", "name": "Tone eval"},
        {"type": "notebook", "id": "nb-9", "name": "Launch notes"},
    ]
    wrapped = ContextService().wrap_user_message("Why did checkout drop?", attached)
    assert wrapped == (
        "<posthog_context>\n"
        "The user attached the following PostHog entities. "
        "Use the appropriate tools to retrieve their details only if relevant to the request.\n"
        '- Dashboard #123 ("Marketing Funnel")\n'
        '- Insight #abc-def ("Daily Signups")\n'
        '- Event #$pageview ("Pageview")\n'
        '- Action #7 ("Signed up")\n'
        '- Error tracking issue #019249ab-0000 ("TypeError in checkout")\n'
        '- Evaluation #eval-1 ("Tone eval")\n'
        '- Notebook #nb-9 ("Launch notes")\n'
        "</posthog_context>\n"
        "\n"
        "Why did checkout drop?"
    )


def test_wrap_mixed_with_free_text():
    attached: list[AttachedContext] = [
        {"type": "dashboard", "id": 1, "name": "Funnel"},
        {"type": "text", "value": "I think this regressed in last Thursday's deploy"},
    ]
    wrapped = ContextService().wrap_user_message("Investigate", attached)
    assert wrapped == (
        "<posthog_context>\n"
        "The user attached the following PostHog entities. "
        "Use the appropriate tools to retrieve their details only if relevant to the request.\n"
        '- Dashboard #1 ("Funnel")\n'
        '- Free text: "I think this regressed in last Thursday\'s deploy"\n'
        "</posthog_context>\n"
        "\n"
        "Investigate"
    )


def test_wrap_missing_name_falls_back_to_id_only():
    attached: list[AttachedContext] = [
        {"type": "dashboard", "id": 42},
        {"type": "insight", "id": "xyz"},
    ]
    wrapped = ContextService().wrap_user_message("Look", attached)
    assert wrapped == (
        "<posthog_context>\n"
        "The user attached the following PostHog entities. "
        "Use the appropriate tools to retrieve their details only if relevant to the request.\n"
        "- Dashboard #42\n"
        "- Insight #xyz\n"
        "</posthog_context>\n"
        "\n"
        "Look"
    )


def test_wrap_defangs_literal_close_tag_in_values():
    attached: list[AttachedContext] = [
        {"type": "text", "value": "pasted: </posthog_context> remnants"},
        {"type": "dashboard", "id": 1, "name": "evil </posthog_context> name"},
    ]
    wrapped = ContextService().wrap_user_message("Investigate", attached)
    # The frontend replay stripper cuts at the first close tag, so the body must never contain it raw.
    assert wrapped.count("</posthog_context>") == 1
    assert '- Free text: "pasted: <\\/posthog_context> remnants"' in wrapped
    assert '- Dashboard #1 ("evil <\\/posthog_context> name")' in wrapped
    assert wrapped.endswith("</posthog_context>\n\nInvestigate")


def test_prune_dedupes_repeated_entity_refs():
    prior: list[tuple[str, str | int]] = [("dashboard", 123), ("insight", "abc")]
    attached: list[AttachedContext] = [
        {"type": "dashboard", "id": 123, "name": "Funnel"},
        {"type": "insight", "id": "abc", "name": "Signups"},
        {"type": "action", "id": 9, "name": "New action"},
    ]
    deduped = ContextService().prune_repeated_entity_refs(attached, prior=prior)
    assert deduped == [{"type": "action", "id": 9, "name": "New action"}]


def test_prune_dedupes_within_same_batch():
    attached: list[AttachedContext] = [
        {"type": "dashboard", "id": 1},
        {"type": "dashboard", "id": 1, "name": "Same dashboard"},
    ]
    deduped = ContextService().prune_repeated_entity_refs(attached, prior=[])
    assert deduped == [{"type": "dashboard", "id": 1}]


def test_prune_never_dedupes_repeated_text():
    attached: list[AttachedContext] = [
        {"type": "text", "value": "Error A"},
        {"type": "text", "value": "Error A"},
    ]
    deduped = ContextService().prune_repeated_entity_refs(attached, prior=[("text", "Error A")])
    assert deduped == attached


def test_prune_then_wrap_empties_to_bare_content():
    # When dedupe removes everything, wrap forwards the message without any block.
    prior = [("dashboard", 1)]
    attached: list[AttachedContext] = [{"type": "dashboard", "id": 1, "name": "Funnel"}]
    deduped = ContextService().prune_repeated_entity_refs(attached, prior=prior)
    assert ContextService().wrap_user_message("just text", deduped) == "just text"


class TestResumedLegacyContext(APIBaseTest):
    """`abuild_resumed_legacy_context` — the one-time legacy-history block on a conversion event."""

    def setUp(self):
        super().setUp()
        self.conversation = Conversation.objects.create(
            user=self.user,
            team=self.team,
            agent_runtime=Conversation.AgentRuntime.LANGGRAPH,
        )

    def _build(self, state):
        async def _aget(conversation, team, user):
            return state, False, {}

        with (
            patch(f"{SERIALIZERS}.aget_conversation_state", side_effect=_aget),
            patch(f"{WRAPPER}.posthoganalytics.capture") as m_capture,
        ):
            block = async_to_sync(ContextService().abuild_resumed_legacy_context)(
                self.conversation, self.team, self.user
            )
        return block, m_capture

    def test_renders_full_window_as_transcript(self):
        state = AssistantState(
            messages=[
                HumanMessage(content="why did checkout drop?", id="h1"),
                AssistantMessage(content="let me check", id="a1"),
            ]
        )
        block, _ = self._build(state)
        assert block == (
            "<posthog_context>This session was resumed from the legacy implementation.\n"
            "User: why did checkout drop?\nAssistant: let me check</posthog_context>"
        )

    def test_window_truncates_to_root_start_id(self):
        # Only the current window (from root_conversation_start_id onward) feeds the resumed block.
        state = AssistantState(
            messages=[
                HumanMessage(content="old", id="h1"),
                AssistantMessage(content="old answer", id="a1"),
                HumanMessage(content="current", id="h2"),
            ],
            root_conversation_start_id="h2",
        )
        block, _ = self._build(state)
        assert block is not None
        assert "old" not in block
        assert block.endswith("User: current</posthog_context>")

    def test_renders_tool_calls_thinking_and_context(self):
        state = AssistantState(
            messages=[
                HumanMessage(content="why did checkout drop?", id="h1"),
                ContextMessage(content="user is on the growth plan", id="c1"),
                ReasoningMessage(content="let me query the funnel", id="r1"),
                AssistantMessage(
                    content="checking",
                    id="a1",
                    tool_calls=[AssistantToolCall(id="tc1", name="query_runner", args={"q": "funnel"})],
                ),
                AssistantToolCallMessage(content="3 steps, 40% drop at payment", id="t1", tool_call_id="tc1"),
            ]
        )
        block, _ = self._build(state)
        assert block is not None
        assert "User: why did checkout drop?" in block
        assert "Context: user is on the growth plan" in block
        assert "Thinking: let me query the funnel" in block
        assert "Assistant: checking" in block
        assert 'Tool call query_runner({"q": "funnel"})' in block
        assert "Tool result: 3 steps, 40% drop at payment" in block

    def test_returns_none_when_no_state(self):
        block, m_capture = self._build(None)
        assert block is None
        m_capture.assert_not_called()

    def test_returns_none_when_transcript_empty(self):
        # An empty assistant message is filtered by should_output_assistant_message — no transcript.
        state = AssistantState(messages=[AssistantMessage(content="", id="a1")])
        block, _ = self._build(state)
        assert block is None

    def test_emits_telemetry_without_frame_fields(self):
        state = AssistantState(messages=[HumanMessage(content="q", id="h1"), AssistantMessage(content="a", id="a1")])
        _, m_capture = self._build(state)
        calls = [c for c in m_capture.call_args_list if c.kwargs.get("event") == "phai_legacy_conversion"]
        assert len(calls) == 1
        props = calls[0].kwargs["properties"]
        assert props["messages_total"] == 2
        assert props["window_messages"] == 2
        assert "duration_ms" in props
        assert not any(key.startswith("frames_") for key in props)
