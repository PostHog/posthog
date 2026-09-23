import json
from dataclasses import replace
from datetime import date
from typing import Any

from posthog.test.base import APIBaseTest, BaseTest
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

import requests
from parameterized import parameterized

from posthog.egress.typesafe import ChoiceAnswer, NoulAnswer, SystemOneAnswers, TypeSafeRequestFailed

from products.posthog_ai.backend.turn_suggestions.benchmark import (
    BenchmarkCase,
    CaseResult,
    best_threshold,
    load_cases,
    score,
)
from products.posthog_ai.backend.turn_suggestions.classifier import classify_turn, pick_offer
from products.posthog_ai.backend.turn_suggestions.dispatch import enqueue_turn_suggestion
from products.posthog_ai.backend.turn_suggestions.drafter import DRAFT_MODEL, draft_scout, render_turn_prompt
from products.posthog_ai.backend.turn_suggestions.judgment import (
    TurnJudgment,
    build_judge_questions,
    build_judge_state,
    judge_turn,
)
from products.posthog_ai.backend.turn_suggestions.offer_ledger import STATE_KEY, OfferRecord, OfferStatus, read_ledger
from products.posthog_ai.backend.turn_suggestions.service import (
    TURN_SUGGESTION_METHOD,
    TurnSuggestionOutcome,
    generate_turn_suggestion,
)
from products.posthog_ai.backend.turn_suggestions.transcript import (
    ErrorIssueRef,
    SavedInsightRef,
    build_turn_transcript,
    redact_values,
)
from products.posthog_ai.backend.turn_suggestions.verdict import (
    AlertDirection,
    AlertDraft,
    Draft,
    ErrorAlertDraft,
    IncidentOutline,
    NotebookDraft,
    NotebookTemplate,
    OfferKind,
    ScoutCadence,
    ScoutDraft,
    ScoutMode,
    SubscriptionDraft,
    TurnIntent,
    TurnVerdict,
)
from products.tasks.backend.facade.api import TaskClientProvenance
from products.tasks.backend.models import Task

SERVICE = "products.posthog_ai.backend.turn_suggestions.service"


def _offer(turn_index: int, *, run_id: str = "run-1") -> dict:
    return {"turn_index": turn_index, "run_id": run_id, "kind": "scout", "status": "offered"}


ALL_OFFERS = frozenset(OfferKind) - {OfferKind.NONE}


def _notification(method: str, params: dict) -> dict:
    return {"type": "notification", "notification": {"method": method, "params": params}}


def _user_message(text: str) -> dict:
    return _notification("_posthog/user_message", {"content": text})


def _agent_text(text: str) -> dict:
    return _notification(
        "session/update",
        {"update": {"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": text}}},
    )


def _agent_final(text: str, message_id: str | None = "m1") -> dict:
    update: dict = {"sessionUpdate": "agent_message", "content": {"type": "text", "text": text}}
    if message_id is not None:
        update["messageId"] = message_id
    return _notification("session/update", {"update": update})


def _builtin_tool_call(tool_call_id: str, tool_name: str, raw_input: dict) -> dict:
    return _notification(
        "session/update",
        {
            "update": {
                "sessionUpdate": "tool_call",
                "toolCallId": tool_call_id,
                "title": tool_name,
                "status": "completed",
                "rawInput": raw_input,
                "_meta": {"claudeCode": {"toolName": tool_name}},
            }
        },
    )


def _exec_tool_call(tool_call_id: str, command: str, status: str = "in_progress", output: dict | None = None) -> dict:
    update: dict = {
        "sessionUpdate": "tool_call",
        "toolCallId": tool_call_id,
        "title": "exec",
        "serverName": "posthog",
        "toolName": "exec",
        "status": status,
        "rawInput": {"command": command},
        "_meta": {"claudeCode": {"toolName": "mcp__posthog__exec"}},
    }
    if output is not None:
        update["rawOutput"] = output
    return _notification("session/update", {"update": update})


def _tool_call_update(
    tool_call_id: str, status: str, raw_input: dict | None = None, output: dict | None = None
) -> dict:
    update: dict = {"sessionUpdate": "tool_call_update", "toolCallId": tool_call_id, "status": status}
    if raw_input is not None:
        update["rawInput"] = raw_input
    if output is not None:
        update["rawOutput"] = output
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


SAVED_INSIGHT = SavedInsightRef(short_id="abc123", insight_id=42, name="Signups", query_kind="TrendsQuery")
ERROR_ISSUE = ErrorIssueRef(issue_id="0199c0de-1111-7000-8000-0000000000aa", name="Checkout error")


def _saved_insight_turn(query_kind: str = "TrendsQuery") -> list[dict]:
    return [
        _user_message("How many signups did we get this week? Save it."),
        _exec_tool_call(
            "t1",
            'call insight-create {"name":"Signups"}',
            "completed",
            {"id": 42, "short_id": "abc123", "name": "Signups", "query": {"kind": query_kind, "series": []}},
        ),
        _agent_text("Saved. You had 412 signups this week."),
    ]


def _error_turn() -> list[dict]:
    return [
        _user_message("Why did checkout break on Tuesday?"),
        _exec_tool_call(
            "t1",
            "call query-error-tracking-issues-list {}",
            "completed",
            {"results": [{"id": ERROR_ISSUE.issue_id, "name": "Checkout error"}], "hasMore": False},
        ),
        _agent_text("A checkout error started at 14:10."),
    ]


_DRAFTS: dict[OfferKind, Draft] = {
    OfferKind.SCOUT: ScoutDraft(
        mode=ScoutMode.REPORT,
        display_name="Weekly signups",
        description="Counts signed_up events for the last 7 days.",
        body="# Weekly signups\n\nQuery `signed_up` for the last 7 days...",
        cadence=ScoutCadence.WEEKLY,
    ),
    OfferKind.NOTEBOOK: NotebookDraft(
        title="Why signups dropped on Tuesday",
        summary="A checkout error cut Tuesday's signups by a third.",
        incident=IncidentOutline(timeline="- 14:10 release", cause="Checkout error.", fix="Rolled back."),
    ),
    OfferKind.ALERT: AlertDraft(insight=SAVED_INSIGHT, direction=AlertDirection.DECREASE, change_percent=20),
    OfferKind.SUBSCRIPTION: SubscriptionDraft(insight=SAVED_INSIGHT, cadence=ScoutCadence.WEEKLY),
    OfferKind.ERROR_ALERT: ErrorAlertDraft(issue=ERROR_ISSUE),
}


def _verdict(offer: OfferKind = OfferKind.SCOUT, intent: TurnIntent = TurnIntent.METRIC_STATE) -> TurnVerdict:
    return TurnVerdict(
        intent=intent,
        show_probability=0.92,
        picked=offer,
        offer_probabilities={offer.value: 0.8},
        title="Get this in Slack every week",
        description="A scout runs this analysis again every week and posts the results to Slack.",
        draft=_DRAFTS.get(offer),
    )


class TestBuildTurnTranscript(SimpleTestCase):
    def test_resolves_exec_wrapped_tools_and_strips_context_blocks(self):
        transcript = build_turn_transcript(_metric_turn())

        assert transcript.human_messages == ("How many signups did we get this week?",)
        assert transcript.assistant_text == "You had 412 signups this week, up 8% on last week."
        assert [(call.name, call.status, call.from_posthog) for call in transcript.tool_calls] == [
            ("query-trends", "completed", True)
        ]
        assert '"series"' in transcript.tool_calls[0].args_preview

    @parameterized.expand(
        [
            ("discovery_verb", "search signups", None),
            ("info_verb", "info insight-create", None),
            ("flag_before_subtool", "call --confirm --no-skills insight-create {}", "insight-create"),
            ("unknown_verb", "frobnicate x", None),
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

    @parameterized.expand(
        [
            ("ids_on_both", "m1", "m1"),
            ("id_only_on_chunks", "m1", None),
            ("id_only_on_final", None, "m1"),
            ("no_ids", None, None),
        ]
    )
    def test_a_closing_agent_message_replaces_its_streamed_chunks(
        self, _name: str, chunk_message_id: str | None, final_message_id: str | None
    ):
        def chunk(text: str) -> dict:
            update: dict = {"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": text}}
            if chunk_message_id is not None:
                update["messageId"] = chunk_message_id
            return _notification("session/update", {"update": update})

        entries = [
            _user_message("q"),
            chunk("You had 412 "),
            chunk("signups."),
            _agent_final("You had 412 signups.", final_message_id),
        ]

        transcript = build_turn_transcript(entries)

        assert transcript.assistant_text == "You had 412 signups."

    def test_builtin_tools_keep_their_name_and_a_preview_of_their_input(self):
        entries = [_user_message("q"), _builtin_tool_call("t1", "Bash", {"command": "ls -la", "timeout": 5})]

        transcript = build_turn_transcript(entries)

        assert [(call.name, call.args_preview, call.from_posthog) for call in transcript.tool_calls] == [
            ("Bash", "ls -la", False)
        ]

    def test_earlier_turns_are_kept_as_context_and_only_the_last_turn_is_folded(self):
        entries = [
            *_metric_turn(),
            _user_message("Why did it drop on Tuesday?"),
            _exec_tool_call("t2", "call query-session-recordings-list {}", status="completed"),
            _agent_text("Tuesday's drop lines up with a checkout error."),
        ]

        transcript = build_turn_transcript(entries)

        assert transcript.last_human_message == "Why did it drop on Tuesday?"
        assert [call.name for call in transcript.tool_calls] == ["query-session-recordings-list"]
        assert transcript.assistant_text == "Tuesday's drop lines up with a checkout error."
        assert [(turn.question, turn.tool_names, turn.answer_excerpt) for turn in transcript.earlier_turns] == [
            (
                "How many signups did we get this week?",
                ("query-trends",),
                "You had 412 signups this week, up 8% on last week.",
            )
        ]

    def test_saved_insights_and_error_issues_come_from_the_tool_payloads(self):
        assert build_turn_transcript(_saved_insight_turn()).saved_insights == (SAVED_INSIGHT,)
        assert build_turn_transcript(_error_turn()).error_issues == (ERROR_ISSUE,)
        assert build_turn_transcript(_metric_turn()).saved_insights == ()

    def test_session_prompt_counts_turns_when_no_user_message_frames_exist(self):
        entries = [
            _notification("session/prompt", {"prompt": [{"type": "text", "text": "How many users today?"}]}),
            _agent_text("120."),
        ]

        transcript = build_turn_transcript(entries)

        assert transcript.human_messages == ("How many users today?",)

    def test_prompt_carries_the_instruction_context_and_resolved_tools(self):
        entries = [*_saved_insight_turn(), _user_message("Break that down by country"), _agent_text("Mostly the US.")]

        prompt = render_turn_prompt(
            build_turn_transcript(entries), today=date(2026, 9, 16), instruction="Layout: incident."
        )

        assert "Layout: incident." in prompt
        assert "- Q: How many signups did we get this week? Save it." in prompt
        assert "<user_question>\nBreak that down by country\n</user_question>" in prompt
        assert "posthog_untrusted_context" not in prompt

    @parameterized.expand(
        [
            (
                "counts_and_percents",
                "You had 412 signups, up 8% on last week.",
                "You had <n> signups, up <n>% on last week.",
            ),
            (
                "money_dates_and_times",
                "Revenue was $1,234.50 on 2026-09-16 at 14:10.",
                "Revenue was <n> on <n> at <n>.",
            ),
            ("identifiers_keep_their_digits", "p95 latency in v2 fell -12%.", "p95 latency in v2 fell -<n>%."),
            (
                "contact_details_and_ids",
                "Ask ada@example.com about 0199c0de-1111-7000-8000-0000000000aa at https://example.com/x",
                "Ask <email> about <id> at <url>",
            ),
        ]
    )
    def test_redact_values_masks_what_an_answer_reports(self, _name: str, text: str, expected: str):
        assert redact_values(text) == expected


def _judgment(**overrides: Any) -> TurnJudgment:
    judgment = TurnJudgment(
        model="jev-1.13.0",
        show_probability=0.9,
        intent=TurnIntent.METRIC_STATE,
        offer=OfferKind.SCOUT,
        offer_probabilities={"scout": 0.7, "none": 0.3},
        scout_mode=ScoutMode.REPORT,
        cadence=ScoutCadence.WEEKLY,
        notebook_template=NotebookTemplate.CONVERSATION,
        alert_direction=AlertDirection.DECREASE,
        alert_change_percent=20,
        insight=SAVED_INSIGHT,
        error_issue=ERROR_ISSUE,
        issue_resolved_probability=0.9,
    )
    return replace(judgment, **overrides)


def _answers(nouls: dict[str, float], choices: dict[str, str]) -> SystemOneAnswers:
    return SystemOneAnswers(
        model="jev-1.13.0",
        nouls={key: NoulAnswer(noul=value) for key, value in nouls.items()},
        choices={
            key: ChoiceAnswer(choice=value, probabilities={value: 1.0}, confidence=1.0)
            for key, value in choices.items()
        },
        input_tokens=300,
    )


FUNNEL_INSIGHT = replace(SAVED_INSIGHT, query_kind="FunnelsQuery")
JUDGMENT = "products.posthog_ai.backend.turn_suggestions.judgment"
CLASSIFIER = "products.posthog_ai.backend.turn_suggestions.classifier"


class TestJudgeTurn(SimpleTestCase):
    @parameterized.expand(
        [("saved_insight", _saved_insight_turn(), "abc123"), ("error_issue", _error_turn(), ERROR_ISSUE.issue_id)]
    )
    def test_jev_sees_the_question_and_a_masked_answer_but_no_outputs_or_ids(
        self, _name: str, entries: list[dict], hidden_id: str
    ):
        transcript = build_turn_transcript(entries)

        state = build_judge_state(transcript)
        questions = build_judge_questions(transcript, ALL_OFFERS)

        wire = json.dumps({"state": state, "questions": {key: q.to_json() for key, q in questions.items()}})
        assert hidden_id not in wire
        latest = state["latest_turn"]
        assert isinstance(latest, dict)
        assert latest["question"] == transcript.last_human_message
        assert "<n>" in str(latest["answer"]) and not any(char.isdigit() for char in str(latest["answer"]))

    def test_option_keys_map_back_to_the_refs_they_stand_for(self):
        answers = _answers(
            {"show_offer": 0.8, "issue_resolved": 0.1},
            {
                "intent": "metric_state",
                "offer": "alert",
                "scout_mode": "watch",
                "cadence": "daily",
                "notebook_template": "conversation",
                "alert_direction": "increase",
                "alert_change": "large",
                "insight": "insight_1",
            },
        )

        with patch(f"{JUDGMENT}.system_one", return_value=answers):
            judgment = judge_turn(build_turn_transcript(_saved_insight_turn()), available=ALL_OFFERS)

        assert judgment is not None
        assert judgment.offer == OfferKind.ALERT
        assert judgment.insight == SAVED_INSIGHT
        assert judgment.alert_direction == AlertDirection.INCREASE
        assert judgment.alert_change_percent == 50
        assert judgment.cadence == ScoutCadence.DAILY
        assert judgment.error_issue is None

    @parameterized.expand(
        [("typesafe_error", TypeSafeRequestFailed("HTTP 500")), ("network_error", requests.ConnectionError())]
    )
    def test_a_failed_request_returns_none(self, _name: str, error: Exception):
        with patch(f"{JUDGMENT}.system_one", side_effect=error):
            assert judge_turn(build_turn_transcript(_metric_turn()), available=ALL_OFFERS) is None


class TestPickOffer(SimpleTestCase):
    @parameterized.expand(
        [
            ("offers_what_jev_picked", {}, ALL_OFFERS, OfferKind.SCOUT),
            ("below_the_show_threshold", {"show_probability": 0.3}, ALL_OFFERS, OfferKind.NONE),
            ("pick_the_project_cannot_act_on", {}, frozenset({OfferKind.NOTEBOOK}), OfferKind.NONE),
            ("alert_without_an_insight", {"offer": OfferKind.ALERT, "insight": None}, ALL_OFFERS, OfferKind.NONE),
            ("alert_on_a_funnel", {"offer": OfferKind.ALERT, "insight": FUNNEL_INSIGHT}, ALL_OFFERS, OfferKind.NONE),
            (
                "subscription_on_a_funnel",
                {"offer": OfferKind.SUBSCRIPTION, "insight": FUNNEL_INSIGHT},
                ALL_OFFERS,
                OfferKind.SUBSCRIPTION,
            ),
            (
                "error_alert_on_an_active_issue",
                {"offer": OfferKind.ERROR_ALERT, "issue_resolved_probability": 0.2},
                ALL_OFFERS,
                OfferKind.NONE,
            ),
            ("error_alert_on_a_resolved_issue", {"offer": OfferKind.ERROR_ALERT}, ALL_OFFERS, OfferKind.ERROR_ALERT),
        ]
    )
    def test_policy(self, _name: str, overrides: dict, available: frozenset[OfferKind], expected: OfferKind):
        assert pick_offer(_judgment(**overrides), available) == expected


class TestBenchmark(SimpleTestCase):
    def test_every_case_expects_offers_its_turn_can_make(self):
        cases = load_cases()

        assert len({case.name for case in cases}) == len(cases)
        for case in cases:
            assert case.acceptable - {OfferKind.NONE} <= case.available, case.name

    def test_scores_count_false_offers_misses_and_ignore_borderline_cases(self):
        transcript = build_turn_transcript(_metric_turn())

        def result(acceptable: set[OfferKind], show: float) -> CaseResult:
            case = BenchmarkCase(
                name="case",
                category="test",
                acceptable=frozenset(acceptable),
                transcript=transcript,
                available=ALL_OFFERS,
            )
            return CaseResult(case=case, judgment=_judgment(show_probability=show), seconds=0.1)

        results = [
            result({OfferKind.SCOUT}, 0.9),
            result({OfferKind.SCOUT}, 0.55),
            result({OfferKind.NONE}, 0.6),
            result({OfferKind.NONE}, 0.1),
            result({OfferKind.SCOUT, OfferKind.NONE}, 0.9),
            result({OfferKind.NOTEBOOK, OfferKind.NONE}, 0.9),
        ]

        low = score(results, 0.5)
        high = score(results, 0.7)

        assert (low.offer_rate, low.precision, low.recall) == (5 / 6, 0.5, 1.0)
        assert (low.false_offers, low.wrong_kind) == (1, 1)
        assert (high.offer_rate, high.precision, high.recall, high.missed) == (0.5, 0.5, 0.5, 1)
        assert best_threshold([low, high]) == low


class TestClassifyTurn(SimpleTestCase):
    def _classify(self, judgment: TurnJudgment | None, scout_draft: ScoutDraft | None = None):
        with (
            patch(f"{CLASSIFIER}.judge_turn", return_value=judgment),
            patch(f"{CLASSIFIER}.draft_scout", return_value=scout_draft) as draft_scout_mock,
            patch(f"{CLASSIFIER}.draft_notebook") as draft_notebook_mock,
        ):
            verdict = classify_turn(
                build_turn_transcript(_saved_insight_turn()), team_id=1, today=date(2026, 9, 16), available=ALL_OFFERS
            )
        return verdict, draft_scout_mock, draft_notebook_mock

    def test_an_alert_is_built_from_the_judgment_without_a_language_model(self):
        verdict, draft_scout_mock, draft_notebook_mock = self._classify(
            _judgment(offer=OfferKind.ALERT, alert_direction=AlertDirection.INCREASE, alert_change_percent=50)
        )

        assert verdict is not None
        assert verdict.draft == AlertDraft(insight=SAVED_INSIGHT, direction=AlertDirection.INCREASE, change_percent=50)
        assert verdict.title == "Get an alert when this rises"
        assert verdict.description == "The alert checks once a day, compares with the day before, and posts to Slack."
        draft_scout_mock.assert_not_called()
        draft_notebook_mock.assert_not_called()

    def test_a_scout_is_drafted_with_the_judged_mode_and_cadence(self):
        draft = ScoutDraft(
            mode=ScoutMode.WATCH,
            display_name="Signups watch",
            description="Watches signups.",
            body="# Signups",
            cadence=ScoutCadence.DAILY,
        )

        verdict, draft_scout_mock, _ = self._classify(
            _judgment(scout_mode=ScoutMode.WATCH, cadence=ScoutCadence.DAILY), scout_draft=draft
        )

        assert verdict is not None and verdict.draft == draft
        assert draft_scout_mock.call_args.kwargs["mode"] == ScoutMode.WATCH
        assert draft_scout_mock.call_args.kwargs["cadence"] == ScoutCadence.DAILY
        assert verdict.title == "Get a Slack message when this changes"

    def test_a_failed_draft_keeps_the_pick_but_offers_nothing(self):
        verdict, _, _ = self._classify(_judgment(), scout_draft=None)

        assert verdict is not None
        assert verdict.picked == OfferKind.SCOUT
        assert verdict.draft is None

    def test_a_failed_judgment_returns_none(self):
        verdict, draft_scout_mock, _ = self._classify(None)

        assert verdict is None
        draft_scout_mock.assert_not_called()


def _gateway_reply(payload: dict) -> MagicMock:
    client = MagicMock()
    client.with_options.return_value = client
    client.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(content=json.dumps(payload)))]
    )
    return client


class TestDraftScout(SimpleTestCase):
    def _draft(self, content: str) -> tuple[ScoutDraft | None, MagicMock]:
        client = _gateway_reply({})
        client.chat.completions.create.return_value = MagicMock(choices=[MagicMock(message=MagicMock(content=content))])
        with patch("products.posthog_ai.backend.turn_suggestions.drafter.get_llm_client", return_value=client):
            draft = draft_scout(
                build_turn_transcript(_metric_turn()),
                team_id=1,
                today=date(2026, 9, 16),
                mode=ScoutMode.WATCH,
                cadence=ScoutCadence.DAILY,
            )
        return draft, client

    def test_the_reply_becomes_a_draft_with_the_mode_and_cadence_it_was_given(self):
        draft, client = self._draft(
            json.dumps({"display_name": " Signups watch ", "description": "Watches signups.", "prompt": "# Signups"})
        )

        assert draft == ScoutDraft(
            mode=ScoutMode.WATCH,
            display_name="Signups watch",
            description="Watches signups.",
            body="# Signups",
            cadence=ScoutCadence.DAILY,
        )
        request = client.chat.completions.create.call_args.kwargs
        assert request["model"] == DRAFT_MODEL
        assert request["response_format"]["json_schema"]["strict"] is True
        assert "Scout mode: watch." in request["messages"][1]["content"]

    @parameterized.expand(
        [
            ("prose", "I cannot tell."),
            ("invalid_shape", json.dumps({"display_name": "x"})),
            ("empty_prompt", json.dumps({"display_name": "x", "description": "y", "prompt": " "})),
        ]
    )
    def test_unusable_replies_return_none(self, _name: str, content: str):
        draft, _ = self._draft(content)

        assert draft is None


class TestEnqueueTurnSuggestion(BaseTest):
    @parameterized.expand(
        [
            ("posthog_ai", Task.OriginProduct.POSTHOG_AI, True),
            ("other_product", Task.OriginProduct.USER_CREATED, False),
        ]
    )
    def test_only_posthog_ai_runs_are_classified(self, _name: str, origin: str, expected: bool):
        task = Task.objects.create(
            team=self.team, title="t", description="d", origin_product=origin, created_by=self.user
        )
        task_run = task.create_run(mode="interactive")

        with patch("products.posthog_ai.backend.tasks.generate_turn_suggestion_task.delay") as delay:
            assert enqueue_turn_suggestion(task_run) is expected

        assert delay.called is expected
        if expected:
            assert delay.call_args.kwargs == {"run_id": str(task_run.id), "team_id": self.team.id}


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
        self.judge = patch(f"{SERVICE}.judge_configured", return_value=True)
        self.capture = patch(f"{SERVICE}.ph_scoped_capture")
        self.mocks = {
            name: patcher.start()
            for name, patcher in {
                "stream": self.stream,
                "publish": self.publish,
                "classify": self.classify,
                "scouts": self.scouts,
                "flag": self.flag,
                "judge": self.judge,
                "capture": self.capture,
            }.items()
        }
        for patcher in (
            self.stream,
            self.publish,
            self.classify,
            self.scouts,
            self.flag,
            self.judge,
            self.capture,
        ):
            self.addCleanup(patcher.stop)

    def _generate(self) -> TurnSuggestionOutcome:
        return generate_turn_suggestion(str(self.task_run.id), self.team.id)

    def _published_params(self) -> dict:
        return self.mocks["publish"].call_args.args[4]

    def _available(self) -> frozenset[OfferKind]:
        return self.mocks["classify"].call_args.kwargs["available"]

    def test_publishes_a_scout_suggestion_for_a_metric_turn(self):
        outcome = self._generate()

        assert outcome == TurnSuggestionOutcome(status="emitted", reason="scout")
        run_id, task_id, team_id, method, params = self.mocks["publish"].call_args.args
        assert (run_id, task_id, team_id, method) == (
            self.task_run.id,
            self.task_run.task_id,
            self.team.id,
            TURN_SUGGESTION_METHOD,
        )
        assert params["turnIndex"] == 0
        assert params["kind"] == "scout"
        assert params["scout"] == {
            "mode": "report",
            "displayName": "Weekly signups",
            "description": "Counts signed_up events for the last 7 days.",
            "body": "# Weekly signups\n\nQuery `signed_up` for the last 7 days...",
            "cadence": "weekly",
        }
        assert self._available() == frozenset({OfferKind.NOTEBOOK, OfferKind.SCOUT})

    @parameterized.expand(
        [
            (
                "incident_notebook",
                OfferKind.NOTEBOOK,
                "notebook",
                {
                    "title": "Why signups dropped on Tuesday",
                    "summary": "A checkout error cut Tuesday's signups by a third.",
                    "incident": {"timeline": "- 14:10 release", "cause": "Checkout error.", "fix": "Rolled back."},
                },
            ),
            (
                "alert",
                OfferKind.ALERT,
                "alert",
                {
                    "insightShortId": "abc123",
                    "insightId": 42,
                    "insightName": "Signups",
                    "direction": "decrease",
                    "changePercent": 20,
                },
            ),
            (
                "subscription",
                OfferKind.SUBSCRIPTION,
                "subscription",
                {
                    "insightShortId": "abc123",
                    "insightId": 42,
                    "insightName": "Signups",
                    "cadence": "weekly",
                },
            ),
            (
                "error_alert",
                OfferKind.ERROR_ALERT,
                "errorAlert",
                {"issueId": ERROR_ISSUE.issue_id, "issueName": "Checkout error"},
            ),
        ]
    )
    def test_each_offer_kind_publishes_its_own_frame(self, _name: str, offer: OfferKind, key: str, expected: dict):
        self.mocks["stream"].return_value = _error_turn() if offer == OfferKind.ERROR_ALERT else _saved_insight_turn()
        self.mocks["classify"].return_value = _verdict(offer=offer)

        outcome = self._generate()

        assert outcome == TurnSuggestionOutcome(status="emitted", reason=offer.value)
        params = self._published_params()
        assert params["kind"] == offer.value
        assert params[key] == expected

    @parameterized.expand(
        [
            ("trends_insight", "TrendsQuery", {OfferKind.NOTEBOOK, OfferKind.SUBSCRIPTION, OfferKind.ALERT}),
            ("funnel_insight", "FunnelsQuery", {OfferKind.NOTEBOOK, OfferKind.SUBSCRIPTION}),
        ]
    )
    def test_offers_follow_what_the_turn_and_project_make_possible(self, _name: str, query_kind: str, expected: set):
        self.mocks["stream"].return_value = _saved_insight_turn(query_kind)
        self.mocks["scouts"].return_value = False

        self._generate()

        assert self._available() == frozenset(expected)

    def test_a_turn_with_nothing_to_offer_never_reaches_the_classifier(self):
        self.mocks["scouts"].return_value = False
        self.mocks["stream"].return_value = [_user_message("Why did signups drop?"), _agent_text("Hard to say.")]

        outcome = self._generate()

        assert outcome.reason == "no_offers_available"
        self.mocks["classify"].assert_not_called()

    def test_verdict_without_an_offer_is_recorded_but_not_published(self):
        self.mocks["classify"].return_value = _verdict(offer=OfferKind.NONE, intent=TurnIntent.KNOWLEDGE)

        outcome = self._generate()

        assert outcome == TurnSuggestionOutcome(status="skipped", reason="no_offer:knowledge")
        self.mocks["publish"].assert_not_called()
        capture = self.mocks["capture"].return_value.__enter__.return_value
        assert capture.call_args.kwargs["properties"]["emitted"] is False
        assert capture.call_args.kwargs["properties"]["offer"] is None

    def test_a_pick_whose_draft_failed_is_a_failure_and_not_published(self):
        self.mocks["classify"].return_value = replace(_verdict(), draft=None)

        outcome = self._generate()

        assert outcome == TurnSuggestionOutcome(status="failed", reason="draft_failed")
        self.mocks["publish"].assert_not_called()
        capture = self.mocks["capture"].return_value.__enter__.return_value
        assert capture.call_args.kwargs["properties"]["picked"] == "scout"
        assert capture.call_args.kwargs["properties"]["draft_model"] == DRAFT_MODEL

    def test_follow_up_turns_are_classified_with_their_own_turn_index(self):
        self.mocks["stream"].return_value = [
            *_metric_turn(),
            _user_message("Break that down by country"),
            _exec_tool_call(
                "t2", 'call query-trends {"breakdownFilter":{"breakdown":"$geoip_country_code"}}', "completed"
            ),
            _agent_text("Most signups came from the US."),
        ]

        outcome = self._generate()

        assert outcome.status == "emitted"
        assert self._published_params()["turnIndex"] == 1
        transcript = self.mocks["classify"].call_args.args[0]
        assert transcript.last_human_message == "Break that down by country"
        assert [turn.question for turn in transcript.earlier_turns] == ["How many signups did we get this week?"]
        assert read_ledger(self.task_run.task_id, self.team.id).offers == (
            OfferRecord(turn_index=1, run_id=str(self.task_run.id), kind="scout", status=OfferStatus.OFFERED),
        )

    @parameterized.expand(
        [
            ("muted", {"offers": [], "muted": True}, "dismissed"),
            ("budget_spent", {"offers": [_offer(0), _offer(1)]}, "offer_budget_spent"),
            ("card_on_the_previous_turn", {"offers": [_offer(0)]}, "follows_an_offer"),
            ("turn_already_claimed", {"offers": [], "last_classified_turn": 1}, "already_classified"),
        ]
    )
    def test_the_offer_ledger_holds_back_a_card(self, _name: str, ledger: dict, reason: str):
        Task.objects.filter(id=self.task_run.task_id).update(state={STATE_KEY: ledger})
        self.mocks["stream"].return_value = [*_metric_turn(), _user_message("And by country?"), _agent_text("US.")]

        outcome = self._generate()

        assert outcome == TurnSuggestionOutcome(status="skipped", reason=reason)
        self.mocks["classify"].assert_not_called()

    @parameterized.expand(
        [
            ("slack", {"origin_product": Task.OriginProduct.SLACK}, "not_posthog_ai_conversation"),
            ("desktop", {"client_provenance": TaskClientProvenance.POSTHOG_DESKTOP}, "not_started_in_web"),
        ]
    )
    def test_only_conversations_started_in_the_web_app_get_a_card(self, _name: str, fields: dict, reason: str):
        Task.objects.filter(id=self.task_run.task_id).update(**fields)

        outcome = self._generate()

        assert outcome == TurnSuggestionOutcome(status="skipped", reason=reason)
        self.mocks["classify"].assert_not_called()

    @parameterized.expand([("flag", "flag_off"), ("judge", "judge_not_configured")])
    def test_a_closed_gate_skips_before_classifying(self, gate: str, reason: str):
        self.mocks[gate].return_value = False

        outcome = self._generate()

        assert outcome.reason == reason
        self.mocks["classify"].assert_not_called()

    def test_falls_back_to_the_stored_log_when_the_live_stream_is_gone(self):
        self.mocks["stream"].return_value = []
        log_lines = "\n".join(json.dumps(entry) for entry in _metric_turn()) + "\nnot json\n"

        with patch(f"{SERVICE}.read_task_run_logs", return_value=log_lines):
            outcome = self._generate()

        assert outcome.status == "emitted"
        transcript = self.mocks["classify"].call_args.args[0]
        assert transcript.last_human_message == "How many signups did we get this week?"

    def test_classifier_failure_is_recorded_and_not_published(self):
        self.mocks["classify"].return_value = None

        outcome = self._generate()

        assert outcome == TurnSuggestionOutcome(status="failed", reason="classifier_failed")
        self.mocks["publish"].assert_not_called()

    def test_a_run_from_another_team_is_ignored(self):
        outcome = generate_turn_suggestion(str(self.task_run.id), self.team.id + 1)

        assert outcome.reason == "run_missing"
        self.mocks["classify"].assert_not_called()

    def test_second_report_of_the_same_turn_is_deduplicated(self):
        first = self._generate()
        second = self._generate()

        assert first.status == "emitted"
        assert second == TurnSuggestionOutcome(status="skipped", reason="already_classified")
        self.mocks["classify"].assert_called_once()


class TestResolveTurnSuggestion(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.task = Task.objects.create(
            team=self.team,
            title="t",
            description="d",
            origin_product=Task.OriginProduct.POSTHOG_AI,
            created_by=self.user,
        )
        self.task_run = self.task.create_run(mode="interactive")
        Task.objects.filter(id=self.task.id).update(
            state={STATE_KEY: {"offers": [_offer(0, run_id=str(self.task_run.id))]}}
        )

    def _resolve(self, task_id: str, turn_index: int, resolution: str):
        with patch(f"{SERVICE}.publish_task_run_stream_notification", return_value=True) as publish:
            response = self.client.post(
                f"/api/projects/{self.team.id}/turn_suggestions/resolve/",
                {"task_id": task_id, "turn_index": turn_index, "resolution": resolution},
                format="json",
            )
        return response, publish

    def test_a_dismissal_mutes_the_conversation_and_replays_into_the_run_log(self):
        response, publish = self._resolve(str(self.task.id), 0, "dismissed")

        assert response.status_code == 200
        assert response.json() == {"recorded": True}
        ledger = read_ledger(self.task.id, self.team.id)
        assert ledger.muted is True
        assert ledger.offers[0].status == OfferStatus.DISMISSED
        assert publish.call_args.args == (
            str(self.task_run.id),
            str(self.task.id),
            self.team.id,
            "_posthog/turn_suggestion_resolved",
            {"turnIndex": 0, "outcome": "dismissed"},
        )

    @parameterized.expand([("turn_without_a_card", False, 3, 200), ("task_of_another_team", True, 0, 404)])
    def test_nothing_is_recorded_for_a_card_that_does_not_exist(
        self, _name: str, other_team: bool, turn_index: int, status_code: int
    ):
        task_id = str(self.task.id)
        if other_team:
            other = self.create_team_with_organization(organization=self.organization)
            task_id = str(
                Task.objects.create(
                    team=other,
                    title="t",
                    description="d",
                    origin_product=Task.OriginProduct.POSTHOG_AI,
                    created_by=self.user,
                ).id
            )

        response, publish = self._resolve(task_id, turn_index, "accepted")

        assert response.status_code == status_code
        publish.assert_not_called()
        assert read_ledger(self.task.id, self.team.id).offers[0].status == OfferStatus.OFFERED
