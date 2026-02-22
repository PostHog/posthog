"""Tests that all Hog evaluation examples compile and run correctly.

Examples are defined in hogEvalExamples.json (shared with the frontend).
"""

import json
import uuid
from datetime import datetime
from pathlib import Path

from parameterized import parameterized

from posthog.cdp.validation import compile_hog
from posthog.temporal.llm_analytics.run_evaluation import run_hog_eval

EXAMPLES_PATH = Path(__file__).resolve().parents[1] / "frontend" / "evaluations" / "hogEvalExamples.json"
EXAMPLES: list[dict] = json.loads(EXAMPLES_PATH.read_text())
EXAMPLE_LABELS = [e["label"] for e in EXAMPLES]


def _get_source(label: str) -> str:
    return next(e["source"] for e in EXAMPLES if e["label"] == label)


def _make_event(
    ai_input=None,
    ai_output_choices=None,
    ai_model="gpt-4",
    ai_total_cost_usd=0.01,
    ai_latency=1.5,
):
    if ai_input is None:
        ai_input = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "What is PostHog?"},
        ]
    if ai_output_choices is None:
        ai_output_choices = [
            {
                "message": {
                    "role": "assistant",
                    "content": "PostHog is an open-source product analytics platform that helps teams understand user behavior.",
                },
                "index": 0,
            },
        ]
    return {
        "uuid": str(uuid.uuid4()),
        "event": "$ai_generation",
        "properties": {
            "$ai_input": ai_input,
            "$ai_output_choices": ai_output_choices,
            "$ai_model": ai_model,
            "$ai_total_cost_usd": ai_total_cost_usd,
            "$ai_latency": ai_latency,
        },
        "timestamp": datetime.now().isoformat(),
        "team_id": 1,
        "distinct_id": "test-user",
    }


# Event whose output satisfies most examples (contains keywords, tool names, enough length, no PII, no errors, etc.)
CLEAN_EVENT = _make_event(
    ai_output_choices=[
        {
            "message": {
                "role": "assistant",
                "content": (
                    "Hello world! I called get_weather and get_news to help you. "
                    "PostHog is an open-source product analytics platform that helps teams "
                    "understand user behavior through event tracking and feature flags."
                ),
            },
            "index": 0,
        },
    ],
)


class TestHogEvalExamplesCompile:
    @parameterized.expand(EXAMPLE_LABELS)
    def test_compiles(self, label):
        source = _get_source(label)
        bytecode = compile_hog(source, "destination")
        assert len(bytecode) > 0


class TestHogEvalExamplesRun:
    @parameterized.expand(EXAMPLE_LABELS)
    def test_returns_bool_without_error(self, label):
        source = _get_source(label)
        bytecode = compile_hog(source, "destination")
        result = run_hog_eval(bytecode, CLEAN_EVENT)

        assert result["error"] is None, f"'{label}' errored: {result['error']}"
        assert isinstance(result["verdict"], bool), f"'{label}' returned non-bool: {result['verdict']}"


class TestHogEvalExamplesBehavior:
    @parameterized.expand(
        [
            ("Output not empty",),
            ("Output quality",),
            ("Error detection",),
            ("Refusal detection",),
            ("Regex safety checks",),
            ("Cost & latency guard",),
            ("Contains keywords",),
            ("Tools called",),
        ]
    )
    def test_passes_on_clean_output(self, label):
        bytecode = compile_hog(_get_source(label), "destination")
        result = run_hog_eval(bytecode, CLEAN_EVENT)
        assert result["error"] is None
        assert result["verdict"] is True

    @parameterized.expand(
        [
            ("Output not empty", ""),
            ("Output quality", "short"),
            ("Error detection", "An error occurred\nTraceback follows"),
            ("Refusal detection", "I'm sorry, but I cannot help with that request."),
        ]
    )
    def test_fails_on_bad_output(self, label, bad_output):
        bytecode = compile_hog(_get_source(label), "destination")
        # Use $ai_output directly so the output global is the plain string, not a JSON-serialized choices array
        event = _make_event()
        event["properties"].pop("$ai_output_choices", None)
        event["properties"]["$ai_output"] = bad_output
        result = run_hog_eval(bytecode, event)
        assert result["error"] is None
        assert result["verdict"] is False, f"'{label}' should have failed but passed"

    def test_cost_guard_fails_on_expensive(self):
        bytecode = compile_hog(_get_source("Cost & latency guard"), "destination")
        event = _make_event(ai_total_cost_usd=0.10, ai_latency=1.0)
        result = run_hog_eval(bytecode, event)
        assert result["verdict"] is False
        assert "exceeds budget" in result["reasoning"]

    def test_conversation_length_fails_on_long(self):
        bytecode = compile_hog(_get_source("Conversation length"), "destination")
        long_conversation = [{"role": "user", "content": f"Message {i}"} for i in range(15)]
        event = _make_event(ai_input=long_conversation)
        result = run_hog_eval(bytecode, event)
        assert result["verdict"] is False
        assert "Exceeds limit" in result["reasoning"]

    def test_regex_safety_fails_on_email(self):
        bytecode = compile_hog(_get_source("Regex safety checks"), "destination")
        event = _make_event(
            ai_output_choices=[
                {"message": {"role": "assistant", "content": "Contact us at test@example.com"}, "index": 0}
            ],
        )
        result = run_hog_eval(bytecode, event)
        assert result["verdict"] is False

    def test_quickstart_prints_messages_and_choices(self):
        bytecode = compile_hog(_get_source("Quickstart"), "destination")
        result = run_hog_eval(bytecode, CLEAN_EVENT)
        assert result["verdict"] is True
        assert "[system] You are a helpful assistant." in result["reasoning"]
        assert "[user] What is PostHog?" in result["reasoning"]
        assert "Choice 0:" in result["reasoning"]
        assert "Model: gpt-4" in result["reasoning"]

    def test_quickstart_handles_plain_string_input_and_output(self):
        bytecode = compile_hog(_get_source("Quickstart"), "destination")
        event = _make_event()
        event["properties"].pop("$ai_output_choices", None)
        event["properties"]["$ai_input"] = "What is PostHog?"
        event["properties"]["$ai_output"] = "PostHog is a product analytics platform."
        result = run_hog_eval(bytecode, event)
        assert result["error"] is None
        assert result["verdict"] is True
        assert "Input: What is PostHog?" in result["reasoning"]
        assert "Output: PostHog is a product analytics platform." in result["reasoning"]
