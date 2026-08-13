"""Give teams losing the legacy session summarization a Replay Vision summarizer in its place.

Those teams had `session_replay`/`session_analysis_cluster` emitting signals into the inbox. Removing
the old feature silences that source, so this mints one summarizer scanner per team to keep it fed.

Deliberately a command rather than a migration: it creates billable resources for real customers, so
it must be run in batches by a person watching credit burn, not fired at every team during a deploy.
"""

from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

import structlog

from posthog.models.team import Team

from products.replay_vision.backend.api.scanners import _refresh_estimate_fail_soft
from products.replay_vision.backend.models.replay_scanner import ReplayScanner, ScannerModel, ScannerType
from products.replay_vision.backend.queries import MIN_SAMPLING_RATE
from products.signals.backend.models import SignalSourceConfig

logger = structlog.get_logger(__name__)

SCANNER_NAME = "Session summary"
SCANNER_DESCRIPTION = "A short narrative summary of the session."

# Kept in step by hand with the `session_summary` scanner template the picker offers, so a provisioned
# scanner and a hand-created one produce the same shape of summary.
SCANNER_PROMPT = (
    "Summarize what the user did in this session: which pages they visited, what they tried to "
    "accomplish, and any notable moments like errors, confusion, or successful completions. "
    "Be concrete and don't speculate."
)


class Command(BaseCommand):
    help = "Provision a summarizer scanner for teams that had the legacy session summarization signal source."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--credit-limit",
            type=int,
            required=True,
            help="Per-scanner credit cap per billing period. Required: without it a provisioned scanner "
            "spends against the org's whole allowance, including purchased credits.",
        )
        parser.add_argument(
            "--sampling-rate",
            type=float,
            default=0.1,
            help="Fraction of matching recordings to scan (default 0.1).",
        )
        parser.add_argument(
            "--model",
            default=ScannerModel.GEMINI_3_5_FLASH_LITE,
            choices=[m.value for m in ScannerModel],
            help="Model to scan with; the cheapest is the default.",
        )
        parser.add_argument("--limit", type=int, help="Provision at most this many teams, for staged rollout.")
        parser.add_argument("--team-ids", help="Comma-separated team ids to restrict to.")
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Actually create scanners. Without it the command only reports what it would do.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        # The cap is the whole safety story, so refuse to run on a build that cannot enforce one rather
        # than silently creating scanners that spend against the org's full balance.
        if not any(f.name == "credit_limit" for f in ReplayScanner._meta.get_fields()):
            raise CommandError(
                "ReplayScanner has no `credit_limit` field, so a per-scanner cap cannot be set. "
                "This command needs the per-scanner credit limit work deployed first."
            )
        if options["credit_limit"] < 1:
            raise CommandError("--credit-limit must be at least 1.")
        # Same floor the serializer enforces: below it a scanner samples so little it scans nothing.
        if not MIN_SAMPLING_RATE <= options["sampling_rate"] <= 1.0:
            raise CommandError(f"--sampling-rate must be between {MIN_SAMPLING_RATE} and 1.")

        team_ids = self._target_team_ids(options.get("team_ids"))

        created = skipped_no_consent = 0
        for team in Team.objects.filter(id__in=team_ids).select_related("organization").order_by("id"):
            # Scanner creation through the API refuses without org approval; a command must not be a way around it.
            if not team.organization.is_ai_data_processing_approved:
                skipped_no_consent += 1
                self.stdout.write(f"  skip team {team.id}: org has not approved AI data processing")
                continue

            # Counted after the consent skip so `--limit 10` provisions ten teams rather than considering ten.
            if options.get("limit") and created >= options["limit"]:
                break

            if not options["apply"]:
                self.stdout.write(f"  would provision team {team.id}")
                created += 1
                continue

            with transaction.atomic():
                scanner = self._create_scanner(team, options)
            # Without this the scanner spends credits while missing from the org's spend forecast.
            _refresh_estimate_fail_soft(scanner)
            logger.info(
                "replay_vision.provisioned_summarizer",
                team_id=team.id,
                scanner_id=str(scanner.id),
                credit_limit=options["credit_limit"],
            )
            self.stdout.write(f"  provisioned team {team.id} -> scanner {scanner.id}")
            created += 1

        verb = "provisioned" if options["apply"] else "would provision"
        self.stdout.write(
            self.style.SUCCESS(f"{verb} {created} team(s); skipped {skipped_no_consent} without AI consent")
        )
        if not options["apply"]:
            self.stdout.write("Dry run. Re-run with --apply to create these scanners.")

    def _target_team_ids(self, restrict_to: str | None) -> list[int]:
        """Teams still on the legacy source that have no scanner of their own to replace it."""
        enabled = SignalSourceConfig.objects.filter(
            source_product=SignalSourceConfig.SourceProduct.SESSION_REPLAY,
            source_type=SignalSourceConfig.SourceType.SESSION_ANALYSIS_CLUSTER,
            enabled=True,
        )
        team_ids = set(enabled.values_list("team_id", flat=True))
        if restrict_to:
            try:
                team_ids &= {int(t) for t in restrict_to.split(",") if t.strip()}
            except ValueError:
                raise CommandError("--team-ids must be a comma-separated list of integers.")
        # `objects` is configured-only, so an inline scan from a summarize click never counts as one.
        already = set(ReplayScanner.objects.filter(team_id__in=team_ids).values_list("team_id", flat=True))
        return sorted(team_ids - already)

    def _create_scanner(self, team: Team, options: dict[str, Any]) -> ReplayScanner:
        fields: dict[str, Any] = {
            "team": team,
            # No creator: nobody asked for this scanner, so crediting a user would misattribute it.
            "created_by": None,
            "name": SCANNER_NAME,
            "description": SCANNER_DESCRIPTION,
            "scanner_type": ScannerType.SUMMARIZER,
            "scanner_config": {"prompt": SCANNER_PROMPT, "length": "medium"},
            "model": options["model"],
            "sampling_rate": options["sampling_rate"],
            "emits_signals": True,
            "enabled": True,
            # Set dynamically because the field ships with the per-scanner credit limit work, which this
            # command predates. `handle` refuses to run until it exists, so this is never silently dropped.
            "credit_limit": options["credit_limit"],
        }
        # No built-in digest: it is a second scheduled LLM run per day, and nobody asked for this scanner.
        return ReplayScanner.objects.create(**fields)
