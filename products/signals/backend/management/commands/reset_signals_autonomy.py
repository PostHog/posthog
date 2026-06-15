import os
import shutil
from datetime import datetime

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from posthog.models import Team

from products.ai_observability.backend.models.skills import LLMSkill
from products.signals.backend.models import (
    SignalEmissionRecord,
    SignalProjectProfile,
    SignalScoutConfig,
    SignalScoutRun,
    SignalScratchpad,
    SignalSourceConfig,
)
from products.signals.backend.scout_harness.skill_loader import SIGNALS_SCOUT_SKILL_PREFIX

# The only reliable canonical-vs-custom discriminator. Canonical scouts (and the
# `authoring-signals-scouts` companion) are stamped with this by the seeding
# harness; scouts the autonomy wizard creates via `llma-skill-create` are not.
# See `lazy_seed.py` (sync_canonical_skills guard) for the authoritative usage.
SEEDED_BY_HARNESS = "signals_scout_harness"

# Basename the wizard's agent writes into its `--install-dir` after an autonomy run.
AUTONOMY_REPORT_FILE = "posthog-product-autonomy-report.md"


class Command(BaseCommand):
    help = (
        "Reset a team to its pre-autonomy state so the product-autonomy wizard can be "
        "re-tested from scratch. Deletes signal sources, the scout fleet config, custom "
        "scouts, scout run-state (and, unless --keep-findings, emitted findings via "
        "cleanup_signals); optionally removes the wizard's report file and cycles its log. "
        "DEBUG only."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--team-id",
            type=int,
            required=True,
            help="Team ID to reset autonomy state for",
        )
        parser.add_argument(
            "--yes",
            action="store_true",
            help="Skip confirmation prompt",
        )
        parser.add_argument(
            "--install-dir",
            type=str,
            default=None,
            help=(
                "The wizard's --install-dir (the test project). When given, removes "
                f"<install-dir>/{AUTONOMY_REPORT_FILE}."
            ),
        )
        parser.add_argument(
            "--wizard-log",
            type=str,
            default="/tmp/posthog-wizard.log",
            help="Path to the wizard log. Backed up to <stem>-previous-<timestamp><ext> then removed.",
        )
        parser.add_argument(
            "--keep-log",
            action="store_true",
            help="Do not back up or remove the wizard log.",
        )
        parser.add_argument(
            "--keep-findings",
            action="store_true",
            help="Do not clear emitted findings/reports (skips the cleanup_signals delegation).",
        )

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("This command can only be run with DEBUG=True")

        try:
            team = Team.objects.get(id=options["team_id"])
        except Team.DoesNotExist:
            raise CommandError(f"Team {options['team_id']} not found")

        if not options["yes"]:
            self.stdout.write(
                self.style.WARNING(
                    f"This will DELETE all Signals autonomy state for team {team.id} "
                    f"(sources, scout fleet config, custom scouts, scout run-state"
                    f"{'' if options['keep_findings'] else ', emitted findings'}). "
                    f"Canonical scouts are preserved."
                )
            )
            confirm = input("Type 'yes' to confirm: ")
            if confirm != "yes":
                self.stdout.write("Aborted.")
                return

        # 1. Emitted findings/reports + ClickHouse rows + Temporal workflows. Delegated to
        #    cleanup_signals because it owns the ClickHouse mutations and workflow termination;
        #    run it first and OUTSIDE our Postgres transaction (it touches non-Postgres systems).
        if not options["keep_findings"]:
            self.stdout.write("Clearing emitted findings via cleanup_signals...")
            call_command("cleanup_signals", team_id=team.id, yes=True)

        # 2. Postgres autonomy state, atomically.
        with transaction.atomic():
            # Custom scouts: every version of each `signals-scout-*` skill NOT stamped by the
            # seeding harness. We partition by SET DIFFERENCE (all scout names minus seeded
            # names), NOT `.exclude(metadata__seeded_by=...)`. An ABSENT JSONB key makes
            # `metadata->>'seeded_by'` SQL NULL, and `NOT (NULL = '...')` is NULL (not TRUE),
            # so `.exclude()` silently skips rows whose metadata has no `seeded_by` key at all
            # — which is the common case for a wizard-/hand-authored scout. The set diff is
            # NULL-safe: a name is custom iff it is a scout name not among the seeded ones.
            # No seeded name can land in `custom_scout_names`, so deleting by `name__in`
            # (every version) never touches a canonical/companion row, and cascades LLMSkillFile.
            scout_skills = LLMSkill.objects.filter(
                team_id=team.id,
                name__startswith=SIGNALS_SCOUT_SKILL_PREFIX,
                is_latest=True,
                deleted=False,
            )
            all_scout_names = set(scout_skills.values_list("name", flat=True))
            seeded_scout_names = set(
                scout_skills.filter(metadata__seeded_by=SEEDED_BY_HARNESS).values_list("name", flat=True)
            )
            custom_scout_names = sorted(all_scout_names - seeded_scout_names)
            skills_deleted = 0
            if custom_scout_names:
                skills_deleted, _ = LLMSkill.objects.filter(team_id=team.id, name__in=custom_scout_names).delete()

            # Scout fleet config (canonical + custom). Deleting — not disabling — restores the
            # fresh-team shape: the next wizard `sync` re-creates canonical configs enabled.
            scout_configs_deleted, _ = SignalScoutConfig.all_teams.filter(team=team).delete()

            # Signal sources. A fresh team has none.
            source_configs_deleted, _ = SignalSourceConfig.objects.filter(team=team).delete()

            # Scout run-state, so the fleet cold-starts with no learned memory or stale runs.
            runs_deleted, _ = SignalScoutRun.all_teams.filter(team=team).delete()
            scratchpads_deleted, _ = SignalScratchpad.all_teams.filter(team=team).delete()
            profiles_deleted, _ = SignalProjectProfile.all_teams.filter(team=team).delete()
            emission_deleted, _ = SignalEmissionRecord.objects.filter(team=team).delete()

        self.stdout.write(f"  ✓ custom scouts: {len(custom_scout_names)} ({skills_deleted} LLMSkill rows + files)")
        self.stdout.write(f"  ✓ scout configs: {scout_configs_deleted}")
        self.stdout.write(f"  ✓ source configs: {source_configs_deleted}")
        self.stdout.write(
            f"  ✓ run-state: {runs_deleted} runs, {scratchpads_deleted} scratchpads, "
            f"{profiles_deleted} profiles, {emission_deleted} emission records"
        )

        # 3. Filesystem artifacts (wizard-side, outside the posthog repo).
        self._remove_report(options["install_dir"])
        if not options["keep_log"]:
            self._cycle_log(options["wizard_log"])

        self.stdout.write(
            self.style.SUCCESS(f"Done. Team {team.id} reset to pre-autonomy state — re-run the wizard to start clean.")
        )

    def _remove_report(self, install_dir):
        if not install_dir:
            return
        report_path = os.path.join(install_dir, AUTONOMY_REPORT_FILE)
        if os.path.exists(report_path):
            os.remove(report_path)
            self.stdout.write(f"  ✓ removed report: {report_path}")
        else:
            self.stdout.write(f"  · no report at {report_path}")

    def _cycle_log(self, log_path):
        if not log_path or not os.path.exists(log_path):
            self.stdout.write(f"  · no wizard log at {log_path}")
            return
        root, ext = os.path.splitext(log_path)
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_path = f"{root}-previous-{timestamp}{ext}"
        shutil.copy2(log_path, backup_path)
        os.remove(log_path)
        self.stdout.write(f"  ✓ wizard log backed up to {backup_path} and cleared")
