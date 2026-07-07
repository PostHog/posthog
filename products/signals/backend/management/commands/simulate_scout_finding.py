"""Post a simulated scout finding to a team's configured Slack delivery channel.

Exercises the exact compose+send path the scout's `notify` tool uses
(`scout_harness.slack_delivery.send_scout_slack_notification`) without spawning a
sandboxed LLM run — the fastest way to verify Slack channel delivery locally after
CSM onboarding has provisioned scout configs. Creates no `SignalScoutRun`/`TaskRun`
rows and appends no run audit; the alert's context line is labeled as simulated.
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from products.signals.backend.models import SignalScoutConfig
from products.signals.backend.scout_harness.slack_delivery import ScoutSlackDeliveryError, send_scout_slack_notification

DEFAULT_SKILL_NAME = "signals-scout-slack-csm-account-pulse"
DEFAULT_ACCOUNT_NAME = "Acme Corp (simulated)"
DEFAULT_TEXT = (
    "Weekly active users dropped 42% over the last 14 days (318 → 184), and the dashboards feature "
    "that anchored the last renewal conversation has gone quiet. Error rates are flat over the same "
    "window, so this reads as disengagement rather than breakage. Worth a check-in this week to ask "
    "what changed before it surfaces in the renewal call."
)
SIMULATION_CONTEXT_LABEL = "Simulated finding — sent by `simulate_scout_finding` for testing"

_REMEDIATION_HINTS = {
    "slack_integration_missing": (
        "The integration id in delivery_config no longer exists — reconnect Slack for this team and "
        "re-run CSM onboarding (provision_persona_scouts) to rewrite the delivery target."
    ),
    "channel_unavailable": (
        "Invite the PostHog Slack bot to the configured channel, or re-run CSM onboarding to pick a "
        "channel the bot can post to."
    ),
}


class Command(BaseCommand):
    help = "Post a simulated scout finding to the team's configured Slack channel (no LLM run)."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--team-id", type=int, required=True)
        parser.add_argument("--skill-name", default=DEFAULT_SKILL_NAME)
        parser.add_argument("--account-name", default=DEFAULT_ACCOUNT_NAME)
        parser.add_argument("--text", default=DEFAULT_TEXT)
        parser.add_argument("--owner-email", default=None)
        parser.add_argument("--severity", choices=["low", "medium", "high"], default="medium")

    def handle(self, *args: Any, **options: Any) -> None:
        team_id: int = options["team_id"]
        skill_name: str = options["skill_name"]

        config = SignalScoutConfig.objects.for_team(team_id).filter(skill_name=skill_name).first()
        if config is None:
            raise CommandError(
                f"No SignalScoutConfig for skill {skill_name!r} on team {team_id}. Run CSM onboarding "
                "(provision_persona_scouts in products/signals/backend/facade/api.py) to provision it, "
                "or pass --skill-name for a scout this team has configured."
            )
        delivery = (config.delivery_config or {}).get("slack") or {}
        if not delivery.get("integration_id") or not delivery.get("channel_id"):
            raise CommandError(
                f"Scout {skill_name!r} on team {team_id} has no Slack delivery channel configured. "
                'CSM onboarding (provision_persona_scouts) writes delivery_config["slack"] — complete '
                "the channel-setup step there first."
            )

        try:
            result = send_scout_slack_notification(
                config=config,
                team_id=team_id,
                text=options["text"],
                account_name=options["account_name"],
                context_label=SIMULATION_CONTEXT_LABEL,
                owner_email=options["owner_email"],
                severity=options["severity"],
                run=None,
            )
        except ScoutSlackDeliveryError as exc:
            message = f"Delivery failed ({exc.code}): {exc}"
            hint = _REMEDIATION_HINTS.get(exc.code)
            if hint:
                message += f"\nHint: {hint}"
            raise CommandError(message)

        self.stdout.write(self.style.SUCCESS(f"Simulated finding delivered to {result.channel}"))
        self.stdout.write(f"  ts:           {result.ts}")
        self.stdout.write(f"  owner_tagged: {result.owner_tagged}")
