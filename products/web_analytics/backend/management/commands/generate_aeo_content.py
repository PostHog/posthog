import json
from typing import Any

from django.core.management.base import BaseCommand, CommandError

from posthog.models.team import Team

from products.web_analytics.backend.content_autopilot.generation import (
    compose,
    content_package,
    generate_run,
    site_context,
)
from products.web_analytics.backend.content_autopilot.llm import build_client
from products.web_analytics.backend.content_autopilot.opportunities import (
    MAX_DRAFTS_PER_RUN,
    draft_opportunities,
    refresh_opportunities,
)
from products.web_analytics.backend.models import ContentAutopilotOpportunity, ContentAutopilotSiteProfile


class Command(BaseCommand):
    help = "Draft content for prompts where AI answer engines don't cite the site, from AEO citation checks."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--team-id", type=int, required=True)
        parser.add_argument("--profile-id", type=str, help="Content autopilot site profile. Defaults to the first one.")
        parser.add_argument("--prompt-hash", action="append", default=[], help="Draft this AEO prompt. Repeatable.")
        parser.add_argument("--limit", type=int, default=1, help="Draft the top N opportunities when no hash is given.")
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print the brief, draft and checks without saving drafts. The opportunity list is still refreshed.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        if options["limit"] < 1:
            raise CommandError("--limit must be 1 or more.")
        team = Team.objects.get(id=options["team_id"])
        profiles = ContentAutopilotSiteProfile.objects.for_team(team.id).filter(deleted=False).order_by("created_at")
        profile = profiles.filter(id=options["profile_id"]).first() if options["profile_id"] else profiles.first()
        if profile is None:
            raise CommandError("No content autopilot site profile found. Add the site in /web/content-autopilot first.")

        opportunities = refresh_opportunities(team=team, profile_id=str(profile.id))
        selected = self._select(opportunities, options["prompt_hash"], options["limit"])
        if not selected:
            raise CommandError("No matching opportunities. Check that citation checks have run for this team.")
        self.stdout.write(f"Drafting {len(selected)} opportunities for {profile.domain}")

        if options["dry_run"]:
            client = build_client(team_id=team.id, properties={"content_autopilot_mode": "dry_run"})
            site = site_context(profile)
            for opportunity in selected:
                composition = compose(
                    client,
                    team_id=team.id,
                    site=site,
                    prompt=opportunity.title,
                    target_url=opportunity.target_url,
                    proposal_type=opportunity.recommended_type,
                    gap=opportunity.gap,
                )
                self.stdout.write(f"\n=== {opportunity.title} ({opportunity.recommended_type})")
                self.stdout.write(json.dumps(composition.brief, indent=2))
                self.stdout.write(
                    json.dumps(
                        content_package(composition.draft, origin=site.origin, skipped=composition.research.skipped),
                        indent=2,
                    )
                )
                self.stdout.write(composition.draft.markdown)
                for check in composition.checks:
                    self.stdout.write(f"[{'pass' if check.passed else 'FAIL'}] {check.label}: {check.message}")
            return

        run = draft_opportunities(
            team=team,
            profile_id=str(profile.id),
            opportunity_ids=[str(opportunity.id) for opportunity in selected],
            triggered_by_id=None,
        )
        generate_run(run.team_id, str(run.id))
        run.refresh_from_db()
        self.stdout.write(f"Run {run.id} finished as {run.run_status}. Review it in /web/content-autopilot.")

    def _select(
        self, opportunities: list[ContentAutopilotOpportunity], prompt_hashes: list[str], limit: int
    ) -> list[ContentAutopilotOpportunity]:
        if prompt_hashes:
            return [opportunity for opportunity in opportunities if opportunity.cluster_key in prompt_hashes][
                :MAX_DRAFTS_PER_RUN
            ]
        available = [
            opportunity for opportunity in opportunities if opportunity.status == ContentAutopilotOpportunity.Status.NEW
        ]
        return available[: min(limit, MAX_DRAFTS_PER_RUN)]
