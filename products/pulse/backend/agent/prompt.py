"""Renders a MissionBundle into the agent's first user_message.

The durable playbook half of the mission ships as a skill in the sandbox image;
this prompt carries only the run-specific bundle plus the output contract.
"""

import json

from products.pulse.backend.agent.mission import GENERAL_BRIEF_MISSION, QUERY_PERFORMANCE_MISSION, MissionBundle
from products.pulse.backend.generation.prompts import sanitize_for_prompt

REPORT_PATH = "/tmp/pulse/report.json"

# Which sandbox-image skill carries the playbook half of each mission.
MISSION_SKILLS: dict[str, str] = {
    GENERAL_BRIEF_MISSION: "pulse-general-brief",
    QUERY_PERFORMANCE_MISSION: "pulse-query-performance",
}

_MISSION_TEMPLATE = """You are the PostHog pulse analyst agent. Load and follow your `{skill_name}` skill playbook.

<team_focus>
{focus_prompt}
</team_focus>

Observation window (frozen — every number you report must come from this window):
window_start: {window_start}
window_end: {window_end}
period_days: {period_days}

Seed observations from the deterministic scan (start here; investigate with your PostHog MCP tools, and compute — correlation, significance — where it strengthens a claim):
{seeds_block}

Output contract — when done, write EXACTLY ONE JSON object to {report_path} (create the directory) with this shape and nothing else on stdout:
{{
  "sections": [{{"kind": str, "title": str, "markdown": str, "citations": [str], "confidence": float}}],
  "opportunities": [{{"kind": "build"|"fix"|"instrument", "title": str, "summary": str, "suggested_action": str, "evidence_refs": [str], "fingerprint_hint": str, "confidence": float}}],
  "window_start": "{window_start}",
  "window_end": "{window_end}",
  "artifacts": []
}}
At most {max_opportunities} opportunities. Copy fingerprint_hint values from seed observations verbatim when an opportunity derives from one. Say less: omit anything you are not confident in."""


def render_mission_prompt(bundle: MissionBundle) -> str:
    return _MISSION_TEMPLATE.format(
        skill_name=MISSION_SKILLS[bundle.mission],
        # Angle brackets neutralized, so the <team_focus> fence cannot be broken out of
        # (same posture as SYNTHESIZE_PROMPT in generation/synthesize.py).
        focus_prompt=sanitize_for_prompt(bundle.focus_prompt),
        window_start=bundle.window_start.isoformat(),
        window_end=bundle.window_end.isoformat(),
        period_days=bundle.period_days,
        seeds_block=json.dumps(bundle.seed_items, indent=2, default=str),
        report_path=REPORT_PATH,
        max_opportunities=bundle.max_opportunities,
    )
