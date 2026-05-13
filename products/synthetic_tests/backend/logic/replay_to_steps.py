"""
Convert a session recording into a draft synthetic test step list.

Hackathon scope:
- If an LLM provider is wired up (ANTHROPIC_API_KEY present), call it with a constrained
  JSON output schema asking it to convert rrweb events + element chain data into steps.
- Otherwise, return a heuristic stub derived from the recording's first navigation +
  a short canned demo step list, so the wedge demo works without external creds.

The returned shape matches GenerateFromReplayResponseSerializer.
"""

import os
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


def generate_steps_from_replay(*, team_id: int, session_recording_id: str) -> dict[str, Any]:
    """
    Build a draft synthetic test from a session recording.

    Returns a dict matching GenerateFromReplayResponseSerializer: { name, target_url, steps }.
    """
    recording_summary = _fetch_recording_summary(team_id=team_id, session_recording_id=session_recording_id)

    if _has_llm():
        try:
            return _generate_via_llm(recording_summary)
        except Exception as exc:  # noqa: BLE001 — fall back to heuristic so the demo never blocks
            logger.warning("synthetic_test_llm_generation_failed", error=str(exc))

    return _generate_heuristic(recording_summary, session_recording_id)


def _fetch_recording_summary(*, team_id: int, session_recording_id: str) -> dict[str, Any]:
    """
    Minimum viable summary of a recording for step generation.

    For the hackathon MVP this returns a stub. A production version would call into
    posthog.session_recordings.session_recording_api to pull the snapshot blob and
    surface inferred clicks/typed values/navigations to the LLM.
    """
    return {
        "team_id": team_id,
        "session_recording_id": session_recording_id,
        "target_url": "https://us.posthog.com/signup",
        "title": "PostHog Cloud signup",
    }


def _has_llm() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def _generate_via_llm(_summary: dict[str, Any]) -> dict[str, Any]:
    """
    Placeholder for the real LLM call. The production version would:
      1. Hydrate rrweb events + element chains from the recording snapshot blob.
      2. Send to Claude with a structured-output schema constraining the response to our step types.
      3. Validate and return.

    For the MVP, this branch is intentionally never reached unless the env is configured;
    we route through the heuristic below to keep the demo deterministic.
    """
    raise NotImplementedError("LLM-backed generation is wired but disabled in the hackathon MVP")


def _generate_heuristic(summary: dict[str, Any], session_recording_id: str) -> dict[str, Any]:
    """Canned demo steps that match the PostHog Cloud signup flow."""
    target_url = summary.get("target_url") or "https://us.posthog.com/signup"
    name = f"Test from {summary.get('title', 'replay')} · {session_recording_id[:8]}"
    steps: list[dict[str, Any]] = [
        {"type": "navigate", "url": target_url},
        {"type": "wait_for_selector", "selector": "[data-attr=signup-email]"},
        {"type": "type", "selector": "[data-attr=signup-email]", "value": "test+synth@posthog.com"},
        {"type": "type", "selector": "[data-attr=signup-password]", "value": "Hackathon123!"},
        {"type": "click", "selector": "[data-attr=signup-submit]"},
        {"type": "wait_for_selector", "selector": "[data-attr=onboarding-step-platform]"},
        {"type": "assert_url_contains", "value": "/onboarding"},
    ]
    return {"name": name, "target_url": target_url, "steps": steps}
