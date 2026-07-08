"""Trusted-side validation of untrusted agent output (spec principle 1:
the trust boundary is the activity edge). Reject, never silently repair."""

import re
import datetime as dt

from pydantic import ValidationError

from products.pulse.backend.generation.gate import apply_say_less_gate
from products.pulse.backend.generation.schemas import AgentBriefOut, BriefOut

# 6h grace: the deterministic window is pinned at prepare_mission time; the agent
# echoes it back. Anything beyond clock-skew-plus-run-duration is a fabricated window.
_WINDOW_TOLERANCE = dt.timedelta(hours=6)

# Rendered-markdown posture (brief sections ship to the frontend as markdown): strip
# non-http(s) URL schemes and prompt-framing markers that could smuggle instructions
# into rendered briefs or later prompt rounds.
_DANGEROUS_URL = re.compile(r"\]\(\s*(?:javascript|data|vbscript|file):[^)]*\)", re.IGNORECASE)
_FRAMING_MARKERS = re.compile(r"</?\s*(?:system|assistant|team_focus|instructions|tool_call)\s*>", re.IGNORECASE)
# Keys must sit under this run's own object-storage namespace — no traversal, no foreign briefs.
_ARTIFACT_KEY = re.compile(r"^pulse/briefs/[0-9]+/[0-9a-f-]+/[A-Za-z0-9._-][A-Za-z0-9._/-]*$")


class AgentReportInvalid(Exception):
    pass


def sanitize_markdown(text: str) -> str:
    text = _DANGEROUS_URL.sub("](#)", text)
    return _FRAMING_MARKERS.sub("", text)


def _check_window(out: AgentBriefOut, window_start: dt.datetime, window_end: dt.datetime) -> None:
    if abs(out.window_start - window_start) > _WINDOW_TOLERANCE or abs(out.window_end - window_end) > _WINDOW_TOLERANCE:
        raise AgentReportInvalid(
            f"Report window [{out.window_start}, {out.window_end}] does not match the "
            f"mission window [{window_start}, {window_end}]"
        )


def validate_agent_report(report: dict, *, window_start: dt.datetime, window_end: dt.datetime) -> AgentBriefOut:
    try:
        out = AgentBriefOut.model_validate(report)
    except ValidationError as err:
        raise AgentReportInvalid(f"Agent report failed schema validation: {err}") from err
    _check_window(out, window_start, window_end)
    for key in out.artifacts:
        if not _ARTIFACT_KEY.match(key):
            raise AgentReportInvalid(f"Artifact key outside the pulse namespace: {key!r}")
    gated = apply_say_less_gate(BriefOut(sections=out.sections, opportunities=out.opportunities))
    return AgentBriefOut(
        sections=[s.model_copy(update={"markdown": sanitize_markdown(s.markdown)}) for s in gated.sections],
        opportunities=[
            o.model_copy(
                update={
                    "summary": sanitize_markdown(o.summary),
                    "suggested_action": sanitize_markdown(o.suggested_action),
                }
            )
            for o in gated.opportunities
        ],
        window_start=out.window_start,
        window_end=out.window_end,
        artifacts=out.artifacts,
    )
