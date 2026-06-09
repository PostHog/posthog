"""Drive emit → dispatch with a KNOWN finding — test the back half of the loop without the sandbox.

Use this to exercise the real PostHog Code path (mechanical → draft PR) and the structural → issue
path deterministically, since the changelog-research stage is non-deterministic and needs a sandbox.

    # Emit the Meta mechanical finding to the inbox only (no dispatch)
    python manage.py test_api_deprecation_dispatch --team-id 1 --sample meta

    # Preview routing without side effects
    python manage.py test_api_deprecation_dispatch --team-id 1 --sample meta --dispatch --dispatch-dry-run

    # Real dispatch → PostHog Code opens a DRAFT PR (target a fork to keep it safe!)
    python manage.py test_api_deprecation_dispatch --team-id 1 --sample meta --dispatch --repository my-org/posthog-fork

    # Structural sample → files a GitHub issue
    python manage.py test_api_deprecation_dispatch --team-id 1 --sample google-structural --dispatch
"""

from __future__ import annotations

from datetime import date
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from products.signals.backend.api_deprecation.emit import emit_signal_to_inbox
from products.signals.backend.api_deprecation.samples import SAMPLES


class Command(BaseCommand):
    help = "Emit (and optionally dispatch) a known sample deprecation finding, bypassing the research sandbox."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--team-id", type=int, required=True)
        parser.add_argument("--sample", choices=sorted(SAMPLES), default="meta")
        parser.add_argument(
            "--repository", default="posthog/posthog", help="Target repo (use a fork for safe testing)."
        )
        parser.add_argument("--dispatch", action="store_true", help="Route the finding (PR / issue).")
        parser.add_argument(
            "--dispatch-dry-run", action="store_true", help="With --dispatch, plan only — no side effects."
        )
        parser.add_argument(
            "--reviewer",
            action="append",
            default=None,
            help="GitHub login to suggest as reviewer (repeatable). Makes the card show in that user's inbox lane. No PR.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        if not settings.DEBUG:
            raise CommandError("test_api_deprecation_dispatch is a local-only test command (requires DEBUG=True)")

        finding = SAMPLES[options["sample"]]()
        today = date.today()

        persisted = emit_signal_to_inbox(
            team_id=options["team_id"],
            findings=[finding],
            today=today,
            repository=options["repository"],
            reviewers=options["reviewer"],
        )
        if persisted is None:
            self.stdout.write("nothing emitted (finding produced no report)")
            return
        self.stdout.write(f"emitted report {persisted.report_id} for {finding.dedup_key}")

        if not options["dispatch"]:
            return

        # Imported here so the emit-only path stays lighter.
        from products.signals.backend.api_deprecation.dispatch import dispatch_findings  # noqa: PLC0415

        outcomes = dispatch_findings(
            team_id=options["team_id"],
            report_id=persisted.report_id,
            findings=[finding],
            repository=options["repository"],
            dry_run=options["dispatch_dry_run"],
        )
        for outcome in outcomes:
            target = outcome.task_id or outcome.issue_url or "—"
            suffix = " (dry-run)" if outcome.dry_run else ""
            self.stdout.write(f"  {outcome.action.value}: {outcome.dedup_key} → {target}{suffix}")
