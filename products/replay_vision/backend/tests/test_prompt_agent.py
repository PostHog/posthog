import json

from unittest.mock import patch

from django.utils import timezone

from products.replay_vision.backend.models.replay_observation import (
    ObservationStatus,
    ObservationTrigger,
    ReplayObservation,
)
from products.replay_vision.backend.models.replay_observation_label import ReplayObservationLabel
from products.replay_vision.backend.prompt_suggestions import (
    _MAX_SUMMARIES_PER_RUN,
    _AgentToolState,
    _dispatch_agent_tool,
    _generate_agentic,
)
from products.replay_vision.backend.tests.test_api import _VisionAPITestCase


class _Call:
    def __init__(self, name: str, args: dict) -> None:
        self.name = name
        self.args = args


class _Candidate:
    def __init__(self) -> None:
        self.content = "model-turn"


class _Response:
    def __init__(self, *, calls: list[_Call] | None = None, text: str = "") -> None:
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

    def test_tool_rounds_run_then_final_structured_answer_parses(self) -> None:
        answer = json.dumps({"suggested_prompt": "better prompt", "rationale": "grounded in sess-1"})
        responses = iter(
            [
                _Response(calls=[_Call("get_rated_observation", {"session_id": "sess-1"})]),
                _Response(),  # model is done with tools
                _Response(text=answer),  # forced structured turn
            ]
        )
        with patch(
            "products.replay_vision.backend.prompt_suggestions._model_call",
            side_effect=lambda *a, **k: next(responses),
        ):
            parsed = _generate_agentic(
                scanner=self.scanner,
                user_content="briefing",
                user=self.user,
                allow_cold_summaries=False,
                distinct_id="test",
            )
        self.assertEqual(parsed.suggested_prompt, "better prompt")

    def test_observation_tool_returns_full_detail_and_summary_tool_respects_budget(self) -> None:
        state = _AgentToolState(self.scanner, self.user, allow_cold_summaries=False)

        detail = _dispatch_agent_tool(state, _Call("get_rated_observation", {"session_id": "sess-1"}))
        self.assertEqual(detail["rating"], "thumbs_down")
        self.assertEqual(detail["feedback"], "should be yes")
        self.assertEqual(detail["reasoning"], "the user closed the tab at payment")

        listing = _dispatch_agent_tool(state, _Call("list_rated_sessions", {}))
        self.assertEqual(listing["total"], 1)
        self.assertEqual(listing["sessions"][0]["session_id"], "sess-1")

        # No cached summary and cold generation disallowed: a clear error, not a workflow launch.
        summary = _dispatch_agent_tool(state, _Call("get_session_summary", {"session_id": "sess-1"}))
        self.assertIn("error", summary)

        # Budget exhaustion is reported once the cap is hit.
        state.summaries_used = _MAX_SUMMARIES_PER_RUN
        capped = _dispatch_agent_tool(state, _Call("get_session_summary", {"session_id": "sess-1"}))
        self.assertIn("budget", capped["error"])

    def test_unknown_session_and_unknown_tool_return_errors(self) -> None:
        state = _AgentToolState(self.scanner, self.user, allow_cold_summaries=False)
        self.assertIn("error", _dispatch_agent_tool(state, _Call("get_rated_observation", {"session_id": "nope"})))
        self.assertIn("error", _dispatch_agent_tool(state, _Call("hack_the_planet", {})))
