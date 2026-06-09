"""API deprecation loop — detect pins, and optionally run the changelog-research agent.

Default (read-only, no DB, no network): print the factual inventory of external-API version pins.
``--research --team-id N``: dispatch the agentic stage that reads each vendor's real changelog and
emits cited signals into the inbox (needs the sandbox + a GitHub integration; never opens a PR).

    python manage.py run_api_deprecation_detector            # inventory, human-readable
    python manage.py run_api_deprecation_detector --json     # inventory as JSON
    python manage.py run_api_deprecation_detector --research --team-id 1
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError

from products.signals.backend.api_deprecation.scanner import scan_repo

# products/signals/backend/management/commands/<this> → repo root is five parents up.
_REPO_ROOT = Path(__file__).resolve().parents[5]


class Command(BaseCommand):
    help = "Detect external-API version pins; optionally run the changelog-research agent to emit signals."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--repo-root", default=str(_REPO_ROOT), help="Repo root to scan.")
        parser.add_argument("--json", action="store_true", help="Emit the inventory as JSON.")
        parser.add_argument("--research", action="store_true", help="Dispatch the changelog-research agent.")
        parser.add_argument("--team-id", type=int, default=None, help="Team to research/emit for.")
        parser.add_argument("--repository", default="posthog/posthog", help="owner/repo the agent researches.")
        parser.add_argument(
            "--dispatch",
            action="store_true",
            help="After research, route findings: mechanical → PostHog Code draft PR, structural → issue.",
        )
        parser.add_argument(
            "--dispatch-dry-run",
            action="store_true",
            help="With --dispatch, print the routing plan without creating any Task or issue.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        pins = scan_repo(options["repo_root"])

        if options["json"]:
            self.stdout.write(json.dumps([p.model_dump(mode="json") for p in pins], indent=2))
        else:
            self.stdout.write(f"Detected {len(pins)} external-API version pin(s):")
            for p in pins:
                self.stdout.write(
                    f"  [{p.vendor}] {p.host} {p.pinned_version}  {p.file}:{p.line}  persisted={p.persisted_per_row}"
                )

        if not options["research"]:
            return

        if options["team_id"] is None:
            raise CommandError("--research requires --team-id")

        # Heavy/Django-side imports deferred so the read-only detect path stays light.
        from asgiref.sync import async_to_sync  # noqa: PLC0415

        from posthog.models import Team  # noqa: PLC0415

        from products.signals.backend.api_deprecation.agent import ApiDeprecationAgent  # noqa: PLC0415

        team = Team.objects.select_related("organization").get(id=options["team_id"])
        agent = ApiDeprecationAgent(team=team, pins=pins, repository=options["repository"])
        reports = async_to_sync(agent.start)()
        for report in reports:
            self.stdout.write(f"emitted report {report.report_id}")

        if not options["dispatch"]:
            return
        if not reports:
            self.stdout.write("nothing to dispatch")
            return

        from products.signals.backend.api_deprecation.dispatch import dispatch_findings  # noqa: PLC0415

        outcomes = dispatch_findings(
            team_id=options["team_id"],
            report_id=reports[0].report_id,
            findings=agent.findings,
            repository=options["repository"],
            dry_run=options["dispatch_dry_run"],
        )
        for outcome in outcomes:
            target = outcome.task_id or outcome.issue_url or "—"
            self.stdout.write(
                f"  {outcome.action.value}: {outcome.dedup_key} → {target}{' (dry-run)' if outcome.dry_run else ''}"
            )
