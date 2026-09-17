import json
from datetime import date

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from parameterized import parameterized

from products.posthog_ai.backend.turn_suggestions.classifier import (
    CLASSIFIER_MODEL,
    AlertDirection,
    AlertDraft,
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
    classify_turn,
    render_turn_prompt,
)
from products.posthog_ai.backend.turn_suggestions.dispatch import enqueue_turn_suggestion
from products.posthog_ai.backend.turn_suggestions.service import (
    TURN_SUGGESTION_METHOD,
    TurnSuggestionOutcome,
    generate_turn_suggestion,
)
from products.posthog_ai.backend.turn_suggestions.transcript import (
    ErrorIssueRef,
    SavedInsightRef,
    build_turn_transcript,
)
from products.tasks.backend.models import Task

SERVICE = "products.posthog_ai.backend.turn_suggestions.service"
ALL_OFFERS = frozenset(OfferKind)


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


def _saved_insight_turn() -> list[dict]:
    return [
        _user_message("How many signups did we get this week? Save it."),
        _exec_tool_call(
            "t1",
            'call insight-create {"name":"Signups"}',
            "completed",
            {"id": 42, "short_id": "abc123", "name": "Signups", "query": {"kind": "TrendsQuery", "series": []}},
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


def _verdict(offer: OfferKind = OfferKind.SCOUT, intent: TurnIntent = TurnIntent.METRIC_STATE) -> TurnVerdict:
    return TurnVerdict(
        intent=intent,
        offer=offer,
        confidence=0.92,
        title="Get this every week in Slack",
        description="A scout can rerun this count each week and post the result.",
        scout=ScoutDraft(
            mode=ScoutMode.REPORT,
            display_name="Weekly signups",
            description="Counts signed_up events for the last 7 days.",
            body="# Weekly signups\n\nQuery `signed_up` for the last 7 days...",
            cadence=ScoutCadence.WEEKLY,
        )
        if offer == OfferKind.SCOUT
        else None,
        notebook=NotebookDraft(
            template=NotebookTemplate.INCIDENT,
            title="Why signups dropped on Tuesday",
            summary="A checkout error cut Tuesday's signups by a third.",
            incident=IncidentOutline(timeline="- 14:10 release", cause="Checkout error.", fix="Rolled back."),
        )
        if offer == OfferKind.NOTEBOOK
        else None,
        alert=AlertDraft(insight=SAVED_INSIGHT, direction=AlertDirection.DECREASE, change_percent=20)
        if offer == OfferKind.ALERT
        else None,
        subscription=SubscriptionDraft(insight=SAVED_INSIGHT, cadence=ScoutCadence.WEEKLY)
        if offer == OfferKind.SUBSCRIPTION
        else None,
        error_alert=ErrorAlertDraft(issue=ERROR_ISSUE) if offer == OfferKind.ERROR_ALERT else None,
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

    def test_prompt_rendering_lists_offers_context_and_resolved_tools(self):
        entries = [*_saved_insight_turn(), _user_message("Break that down by country"), _agent_text("Mostly the US.")]

        prompt = render_turn_prompt(
            build_turn_transcript(entries),
            today=date(2026, 9, 16),
            available=frozenset({OfferKind.NONE, OfferKind.SCOUT, OfferKind.NOTEBOOK}),
        )

        assert "<available_offers>\n- none\n- scout" in prompt and "alert" not in prompt.split("</available_offers>")[0]
        assert "- Q: How many signups did we get this week? Save it." in prompt
        assert "<user_question>\nBreak that down by country\n</user_question>" in prompt
        assert "posthog_untrusted_context" not in prompt


def _gateway_reply(payload: dict) -> MagicMock:
    client = MagicMock()
    client.with_options.return_value = client
    client.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(content=json.dumps(payload)))]
    )
    return client


_REPLY = {
    "intent": "metric_state",
    "offer": "scout",
    "confidence": 0.9,
    "title": "Get this every week in Slack",
    "description": "A scout can rerun this each week.",
    "scout_mode": "report",
    "scout_display_name": "Weekly signups",
    "scout_description": "Counts signups weekly.",
    "scout_prompt": "# Weekly signups",
    "cadence": "weekly",
    "notebook_template": "conversation",
    "notebook_title": "",
    "notebook_summary": "",
    "incident_timeline": "",
    "incident_cause": "",
    "incident_fix": "",
    "alert_insight_short_id": "",
    "alert_direction": "decrease",
    "alert_change_percent": 0,
    "subscription_insight_short_id": "",
    "subscription_cadence": "weekly",
    "error_issue_id": "",
}


class TestClassifyTurn(SimpleTestCase):
    def _classify(self, reply: dict, entries: list[dict], available: frozenset[OfferKind] = ALL_OFFERS):
        client = _gateway_reply(reply)
        with patch("products.posthog_ai.backend.turn_suggestions.classifier.get_llm_client", return_value=client):
            verdict = classify_turn(
                build_turn_transcript(entries), team_id=1, today=date(2026, 9, 16), available=available
            )
        return verdict, client

    @parameterized.expand(
        [
            ("scout_report", _REPLY, _metric_turn(), OfferKind.SCOUT),
            (
                "incident_notebook",
                {
                    **_REPLY,
                    "intent": "diagnostic",
                    "offer": "notebook",
                    "notebook_template": "incident",
                    "notebook_title": "Why signups dropped",
                    "notebook_summary": "A checkout error.",
                    "incident_timeline": "- 14:10 release",
                    "incident_cause": "Checkout error.",
                    "incident_fix": "Rolled back.",
                },
                _metric_turn(),
                OfferKind.NOTEBOOK,
            ),
            (
                "alert_on_saved_insight",
                {**_REPLY, "offer": "alert", "alert_insight_short_id": "abc123", "alert_change_percent": 20.4},
                _saved_insight_turn(),
                OfferKind.ALERT,
            ),
            (
                "subscription_on_saved_insight",
                {**_REPLY, "offer": "subscription", "subscription_insight_short_id": "abc123"},
                _saved_insight_turn(),
                OfferKind.SUBSCRIPTION,
            ),
            (
                "error_alert",
                {**_REPLY, "intent": "diagnostic", "offer": "error_alert", "error_issue_id": ERROR_ISSUE.issue_id},
                _error_turn(),
                OfferKind.ERROR_ALERT,
            ),
            ("none", {**_REPLY, "intent": "knowledge", "offer": "none"}, _metric_turn(), OfferKind.NONE),
        ]
    )
    def test_maps_the_gateway_reply_onto_an_offer(self, _name: str, reply: dict, entries: list[dict], offer: OfferKind):
        verdict, client = self._classify(reply, entries)

        assert verdict is not None
        assert verdict.offer == offer
        assert verdict.offers is (offer != OfferKind.NONE)
        request = client.chat.completions.create.call_args.kwargs
        assert request["model"] == CLASSIFIER_MODEL
        assert request["response_format"]["json_schema"]["strict"] is True

    def test_alert_draft_rounds_the_percent_and_keeps_the_insight_reference(self):
        verdict, _ = self._classify(
            {**_REPLY, "offer": "alert", "alert_insight_short_id": " abc123 ", "alert_change_percent": 20.4},
            _saved_insight_turn(),
        )

        assert verdict is not None and verdict.alert is not None
        assert verdict.alert.insight == SAVED_INSIGHT
        assert verdict.alert.change_percent == 20

    @parameterized.expand(
        [
            ("offer_not_available", {**_REPLY, "offer": "scout"}, frozenset({OfferKind.NONE, OfferKind.NOTEBOOK})),
            ("alert_on_unknown_insight", {**_REPLY, "offer": "alert", "alert_insight_short_id": "nope"}, ALL_OFFERS),
        ]
    )
    def test_a_pick_the_project_cannot_act_on_becomes_none(self, _name: str, reply: dict, available):
        verdict, _ = self._classify(reply, _saved_insight_turn(), available)

        assert verdict is not None
        assert verdict.offers is False

    @parameterized.expand([("prose", "I cannot tell."), ("invalid_shape", json.dumps({"intent": "metric_state"}))])
    def test_unusable_replies_return_none(self, _name: str, content: str):
        client = _gateway_reply({})
        client.chat.completions.create.return_value = MagicMock(choices=[MagicMock(message=MagicMock(content=content))])

        with patch("products.posthog_ai.backend.turn_suggestions.classifier.get_llm_client", return_value=client):
            verdict = classify_turn(
                build_turn_transcript(_metric_turn()), team_id=1, today=date(2026, 9, 16), available=ALL_OFFERS
            )

        assert verdict is None


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
        self.capture = patch(f"{SERVICE}.ph_scoped_capture")
        self.redis = patch(
            f"{SERVICE}.get_client",
            return_value=MagicMock(set=MagicMock(return_value=True), get=MagicMock(return_value=None)),
        )
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
        assert self._available() == frozenset({OfferKind.NONE, OfferKind.NOTEBOOK, OfferKind.SCOUT})

    @parameterized.expand(
        [
            (
                "incident_notebook",
                OfferKind.NOTEBOOK,
                "notebook",
                {
                    "template": "incident",
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
                    "queryKind": "TrendsQuery",
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
                    "queryKind": "TrendsQuery",
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

    def test_offers_follow_what_the_turn_and_project_make_possible(self):
        self.mocks["stream"].return_value = _saved_insight_turn()
        self.mocks["scouts"].return_value = False

        self._generate()

        assert self._available() == frozenset(
            {OfferKind.NONE, OfferKind.NOTEBOOK, OfferKind.SUBSCRIPTION, OfferKind.ALERT}
        )

    def test_a_pick_outside_the_available_offers_is_not_published(self):
        self.mocks["scouts"].return_value = False

        outcome = self._generate()

        assert outcome.reason == "no_offer:metric_state"
        self.mocks["publish"].assert_not_called()

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
        pipeline = self.mocks["redis"].return_value.pipeline.return_value.__enter__.return_value
        pipeline.incr.assert_called_once()

    def test_a_conversation_stops_getting_offers_once_its_budget_is_spent(self):
        self.mocks["redis"].return_value.get.return_value = b"2"

        outcome = self._generate()

        assert outcome.reason == "offer_budget_spent"
        self.mocks["classify"].assert_not_called()

    def test_a_closed_flag_skips_before_classifying(self):
        self.mocks["flag"].return_value = False

        outcome = self._generate()

        assert outcome.reason == "flag_off"
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
        self.mocks["redis"].return_value.set.return_value = False

        outcome = self._generate()

        assert outcome.reason == "already_classified"
        self.mocks["classify"].assert_not_called()
