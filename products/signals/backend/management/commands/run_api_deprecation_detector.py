"""Detect in-code external-API version pins; optionally research them into a cited inbox report.

Default (read-only, no DB, no network): print the factual inventory of pins.
``--research --team-id N``: launch the ``ApiDeprecationAgent`` (shared custom-agent workflow) which
reads each vendor's real changelog and files a cited ``SignalReport`` into the inbox.

    python manage.py run_api_deprecation_detector            # inventory, human-readable
    python manage.py run_api_deprecation_detector --json     # inventory as JSON
    python manage.py run_api_deprecation_detector --research --team-id 1 --repository owner/repo
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
    help = "Detect external-API version pins; optionally research them into a cited inbox report."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--repo-root", default=str(_REPO_ROOT), help="Repo root to scan.")
        parser.add_argument("--json", action="store_true", help="Emit the inventory as JSON.")
        parser.add_argument("--research", action="store_true", help="Launch the changelog-research agent.")
        parser.add_argument("--team-id", type=int, default=None, help="Team to research/emit for.")
        parser.add_argument("--repository", default="posthog/posthog", help="owner/repo the agent researches.")

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
        from posthog.models import Team  # noqa: PLC0415

        from products.signals.backend.api_deprecation.research import build_research_initial_prompt  # noqa: PLC0415
        from products.signals.backend.custom_agent.examples.api_deprecation_agent import (  # noqa: PLC0415
            ApiDeprecationAgent,
        )
        from products.signals.backend.temporal.custom_agent import run_agent  # noqa: PLC0415

        try:
            team = Team.objects.select_related("organization").get(id=options["team_id"])
        except Team.DoesNotExist:
            raise CommandError(f"Team {options['team_id']} not found.")
        handle = run_agent(
            ApiDeprecationAgent,
            team=team,
            initial_prompt=build_research_initial_prompt(pins),
            repository=options["repository"],
        )
        self.stdout.write(f"started workflow {handle.workflow_id}")
