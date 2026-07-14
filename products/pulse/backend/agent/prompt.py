"""Renders a MissionBundle into the agent's first user_message.

The durable playbook half of the mission ships as a skill in the sandbox image;
this prompt carries only the run-specific bundle plus the output contract.
"""

import json

from posthog.security.llm_prompt_sanitization import sanitize_user_text

from products.pulse.backend.agent.mission import MissionBundle

REPORT_PATH = "/tmp/pulse/report.json"

_MISSION_TEMPLATE = """You are the PostHog pulse analyst agent. Load and follow your `pulse-general-brief` skill playbook.

<team_focus>
{focus_prompt}
</team_focus>

Observation window (frozen — every number you report must come from this window):
window_start: {window_start}
window_end: {window_end}
lookback_days: {lookback_days}

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
        # Angle brackets neutralized, so the <team_focus> fence cannot be broken out of
        # (same posture as the synthesize prompt via sanitize_user_text).
        focus_prompt=sanitize_user_text(bundle.focus_prompt, max_len=2000),
        window_start=bundle.window_start.isoformat(),
        window_end=bundle.window_end.isoformat(),
        lookback_days=bundle.lookback_days,
        seeds_block=json.dumps(bundle.seed_items, indent=2, default=str),
        report_path=REPORT_PATH,
        max_opportunities=bundle.max_opportunities,
    )
