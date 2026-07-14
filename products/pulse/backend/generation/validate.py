import re
import datetime as dt

from pydantic import ValidationError

from products.pulse.backend.generation.gate import CONFIDENCE_THRESHOLD, MAX_OPPORTUNITIES, apply_say_less_gate
from products.pulse.backend.generation.schemas import AgentBriefOut, BriefOut

# 6h grace: the deterministic window is pinned at prepare_mission time; the agent
# echoes it back. Anything beyond clock-skew-plus-run-duration is a fabricated window.
_WINDOW_TOLERANCE = dt.timedelta(hours=6)

# Rendered-markdown posture (brief sections ship to the frontend as markdown): strip
# non-http(s) URL schemes and prompt-framing markers that could smuggle instructions
# into rendered briefs or later prompt rounds.
_DANGEROUS_SCHEMES = ("javascript", "data", "vbscript", "file")
# Tolerate whitespace/control chars injected between scheme characters ("java\tscript:"): some
# renderers strip them before resolving the scheme, so a contiguous-token match is bypassable.
_SCHEME_SEP = r"[\s\x00-\x1f]*"
_DANGEROUS_SCHEMES_RE = "|".join(_SCHEME_SEP.join(re.escape(c) for c in scheme) for scheme in _DANGEROUS_SCHEMES)
# Dangerous scheme as a markdown link/image target — neutralize the whole target.
_DANGEROUS_LINK = re.compile(rf"\]\(\s*(?:{_DANGEROUS_SCHEMES_RE}):[^)]*\)", re.IGNORECASE)
# Bare dangerous-scheme URLs anywhere else (some renderers autolink these) — strip them.
# Guards against mangling ordinary prose: the lookbehind pins the scheme to a token start
# (so "metadata:"/"Profile:" survive) and the trailing `+` requires a non-space URL char right
# after the colon (so a label like "file: config.py" or "data: 42 users" survives). Only a bare
# autolinkable "javascript:alert(...)"/"data:text/html,..." at a word start is stripped.
_BARE_DANGEROUS_SCHEME = re.compile(rf"(?<![A-Za-z0-9])(?:{_DANGEROUS_SCHEMES_RE}):[^\s)\]]+", re.IGNORECASE)
_FRAMING_MARKERS = re.compile(r"</?\s*(?:system|assistant|team_focus|instructions|tool_call)\s*>", re.IGNORECASE)
# Keys must sit under this run's own object-storage namespace — no traversal, no foreign briefs.
_ARTIFACT_KEY = re.compile(r"^pulse/briefs/[0-9]+/[0-9a-f-]+/[A-Za-z0-9._-][A-Za-z0-9._/-]*$")


class AgentReportInvalid(Exception):
    pass


def sanitize_markdown(text: str) -> str:
    text = _DANGEROUS_LINK.sub("](#)", text)
    text = _BARE_DANGEROUS_SCHEME.sub("", text)
    return _FRAMING_MARKERS.sub("", text)


def _check_window(out: AgentBriefOut, window_start: dt.datetime, window_end: dt.datetime) -> None:
    if abs(out.window_start - window_start) > _WINDOW_TOLERANCE or abs(out.window_end - window_end) > _WINDOW_TOLERANCE:
        raise AgentReportInvalid(
            f"Report window [{out.window_start}, {out.window_end}] does not match the "
            f"mission window [{window_start}, {window_end}]"
        )


def validate_agent_report(
    report: dict,
    *,
    window_start: dt.datetime,
    window_end: dt.datetime,
    has_goal: bool = False,
    confidence_threshold: float = CONFIDENCE_THRESHOLD,
    max_opportunities: int = MAX_OPPORTUNITIES,
) -> AgentBriefOut:
    try:
        out = AgentBriefOut.model_validate(report)
    except ValidationError as err:
        raise AgentReportInvalid(f"Agent report failed schema validation: {err}") from err
    _check_window(out, window_start, window_end)
    for key in out.artifacts:
        # `..` as a path component would pass the namespace regex but enable traversal if a key
        # ever reaches a filesystem or a dot-normalizing store — reject it explicitly.
        if not _ARTIFACT_KEY.match(key) or ".." in key.split("/"):
            raise AgentReportInvalid(f"Artifact key outside the pulse namespace: {key!r}")
    opportunities = out.opportunities
    if not has_goal:
        # Mirror synthesize's goalless zeroing: a goalless brief must not reorder by goal_relevant
        # (and persist drops proposals on non-goal-relevant opportunities).
        opportunities = [o.model_copy(update={"goal_relevant": False}) for o in opportunities]
    gated = apply_say_less_gate(
        BriefOut(sections=out.sections, opportunities=opportunities),
        confidence_threshold=confidence_threshold,
        max_opportunities=max_opportunities,
    )
    # Titles are untrusted free text too: sanitize them alongside body markdown so framing/XSS
    # markers can't reach stored JSON or downstream prompts.
    return AgentBriefOut(
        sections=[
            s.model_copy(update={"title": sanitize_markdown(s.title), "markdown": sanitize_markdown(s.markdown)})
            for s in gated.sections
        ],
        opportunities=[
            o.model_copy(
                update={
                    "title": sanitize_markdown(o.title),
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
