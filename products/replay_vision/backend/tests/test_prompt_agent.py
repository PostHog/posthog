import json
import time
from typing import Any

from unittest.mock import patch

from django.utils import timezone

from google.genai import types
from parameterized import parameterized

from posthog.constants import AvailableFeature
from posthog.models import OrganizationMembership, User
from posthog.session_recordings.models.session_recording import SessionRecording

from products.replay_vision.backend.models.replay_observation import (
    ObservationStatus,
    ObservationTrigger,
    ReplayObservation,
)
from products.replay_vision.backend.models.replay_observation_label import ReplayObservationLabel
from products.replay_vision.backend.prompt_suggestions import (
    _MAX_SUMMARIES_PER_RUN,
    _MAX_TOOL_ROUNDS,
    _AgentToolState,
    _dispatch_agent_tool,
    _generate_agentic,
)
from products.replay_vision.backend.tests.test_api import _VisionAPITestCase

from ee.models.rbac.access_control import AccessControl


def _call(name: str, args: dict[str, Any]) -> types.FunctionCall:
    return types.FunctionCall(name=name, args=args)


class _Candidate:
    def __init__(self) -> None:
        self.content = "model-turn"


class _Response:
    def __init__(self, *, calls: list[types.FunctionCall] | None = None, text: str = "") -> None:
        self.function_calls = calls or []
        self.candidates = [_Candidate()]
        self.text = text


class TestPromptAgent(_VisionAPITestCase):
    def setUp(self) -> None:
        super().setUp()
        self.scanner = self._create_scanner()
        self.observation = ReplayObservation.objects.create(
            scanner=self.scanner,
            team=self.team,
            session_id="sess-1",
            status=ObservationStatus.SUCCEEDED,
            completed_at=timezone.now(),
            triggered_by=ObservationTrigger.ON_DEMAND,
            scanner_snapshot={"scanner_version": 1},
            scanner_result={
                "model_output": {
                    "verdict": "no",
                    "confidence": 0.9,
                    "scanner_type": "monitor",
                    "reasoning": "the user closed the tab at payment",
                },
                "signals_count": 0,
            },
        )
        ReplayObservationLabel.objects.create(observation=self.observation, is_correct=False, feedback="should be yes")

    def _state(self, *, allow_cold_summaries: bool = False, budget_s: float = 60.0) -> _AgentToolState:
        return _AgentToolState(self.scanner, self.user, allow_cold_summaries, time.monotonic() + budget_s)

    def test_tool_rounds_run_then_final_structured_answer_parses(self) -> None:
        answer = json.dumps({"suggested_prompt": "better prompt", "rationale": "grounded in sess-1"})
        responses = iter(
            [
                _Response(calls=[_call("get_rated_observation", {"session_id": "sess-1"})]),
                _Response(),  # model is done with tools
                _Response(text=answer),  # forced structured turn
            ]
        )
        with (
            patch("products.replay_vision.backend.prompt_suggestions.genai"),
            patch(
                "products.replay_vision.backend.prompt_suggestions._model_call",
                side_effect=lambda *a, **k: next(responses),
            ),
        ):
            parsed = _generate_agentic(
                scanner=self.scanner,
                user_content="briefing",
                user=self.user,
                allow_cold_summaries=False,
                distinct_id="test",
            )
        self.assertEqual(parsed.suggested_prompt, "better prompt")

    @parameterized.expand(
        [
            ("round_budget_exhausted", 60.0, _MAX_TOOL_ROUNDS + 2),
            ("time_budget_exhausted", 0.0, 2),
        ]
    )
    def test_exhausted_budget_answers_pending_tool_calls_before_the_final_turn(
        self, _name: str, budget_s: float, expected_model_calls: int
    ) -> None:
        answer = json.dumps({"suggested_prompt": "better prompt", "rationale": "grounded"})
        seen_contents: list[list[Any]] = []

        def fake_model_call(client: Any, contents: list[Any], config: Any, **kwargs: Any) -> _Response:
            seen_contents.append(list(contents))
            if config.response_json_schema is not None:
                return _Response(text=answer)
            return _Response(calls=[_call("get_rated_observation", {"session_id": "sess-1"})])

        with (
            patch("products.replay_vision.backend.prompt_suggestions._AGENT_BUDGET_INLINE_S", budget_s),
            patch("products.replay_vision.backend.prompt_suggestions.genai"),
            patch("products.replay_vision.backend.prompt_suggestions._model_call", side_effect=fake_model_call),
        ):
            parsed = _generate_agentic(
                scanner=self.scanner,
                user_content="briefing",
                user=self.user,
                allow_cold_summaries=False,
                distinct_id="test",
            )
        self.assertEqual(parsed.suggested_prompt, "better prompt")
        self.assertEqual(len(seen_contents), expected_model_calls)
        # The last user turn must answer the still-pending call, or Gemini rejects the conversation.
        final_turn = seen_contents[-1][-1]
        self.assertEqual(
            [p.function_response.name for p in final_turn.parts if p.function_response is not None],
            ["get_rated_observation"],
        )
        self.assertEqual(final_turn.parts[-1].text, "Respond now with the JSON answer.")

    def test_observation_tool_returns_full_detail_and_summary_tool_budgets_cold_runs(self) -> None:
        state = self._state()

        detail = _dispatch_agent_tool(state, _call("get_rated_observation", {"session_id": "sess-1"}))
        self.assertEqual(detail["rating"], "thumbs_down")
        self.assertEqual(detail["feedback"], "should be yes")
        self.assertEqual(detail["reasoning"], "the user closed the tab at payment")

        listing = _dispatch_agent_tool(state, _call("list_rated_sessions", {}))
        self.assertEqual(listing["total"], 1)
        self.assertEqual(listing["sessions"][0]["session_id"], "sess-1")

        summary = _dispatch_agent_tool(state, _call("get_session_summary", {"session_id": "sess-1"}))
        self.assertIn("error", summary)  # no cached summary, cold generation disallowed here

        cold_state = self._state(allow_cold_summaries=True, budget_s=600.0)
        cold_state.cold_summaries_used = _MAX_SUMMARIES_PER_RUN
        capped = _dispatch_agent_tool(cold_state, _call("get_session_summary", {"session_id": "sess-1"}))
        self.assertIn("budget", capped["error"])

        drained = self._state(allow_cold_summaries=True, budget_s=0.0)
        timed_out = _dispatch_agent_tool(drained, _call("get_session_summary", {"session_id": "sess-1"}))
        self.assertIn("time", timed_out["error"])

    def test_summary_tool_refuses_deleted_and_inaccessible_recordings(self) -> None:
        recording = SessionRecording.objects.create(team=self.team, session_id="sess-1", deleted=True)
        deleted = _dispatch_agent_tool(self._state(), _call("get_session_summary", {"session_id": "sess-1"}))
        self.assertIn("deleted", deleted["error"])

        recording.deleted = False
        recording.save()
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save()
        denied_user = User.objects.create_and_join(self.organization, "denied@posthog.com", "testtest")
        membership = OrganizationMembership.objects.get(user=denied_user, organization=self.organization)
        AccessControl.objects.create(
            team=self.team,
            resource="session_recording",
            resource_id=None,
            access_level="none",
            organization_member=membership,
        )
        denied_state = _AgentToolState(self.scanner, denied_user, False, time.monotonic() + 60.0)
        denied = _dispatch_agent_tool(denied_state, _call("get_session_summary", {"session_id": "sess-1"}))
        self.assertIn("not accessible", denied["error"])

        # Background refresh with no scanner creator: fail closed rather than serve cached summaries.
        userless_state = _AgentToolState(self.scanner, None, True, time.monotonic() + 600.0)
        userless = _dispatch_agent_tool(userless_state, _call("get_session_summary", {"session_id": "sess-1"}))
        self.assertIn("not accessible", userless["error"])

    def test_unknown_session_and_unknown_tool_return_errors(self) -> None:
        state = self._state()
        self.assertIn("error", _dispatch_agent_tool(state, _call("get_rated_observation", {"session_id": "nope"})))
        self.assertIn("error", _dispatch_agent_tool(state, _call("hack_the_planet", {})))
