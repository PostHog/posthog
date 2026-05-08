"""Tests for `LLMAnalyticsConversationsViewSet`.

Three concerns:

1. The list endpoint shapes raw `$ai_generation` events into one row per
   `$ai_session_id`, with a per-row title preview from the first user message.
   Orphan traces are hidden by default and surface only when
   `include_orphan_traces=true`.
2. The retrieve endpoint walks a session's traces and folds them into a flat
   transcript via `extract_turns`, which dedupes prior history so the reader
   sees only what the end user actually saw.
3. `extract_turns` is the only piece of bespoke Python logic with branching;
   it's covered by direct unit tests against synthetic `LLMTrace` fixtures.
"""

import json
from datetime import UTC, datetime, timedelta
from typing import Any

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events

from rest_framework import status

from posthog.schema import LLMTrace, LLMTraceEvent

from products.llm_analytics.backend.api.conversations import extract_turns


def _create_generation(
    *,
    team,
    distinct_id: str,
    trace_id: str,
    session_id: str | None,
    user_messages: list[dict[str, Any]],
    assistant_text: str,
    timestamp: datetime,
    cost: float = 0.001,
    model: str = "gpt-4o-mini",
):
    """Insert one $ai_generation event with the given history + assistant reply.

    `user_messages` is the *full* conversation history sent to the LLM at this
    turn (system + alternating user/assistant up to and including the current
    user message). `assistant_text` is the model's reply, surfaced via
    `$ai_output_choices`.
    """
    props: dict[str, Any] = {
        "$ai_trace_id": trace_id,
        "$ai_input": user_messages,
        "$ai_output_choices": [
            {"index": 0, "message": {"role": "assistant", "content": assistant_text}, "finish_reason": "stop"}
        ],
        "$ai_input_tokens": 10,
        "$ai_output_tokens": 5,
        "$ai_total_cost_usd": cost,
        "$ai_input_cost_usd": cost / 2,
        "$ai_output_cost_usd": cost / 2,
        "$ai_latency": 1.0,
        "$ai_model": model,
        "$ai_provider": "openai",
    }
    if session_id is not None:
        props["$ai_session_id"] = session_id

    _create_event(
        event="$ai_generation",
        distinct_id=distinct_id,
        team=team,
        properties=props,
        timestamp=timestamp,
    )


class TestConversationsList(ClickhouseTestMixin, APIBaseTest):
    URL: str = ""

    def setUp(self) -> None:
        super().setUp()
        self.URL = f"/api/environments/{self.team.id}/llm_analytics/conversations/"
        self.now = datetime.now(UTC).replace(microsecond=0)

    def _seed_session(self, session_id: str, exchanges: list[tuple[str, str]], minutes_ago_start: int = 5) -> None:
        """Insert a multi-turn session as N consecutive `$ai_generation` events.

        Each subsequent turn carries the prior history in `$ai_input`, mirroring
        what a real chat client would send.
        """
        history: list[dict[str, Any]] = [
            {"role": "system", "content": "You are a helpful assistant."},
        ]
        for i, (user_msg, assistant_msg) in enumerate(exchanges):
            history.append({"role": "user", "content": user_msg})
            _create_generation(
                team=self.team,
                distinct_id="user-1",
                trace_id=f"{session_id}-trace-{i}",
                session_id=session_id,
                user_messages=list(history),
                assistant_text=assistant_msg,
                timestamp=self.now - timedelta(minutes=minutes_ago_start - i),
            )
            history.append({"role": "assistant", "content": assistant_msg})

    def _seed_orphan(self, trace_id: str, prompt: str, reply: str, minutes_ago: int = 3) -> None:
        _create_generation(
            team=self.team,
            distinct_id="user-2",
            trace_id=trace_id,
            session_id=None,
            user_messages=[
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": prompt},
            ],
            assistant_text=reply,
            timestamp=self.now - timedelta(minutes=minutes_ago),
        )

    def test_returns_one_row_per_session_with_title(self):
        self._seed_session(
            "sess-cancel",
            [("How do I cancel my subscription?", "Settings → Billing.")],
        )
        self._seed_session(
            "sess-trends",
            [("What are trends?", "Trends show changes over time."), ("Example?", "Daily signups.")],
        )
        flush_persons_and_events()

        response = self.client.get(self.URL + "?date_from=-1d")
        assert response.status_code == status.HTTP_200_OK, response.content
        body = response.json()
        results = body["results"]
        assert len(results) == 2

        by_id = {row["id"]: row for row in results}
        assert by_id["sess-cancel"]["kind"] == "session"
        assert by_id["sess-cancel"]["title"] == "How do I cancel my subscription?"
        assert by_id["sess-cancel"]["turns"] == 1
        assert by_id["sess-trends"]["title"] == "What are trends?"
        assert by_id["sess-trends"]["turns"] == 2

    def test_orphan_traces_hidden_by_default(self):
        self._seed_session("sess-1", [("hi", "hello")])
        self._seed_orphan("orphan-1", "What's the capital of France?", "Paris.")
        flush_persons_and_events()

        response = self.client.get(self.URL + "?date_from=-1d")
        assert response.status_code == status.HTTP_200_OK
        ids = [row["id"] for row in response.json()["results"]]
        assert ids == ["sess-1"]

    def test_orphan_traces_appear_when_toggled(self):
        self._seed_session("sess-1", [("hi", "hello")])
        self._seed_orphan("orphan-1", "What's the capital of France?", "Paris.")
        flush_persons_and_events()

        response = self.client.get(self.URL + "?date_from=-1d&include_orphan_traces=true")
        assert response.status_code == status.HTTP_200_OK
        rows = response.json()["results"]
        kinds = {row["id"]: row["kind"] for row in rows}
        assert kinds == {"sess-1": "session", "orphan-1": "trace"}
        # Orphan title comes from the prompt
        orphan_row = next(r for r in rows if r["id"] == "orphan-1")
        assert orphan_row["title"] == "What's the capital of France?"
        assert orphan_row["turns"] == 1

    def test_date_filter_prunes_old_events(self):
        # Far in the past — outside default -1h
        old_session = "sess-old"
        history: list[dict[str, Any]] = [{"role": "user", "content": "ancient"}]
        _create_generation(
            team=self.team,
            distinct_id="user-1",
            trace_id="old-trace",
            session_id=old_session,
            user_messages=history,
            assistant_text="reply",
            timestamp=self.now - timedelta(days=10),
        )
        # Recent — inside -1h window
        self._seed_session("sess-recent", [("recent question", "recent reply")])
        flush_persons_and_events()

        response = self.client.get(self.URL + "?date_from=-1h")
        assert response.status_code == status.HTTP_200_OK
        ids = [row["id"] for row in response.json()["results"]]
        assert ids == ["sess-recent"]

    def test_property_filter_event_property(self):
        """Property filters apply at the event level. A trace surfaces if any of
        its events match the filter — so filtering by `$ai_model = "gpt-4o"`
        keeps sessions that have at least one matching generation."""
        # Session A: all gpt-4o-mini
        _create_generation(
            team=self.team,
            distinct_id="user-1",
            trace_id="t-a",
            session_id="sess-a",
            user_messages=[{"role": "user", "content": "a"}],
            assistant_text="A",
            timestamp=self.now - timedelta(minutes=10),
            model="gpt-4o-mini",
        )
        # Session B: gpt-4o (we want to find this one)
        _create_generation(
            team=self.team,
            distinct_id="user-1",
            trace_id="t-b",
            session_id="sess-b",
            user_messages=[{"role": "user", "content": "b"}],
            assistant_text="B",
            timestamp=self.now - timedelta(minutes=8),
            model="gpt-4o",
        )
        flush_persons_and_events()

        # Filter for the gpt-4o session
        properties = [
            {
                "type": "event",
                "key": "$ai_model",
                "operator": "exact",
                "value": ["gpt-4o"],
            }
        ]

        response = self.client.get(self.URL + f"?date_from=-1d&properties={json.dumps(properties)}")
        assert response.status_code == status.HTTP_200_OK, response.content
        ids = {row["id"] for row in response.json()["results"]}
        assert ids == {"sess-b"}

    def test_property_filter_person_property(self):
        """Person property filters take a different HogQL code path (joining the
        persons table on distinct_id) than event property filters do. Cover it
        explicitly so a regression in the join translation is caught."""
        from posthog.test.base import _create_person

        # Person 1: matches the filter
        _create_person(
            team=self.team,
            distinct_ids=["user-target"],
            properties={"email": "target@example.com"},
        )
        # Person 2: does not
        _create_person(
            team=self.team,
            distinct_ids=["user-other"],
            properties={"email": "other@example.com"},
        )
        _create_generation(
            team=self.team,
            distinct_id="user-target",
            trace_id="t-target",
            session_id="sess-target",
            user_messages=[{"role": "user", "content": "hi from target"}],
            assistant_text="reply",
            timestamp=self.now - timedelta(minutes=5),
        )
        _create_generation(
            team=self.team,
            distinct_id="user-other",
            trace_id="t-other",
            session_id="sess-other",
            user_messages=[{"role": "user", "content": "hi from other"}],
            assistant_text="reply",
            timestamp=self.now - timedelta(minutes=3),
        )
        flush_persons_and_events()

        properties = [
            {
                "type": "person",
                "key": "email",
                "operator": "exact",
                "value": ["target@example.com"],
            }
        ]
        response = self.client.get(self.URL + f"?date_from=-1d&properties={json.dumps(properties)}")
        assert response.status_code == status.HTTP_200_OK, response.content
        ids = {row["id"] for row in response.json()["results"]}
        assert ids == {"sess-target"}

    def test_property_filter_applies_to_orphan_traces_too(self):
        """The orphan-trace UNION branch is a separate SQL block that also embeds
        the `{filters}` placeholder. A regression where the filter is wired up on
        only one branch would silently leak rows when both toggles are on."""
        # Session with gpt-4o-mini — should NOT match
        _create_generation(
            team=self.team,
            distinct_id="user-1",
            trace_id="t-sess",
            session_id="sess-mini",
            user_messages=[{"role": "user", "content": "x"}],
            assistant_text="X",
            timestamp=self.now - timedelta(minutes=10),
            model="gpt-4o-mini",
        )
        # Orphan trace with gpt-4o-mini — should NOT match
        _create_generation(
            team=self.team,
            distinct_id="user-1",
            trace_id="t-orphan-mini",
            session_id=None,
            user_messages=[{"role": "user", "content": "y"}],
            assistant_text="Y",
            timestamp=self.now - timedelta(minutes=8),
            model="gpt-4o-mini",
        )
        # Orphan trace with gpt-4o — SHOULD match (proves filter applies to orphans)
        _create_generation(
            team=self.team,
            distinct_id="user-1",
            trace_id="t-orphan-target",
            session_id=None,
            user_messages=[{"role": "user", "content": "z"}],
            assistant_text="Z",
            timestamp=self.now - timedelta(minutes=6),
            model="gpt-4o",
        )
        flush_persons_and_events()

        properties = [
            {"type": "event", "key": "$ai_model", "operator": "exact", "value": ["gpt-4o"]},
        ]
        response = self.client.get(
            self.URL + f"?date_from=-1d&include_orphan_traces=true&properties={json.dumps(properties)}"
        )
        assert response.status_code == status.HTTP_200_OK, response.content
        ids = {row["id"] for row in response.json()["results"]}
        assert ids == {"t-orphan-target"}

    def test_invalid_properties_payload_returns_400(self):
        # Not a JSON array
        response = self.client.get(self.URL + "?properties=not-json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        # Valid JSON but not a list
        response = self.client.get(self.URL + '?properties={"key":"value"}')
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_other_team_is_isolated(self):
        # Seed in our team
        self._seed_session("sess-ours", [("ours", "us")])
        # Seed in a foreign team (different organization)
        from posthog.models import Organization, Team

        foreign_org = Organization.objects.create(name="other-org")
        foreign_team = Team.objects.create(organization=foreign_org, name="other-team")
        _create_generation(
            team=foreign_team,
            distinct_id="user-1",
            trace_id="foreign-trace",
            session_id="sess-foreign",
            user_messages=[{"role": "user", "content": "secret"}],
            assistant_text="hidden",
            timestamp=self.now,
        )
        flush_persons_and_events()

        response = self.client.get(self.URL + "?date_from=-1d")
        assert response.status_code == status.HTTP_200_OK
        ids = {row["id"] for row in response.json()["results"]}
        assert ids == {"sess-ours"}


class TestConversationsRetrieve(ClickhouseTestMixin, APIBaseTest):
    URL_TEMPLATE: str = ""

    def setUp(self) -> None:
        super().setUp()
        self.URL_TEMPLATE = f"/api/environments/{self.team.id}/llm_analytics/conversations/{{id}}/"
        self.now = datetime.now(UTC).replace(microsecond=0)

    def test_session_detail_dedupes_repeated_history(self):
        """Each turn's `$ai_input` carries the full conversation history. The
        retrieve endpoint must surface only the *new* user messages per turn,
        so the reader doesn't see the same prompt repeated three times."""
        session_id = "sess-multiturn"
        # Turn 1: user-only prompt, system message
        _create_generation(
            team=self.team,
            distinct_id="user-1",
            trace_id="trace-1",
            session_id=session_id,
            user_messages=[
                {"role": "system", "content": "sys"},
                {"role": "user", "content": "first user prompt"},
            ],
            assistant_text="first assistant reply",
            timestamp=self.now - timedelta(minutes=10),
        )
        # Turn 2: history of turn-1 + new user message
        _create_generation(
            team=self.team,
            distinct_id="user-1",
            trace_id="trace-2",
            session_id=session_id,
            user_messages=[
                {"role": "system", "content": "sys"},
                {"role": "user", "content": "first user prompt"},
                {"role": "assistant", "content": "first assistant reply"},
                {"role": "user", "content": "second user prompt"},
            ],
            assistant_text="second assistant reply",
            timestamp=self.now - timedelta(minutes=8),
        )
        flush_persons_and_events()

        response = self.client.get(self.URL_TEMPLATE.format(id=session_id) + "?date_from=-1d")
        assert response.status_code == status.HTTP_200_OK, response.content
        body = response.json()
        assert body["kind"] == "session"
        assert body["id"] == session_id
        assert body["title"] == "first user prompt"
        turns = body["turns"]
        assert len(turns) == 2

        # Turn 1: includes the first user prompt (system message is not shown — role filter)
        turn1_user_contents = [m["content"] for m in turns[0]["user_messages"]]
        assert "first user prompt" in turn1_user_contents
        # Turn 2: must show ONLY the new user prompt, not the repeated turn-1 messages
        turn2_user_contents = [m["content"] for m in turns[1]["user_messages"]]
        assert turn2_user_contents == ["second user prompt"]
        # Both turns must surface their assistant reply
        assert any(m["content"] == "first assistant reply" for m in turns[0]["assistant_messages"])
        assert any(m["content"] == "second assistant reply" for m in turns[1]["assistant_messages"])

    def test_orphan_trace_kind(self):
        trace_id = "orphan-x"
        _create_generation(
            team=self.team,
            distinct_id="user-1",
            trace_id=trace_id,
            session_id=None,
            user_messages=[{"role": "user", "content": "translate hello to spanish"}],
            assistant_text="hola",
            timestamp=self.now - timedelta(minutes=2),
        )
        flush_persons_and_events()

        response = self.client.get(self.URL_TEMPLATE.format(id=trace_id) + "?kind=trace&date_from=-1d")
        assert response.status_code == status.HTTP_200_OK, response.content
        body = response.json()
        assert body["kind"] == "trace"
        assert body["id"] == trace_id
        assert len(body["turns"]) == 1
        assert any(m["content"] == "hola" for m in body["turns"][0]["assistant_messages"])

    def test_unknown_id_returns_404(self):
        response = self.client.get(self.URL_TEMPLATE.format(id="does-not-exist") + "?date_from=-1d")
        assert response.status_code == status.HTTP_404_NOT_FOUND


class TestExtractTurns(APIBaseTest):
    """Pure-Python coverage of the dedup helper. No ClickHouse touch — just verifies
    the message-walk over synthetic LLMTrace fixtures."""

    def _trace(
        self,
        trace_id: str,
        generation_input: list[dict],
        generation_output: list[dict],
        created_at: datetime | None = None,
    ) -> LLMTrace:
        ts = created_at or datetime.now(UTC)
        gen_event = LLMTraceEvent(
            id=f"{trace_id}-gen",
            event="$ai_generation",
            createdAt=ts.isoformat(),
            properties={
                "$ai_input": generation_input,
                "$ai_output_choices": generation_output,
            },
        )
        return LLMTrace(
            id=trace_id,
            createdAt=ts.isoformat(),
            distinctId="user-1",
            events=[gen_event],
            totalCost=0.001,
            totalLatency=1.0,
            errorCount=0,
        )

    def test_single_turn_surfaces_user_and_assistant(self):
        trace = self._trace(
            "t1",
            generation_input=[
                {"role": "system", "content": "sys"},
                {"role": "user", "content": "hi"},
            ],
            generation_output=[{"role": "assistant", "content": "hello"}],
        )
        turns = extract_turns([trace])
        assert len(turns) == 1
        # System role is filtered; user content reaches the transcript.
        assert [m["content"] for m in turns[0]["user_messages"]] == ["hi"]
        assert [m["content"] for m in turns[0]["assistant_messages"]] == ["hello"]

    def test_tool_role_messages_are_preserved(self):
        trace = self._trace(
            "t1",
            generation_input=[
                {"role": "user", "content": "what's the weather?"},
                {"role": "assistant", "content": ""},
                {"role": "tool", "content": '{"temp":72}'},
            ],
            generation_output=[{"role": "assistant", "content": "72°F"}],
        )
        turns = extract_turns([trace])
        roles = [m["role"] for m in turns[0]["user_messages"]]
        assert "user" in roles and "tool" in roles
