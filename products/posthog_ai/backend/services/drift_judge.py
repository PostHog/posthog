"""Structured-output drift judge.

Takes Max's "what has changed" narrative and returns a strict-JSON verdict on whether the
drift is material enough to emit a Signal. Implementation is intentionally small so that the
judge can be swapped for a deterministic or rules-based variant in tests.
"""

from dataclasses import dataclass
from typing import Any, Literal

import structlog

logger = structlog.get_logger(__name__)


JUDGE_SYSTEM_PROMPT = """\
You are judging whether a PostHog AI drift report describes a materially changed metric.

Material = a business-relevant shift in the headline metric, a clear shape change in a curve,
a meaningful funnel-step regression, a category becoming dominant or vanishing, or a sustained
directional move. Day-of-week wiggle, sub-percent drift on noisy metrics, and "I couldn't tell"
are NOT material.

Return strict JSON matching this schema:
{
  "drift_detected": boolean,
  "severity": "none" | "minor" | "moderate" | "significant",
  "summary": string  // 1-2 sentences for the watched-questions UI list
}
"""


Severity = Literal["none", "minor", "moderate", "significant"]


@dataclass
class DriftJudgement:
    drift_detected: bool
    severity: Severity
    summary: str
    payload: dict[str, Any]

    @property
    def is_emit_worthy(self) -> bool:
        return self.drift_detected and self.severity in ("moderate", "significant")


def judge_drift(narrative: str) -> DriftJudgement:
    """Call the LLM-backed judge and parse its response. Falls back to a conservative no-drift
    verdict on any failure so that a flaky judge never floods the PR pipeline.
    """
    if not narrative or not narrative.strip():
        return DriftJudgement(
            drift_detected=False,
            severity="none",
            summary="No narrative produced by the chat agent — skipping.",
            payload={},
        )

    try:
        from ee.hogai.llm import MaxChatLLM  # type: ignore[import-not-found]
    except Exception:  # pragma: no cover - import-time fallback
        MaxChatLLM = None  # type: ignore[assignment]

    if MaxChatLLM is None:
        logger.warning("MaxChatLLM unavailable; returning conservative no-drift verdict.")
        return DriftJudgement(
            drift_detected=False,
            severity="none",
            summary="Drift judge offline; deferred to next run.",
            payload={"reason": "llm_unavailable"},
        )

    try:
        llm = MaxChatLLM(model="claude-haiku-4-5-20251001", temperature=0.0)
        response_payload = llm.complete_structured(
            system_prompt=JUDGE_SYSTEM_PROMPT,
            user_prompt=narrative,
            schema={
                "type": "object",
                "required": ["drift_detected", "severity", "summary"],
                "properties": {
                    "drift_detected": {"type": "boolean"},
                    "severity": {
                        "type": "string",
                        "enum": ["none", "minor", "moderate", "significant"],
                    },
                    "summary": {"type": "string", "maxLength": 600},
                },
                "additionalProperties": False,
            },
        )
    except Exception:
        logger.exception("Drift judge LLM call failed; returning conservative no-drift verdict.")
        return DriftJudgement(
            drift_detected=False,
            severity="none",
            summary="Drift judge errored; deferred to next run.",
            payload={"reason": "llm_error"},
        )

    payload = response_payload or {}
    severity: Severity = payload.get("severity", "none")  # type: ignore[assignment]
    if severity not in ("none", "minor", "moderate", "significant"):
        severity = "none"
    return DriftJudgement(
        drift_detected=bool(payload.get("drift_detected", False)),
        severity=severity,
        summary=str(payload.get("summary", "")).strip(),
        payload=payload,
    )
