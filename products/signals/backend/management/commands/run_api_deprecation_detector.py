"""Detect in-code third-party API usages; optionally research them into a cited inbox report.

Default (read-only, no DB, no network): print the factual inventory of external URL usages.
``--research --team-id N``: launch the ``ApiDeprecationAgent`` (shared custom-agent workflow) which
triages the genuine API call sites, researches them against each vendor's official documentation
(version-level and endpoint-level), and files a cited ``SignalReport`` into the inbox.

    python manage.py run_api_deprecation_detector            # inventory, human-readable
    python manage.py run_api_deprecation_detector --json     # inventory as JSON
    python manage.py run_api_deprecation_detector --research --team-id 1 --repository owner/repo
"""

from __future__ import annotations

import json
import hashlib
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError

from products.signals.backend.api_deprecation.scanner import filter_usages, scan_repo
from products.signals.backend.api_deprecation.schema import ApiUsage

# products/signals/backend/management/commands/<this> → repo root is five parents up.
_REPO_ROOT = Path(__file__).resolve().parents[5]


def _inventory_run_id(usages: list[ApiUsage]) -> str:
    """Stable workflow run id for an inventory, so re-running while a research run for the same
    set of usages is still in flight is a no-op instead of a duplicate report."""
    digest = hashlib.sha256("\n".join(sorted(u.model_dump_json() for u in usages)).encode()).hexdigest()
    return digest[:16]


class Command(BaseCommand):
    help = "Detect third-party API usages; optionally research them into a cited inbox report."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--repo-root", default=str(_REPO_ROOT), help="Repo root to scan.")
        parser.add_argument("--json", action="store_true", help="Emit the inventory as JSON.")
        parser.add_argument("--research", action="store_true", help="Launch the triage + research agent.")
        parser.add_argument("--team-id", type=int, default=None, help="Team to research/emit for.")
        parser.add_argument("--repository", default="posthog/posthog", help="owner/repo the agent researches.")
        parser.add_argument(
            "--filter",
            action="append",
            dest="filters",
            default=None,
            help="Only include usages whose host/endpoint/file contains this substring (repeatable).",
        )
        parser.add_argument("--limit", type=int, default=None, help="Cap the inventory at N usages.")

    def handle(self, *args: Any, **options: Any) -> None:
        usages = scan_repo(options["repo_root"])
        usages = filter_usages(usages, tuple(options["filters"] or ()), options["limit"])

        if options["json"]:
            self.stdout.write(json.dumps([u.model_dump(mode="json") for u in usages], indent=2))
        else:
            self.stdout.write(f"Detected {len(usages)} external URL usage(s):")
            for u in usages:
                self.stdout.write(f"  {u.host}{u.endpoint}  version={u.version or '-'}  {u.file}:{u.line}")

        if not options["research"]:
            return
        if options["team_id"] is None:
            raise CommandError("--research requires --team-id")

        # Heavy/Django-side imports deferred so the read-only detect path stays light.
        from posthog.models import Team  # noqa: PLC0415

        from products.signals.backend.api_deprecation.agent import ApiDeprecationAgent  # noqa: PLC0415
        from products.signals.backend.api_deprecation.research import build_research_initial_prompt  # noqa: PLC0415
        from products.signals.backend.custom_agent import AIDataProcessingNotApprovedError  # noqa: PLC0415
        from products.signals.backend.temporal.custom_agent import run_agent  # noqa: PLC0415

        try:
            team = Team.objects.select_related("organization").get(id=options["team_id"])
        except Team.DoesNotExist:
            raise CommandError(f"Team {options['team_id']} not found.")
        try:
            handle = run_agent(
                ApiDeprecationAgent,
                team=team,
                initial_prompt=build_research_initial_prompt(usages),
                repository=options["repository"],
                id=_inventory_run_id(usages),
            )
        except AIDataProcessingNotApprovedError as error:
            raise CommandError(str(error))
        if handle.started:
            self.stdout.write(f"started workflow {handle.workflow_id}")
        else:
            self.stdout.write(f"workflow {handle.workflow_id} is already running for this inventory; not restarting")
