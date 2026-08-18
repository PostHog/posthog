"""Prompts that hand one recording moment to a scout instead of to report research.

A scout's real prompt is the harness system prompt plus a skill body the agent fetches over the
skills MCP at run time. Neither is available in the eval sandbox, so a case can't be a full scout
run. What it can be is the part that changed: the attribution section of the scout's own
``SKILL.md``, read off disk verbatim, in front of a finding the scout has already validated.

Reading the section rather than restating it means the eval fails loudly when someone deletes or
renames it, instead of scoring a copy that drifted away from what ships to teams.
"""

from __future__ import annotations

import re
from pathlib import Path

from products.signals.evals.constants import HEDGEBOX_ORIGIN, ScoutAttributionCase

__all__ = ["build_scout_prompt", "skill_section"]

_SKILLS_DIR = Path(__file__).resolve().parent.parent / "skills"
_SKILL_BY_SCOUT = {
    "session_replay": "signals-scout-session-replay",
    "replay_vision": "signals-scout-replay-vision",
}
_SECTION_BY_SCOUT = {
    "session_replay": "#### Name the code behind the surface",
    "replay_vision": "#### Anchor a finding in code",
}
_HEADING_RE = re.compile(r"^#{1,6} ", re.MULTILINE)

_ANSWER_CONTRACT = """Answer with one JSON object and nothing else:

```json
{
  "anchor": "the single string a reader would grep the source for, or null if you found none",
  "tier": "exception | identifier | text | route",
  "element_known": true
}
```

Set `element_known` to false when no element backs the moment."""


class SkillSectionMissingError(LookupError):
    """The scout body no longer carries the section these cases score."""


def skill_section(scout: str) -> str:
    """The attribution section of a scout's `SKILL.md`, verbatim, without its heading."""
    skill_file = _SKILLS_DIR / _SKILL_BY_SCOUT[scout] / "SKILL.md"
    body = skill_file.read_text()
    heading = _SECTION_BY_SCOUT[scout]
    start = body.find(f"{heading}\n")
    if start == -1:
        raise SkillSectionMissingError(f"{skill_file} has no section titled {heading!r}")
    rest = body[start + len(heading) :]
    following = _HEADING_RE.search(rest)
    return rest[: following.start() if following else len(rest)].strip()


def _session_replay_brief(case: ScoutAttributionCase) -> str:
    moment = case.moment
    return f"""You are the PostHog signals session-replay scout, part way through a run.

You have already corroborated a friction cluster and you are about to author the report. What it
is missing is the code: it names a page, and nothing else. You are running headless, with this
project's data over the PostHog MCP and no checkout, so the answer has to come out of the events.

- Host: `{HEDGEBOX_ORIGIN}`
- Path: `{moment.pathname}`
- Example sessions you shortlisted: `{moment.session_id}`
- What the recordings show: {moment.description}

Work out what the report should name as the code behind this surface."""


def _replay_vision_brief(case: ScoutAttributionCase) -> str:
    moment = case.moment
    return f"""You are the PostHog signals replay-vision scout, part way through a run.

You have already validated an aggregate shift on one scanner and you are about to author the
report. Its example findings each carry a moment in a recording, and no file. You are running
headless, with this project's data over the PostHog MCP and no checkout, so the answer has to
come out of the events.

- Scanner: `Broken flows` (monitor)
- Example observation: `session_id` `{moment.session_id}`, with `signal_finding_rec_ts` of `[{moment.start_time}]`
- What the scanner reported at that moment: {moment.description}

Work out what the report should name as the code behind that finding."""


_BRIEF_BY_SCOUT = {
    "session_replay": _session_replay_brief,
    "replay_vision": _replay_vision_brief,
}


def build_scout_prompt(case: ScoutAttributionCase) -> str:
    """The brief, the scout's own attribution guidance, and the answer contract."""
    return "\n\n".join(
        (
            _BRIEF_BY_SCOUT[case.scout](case),
            "Your skill tells you how to do this:",
            skill_section(case.scout),
            _ANSWER_CONTRACT,
        )
    )
