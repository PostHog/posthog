import json
from typing import Any

from unittest.mock import patch

from django.utils import timezone

from google.genai import types
from parameterized import parameterized

from products.replay_vision.backend.models.replay_observation import (
    ObservationStatus,
    ObservationTrigger,
    ReplayObservation,
)
from products.replay_vision.backend.models.replay_observation_label import ReplayObservationLabel
from products.replay_vision.backend.prompt_suggestions import _MAX_TOOL_ROUNDS, _dispatch_agent_tool, _generate_agentic
from products.replay_vision.backend.proposers import get_proposer
from products.replay_vision.backend.tests.test_api import _VisionAPITestCase


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
        # The scanner defaults to monitor; its proposer supplies the system prompt and schema the agent needs.
        self.proposer = get_proposer("monitor")

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
                budget_s=60.0,
                distinct_id="test",
                system_prompt=self.proposer.system_prompt(),
                output_schema=self.proposer.output_schema(),
            )
        self.assertEqual(parsed["suggested_prompt"], "better prompt")

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
            patch("products.replay_vision.backend.prompt_suggestions.genai"),
            patch("products.replay_vision.backend.prompt_suggestions._model_call", side_effect=fake_model_call),
        ):
            parsed = _generate_agentic(
                scanner=self.scanner,
                user_content="briefing",
                budget_s=budget_s,
                distinct_id="test",
                system_prompt=self.proposer.system_prompt(),
                output_schema=self.proposer.output_schema(),
            )
        self.assertEqual(parsed["suggested_prompt"], "better prompt")
        self.assertEqual(len(seen_contents), expected_model_calls)
        # The last user turn must answer the still-pending call, or Gemini rejects the conversation.
        final_turn = seen_contents[-1][-1]
        self.assertEqual(
            [p.function_response.name for p in final_turn.parts if p.function_response is not None],
            ["get_rated_observation"],
        )
        self.assertEqual(final_turn.parts[-1].text, "Respond now with the JSON answer.")

    def test_observation_tools_return_full_detail_and_the_rated_session_listing(self) -> None:

        detail = _dispatch_agent_tool(self.scanner, _call("get_rated_observation", {"session_id": "sess-1"}))
        self.assertEqual(detail["rating"], "thumbs_down")
        self.assertEqual(detail["feedback"], "should be yes")
        self.assertEqual(detail["reasoning"], "the user closed the tab at payment")

        listing = _dispatch_agent_tool(self.scanner, _call("list_rated_sessions", {}))
        self.assertEqual(listing["total"], 1)
        self.assertEqual(listing["sessions"][0]["session_id"], "sess-1")

    def test_tools_only_see_the_ratings_of_the_scanner_under_review(self) -> None:
        # The scanner_id filter is the only thing keeping one scanner's rated sessions out of another's
        # calibration briefing, and the rated set is what the rewrite is derived from.
        other_scanner = self._create_scanner(name="other-scanner")
        other = ReplayObservation.objects.create(
            scanner=other_scanner,
            team=self.team,
            session_id="sess-1",
            status=ObservationStatus.SUCCEEDED,
            completed_at=timezone.now(),
            triggered_by=ObservationTrigger.ON_DEMAND,
            scanner_snapshot={"scanner_version": 1},
            scanner_result={"model_output": {"verdict": "yes", "scanner_type": "monitor"}, "signals_count": 0},
        )
        ReplayObservationLabel.objects.create(observation=other, is_correct=True, feedback="looks right")

        self.assertEqual(_dispatch_agent_tool(self.scanner, _call("list_rated_sessions", {}))["total"], 1)
        detail = _dispatch_agent_tool(self.scanner, _call("get_rated_observation", {"session_id": "sess-1"}))
        self.assertEqual(detail["rating"], "thumbs_down")  # this scanner's rating, not the other's thumbs up

    def test_unknown_session_and_unknown_tool_return_errors(self) -> None:
        self.assertIn(
            "error", _dispatch_agent_tool(self.scanner, _call("get_rated_observation", {"session_id": "nope"}))
        )
        self.assertIn("error", _dispatch_agent_tool(self.scanner, _call("hack_the_planet", {})))
