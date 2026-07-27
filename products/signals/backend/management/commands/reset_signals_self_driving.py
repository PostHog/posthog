import os
import shutil
from datetime import datetime

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from posthog.models import Team

from products.signals.backend.models import (
    SignalEmissionRecord,
    SignalProjectProfile,
    SignalScoutConfig,
    SignalScoutRun,
    SignalScratchpad,
    SignalSourceConfig,
)
from products.signals.backend.scout_harness.skill_loader import SIGNALS_SCOUT_SKILL_PREFIX
from products.skills.backend.models.skills import LLMSkill

# Seed tag stamped on canonical scouts + the `authoring-scouts` companion; this DEBUG
# reset preserves tagged rows. Not a perfect canonical marker (`_scout_origin` also checks the
# name ships on disk), but wizard customs (`llma-skill-create`) carry no tag, so tag-only suffices.
SEEDED_BY_HARNESS = "signals_scout_harness"

# Basename the wizard's agent writes into its `--install-dir` after a self-driving run.
SELF_DRIVING_REPORT_FILE = "posthog-self-driving-report.md"

# The products the wizard's "Enable products" step turns ON, as (label, Team attr). Reading
# them before the reset doubles as a check: an OFF one right after a run is a missed enable.
SELF_DRIVING_PRODUCT_TOGGLES = [
    ("Session Replay", "session_recording_opt_in"),
    ("Error Tracking", "autocapture_exceptions_opt_in"),
    ("Support / Conversations", "conversations_enabled"),
]


class Command(BaseCommand):
    help = (
        "Reset a team to its pre-self-driving state so the self-driving wizard can be "
        "re-tested from scratch. Deletes signal sources, the scout fleet config, custom scouts, "
        "scout run-state (and, unless --keep-findings, emitted findings via cleanup_signals); "
        "optionally removes the wizard's report file and cycles its log. With --reset-products it "
        "also reports the product-enablement toggles (replay / error tracking / conversations) — "
        "after a run they should all be ON, so an OFF one is highlighted as a missed enable — and "
        "then turns them back off. DEBUG only."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--team-id",
            type=int,
            required=True,
            help="Team ID to reset self-driving state for",
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
                f"<install-dir>/{SELF_DRIVING_REPORT_FILE}."
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
        parser.add_argument(
            "--reset-products",
            action="store_true",
            help=(
                "Also report and then turn OFF the wizard's product-enablement toggles (replay / error "
                "tracking / conversations). Off by default — the plain reset leaves product settings "
                "untouched. Use this for the enable-products smoke test: the pre-reset report flags any "
                "product a self-driving run should have enabled but didn't."
            ),
        )

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("This command can only be run with DEBUG=True")

        try:
            team = Team.objects.get(id=options["team_id"])
        except Team.DoesNotExist:
            raise CommandError(f"Team {options['team_id']} not found")

        # Reported before the reset so it reflects what the wizard left behind.
        if options["reset_products"]:
            self._report_product_state(team)

        if not options["yes"]:
            products_clause = "turn OFF the product toggles above and " if options["reset_products"] else ""
            self.stdout.write(
                self.style.WARNING(
                    f"This will {products_clause}DELETE all Signals self-driving state for team "
                    f"{team.id} (sources, scout fleet config, custom scouts, scout run-state"
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

        # 2. Postgres self-driving state, atomically.
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

            # Product toggles + companion settings back to fresh-team shape so the next run re-enables.
            # save(update_fields=...) fires the Team post_save that re-syncs remote config.
            if options["reset_products"]:
                team.session_recording_opt_in = False
                team.session_recording_masking_config = None
                team.autocapture_exceptions_opt_in = None
                team.conversations_enabled = None
                team.conversations_settings = None
                team.save(
                    update_fields=[
                        "session_recording_opt_in",
                        "session_recording_masking_config",
                        "autocapture_exceptions_opt_in",
                        "conversations_enabled",
                        "conversations_settings",
                    ]
                )

            # Scout run-state, so the fleet cold-starts with no learned memory or stale runs.
            runs_deleted, _ = SignalScoutRun.all_teams.filter(team=team).delete()
            scratchpads_deleted, _ = SignalScratchpad.all_teams.filter(team=team).delete()
            profiles_deleted, _ = SignalProjectProfile.all_teams.filter(team=team).delete()
            emission_deleted, _ = SignalEmissionRecord.objects.filter(team=team).delete()

        self.stdout.write(f"  ✓ custom scouts: {len(custom_scout_names)} ({skills_deleted} LLMSkill rows + files)")
        self.stdout.write(f"  ✓ scout configs: {scout_configs_deleted}")
        self.stdout.write(f"  ✓ source configs: {source_configs_deleted}")
        if options["reset_products"]:
            self.stdout.write("  ✓ product toggles: replay / error tracking / conversations turned OFF")
        self.stdout.write(
            f"  ✓ run-state: {runs_deleted} runs, {scratchpads_deleted} scratchpads, "
            f"{profiles_deleted} profiles, {emission_deleted} emission records"
        )

        # 2b. DWH-backed issue-tracker pipelines the wizard created (Github / Linear / Zendesk /
        #     PgAnalyze). Not covered by the signals-owned models above — nothing FK-links them —
        #     so they need their own teardown. Own transaction + best-effort Temporal cleanup.
        self._soft_delete_dwh_sources(team)

        # 3. Filesystem artifacts (wizard-side, outside the posthog repo).
        self._remove_report(options["install_dir"])
        if not options["keep_log"]:
            self._cycle_log(options["wizard_log"])

        self.stdout.write(
            self.style.SUCCESS(
                f"Done. Team {team.id} reset to pre-self-driving state — re-run the wizard to start clean."
            )
        )

    def _report_product_state(self, team):
        """Print the product toggles before resetting them. Right after a run all three should be
        ON, so an OFF one is a missed enable."""
        self.stdout.write("Product enablement (should all be ON right after a self-driving run):")
        off = []
        for label, attr in SELF_DRIVING_PRODUCT_TOGGLES:
            if getattr(team, attr):
                self.stdout.write(self.style.SUCCESS(f"  ✓ {label}: ON"))
            else:
                self.stdout.write(self.style.WARNING(f"  ✗ {label}: OFF"))
                off.append(label)
        if off:
            self.stdout.write(
                self.style.WARNING(f"  ⚠ a self-driving run should have enabled, but didn't: {', '.join(off)}")
            )

    def _soft_delete_dwh_sources(self, team):
        """Soft-delete the self-driving-created data-warehouse pipelines (the Github / Linear /
        Zendesk / PgAnalyze issue/ticket sources) so a re-run starts clean.

        `SignalSourceConfig` (deleted above) has NO foreign key to these warehouse sources —
        the signals layer attaches to them only by (team, source_type, schema_name). So a naive
        reset leaves the pipeline behind; the wizard's `external-data-sources-list` then reports
        the source as already connected and skips the connector — the only place that asks for
        the repo and (re)binds the GitHub connection.

        Mirrors the source-destroy endpoint: soft-delete the schemas + the source (both the list
        and the status queries `.exclude(deleted=True)`), then best-effort tear down the Temporal
        sync schedules so they stop firing. Scoped to `created_via=MCP` so a user's own
        hand-connected warehouse source of the same type is never touched.
        """
        from products.data_warehouse.backend.facade.api import (
            delete_discover_schemas_schedule,
            delete_external_data_schedule,
        )
        from products.signals.backend.serializers import _DATA_IMPORT_SOURCE_MAP
        from products.warehouse_sources.backend.facade.models import ExternalDataSource

        dwh_source_types = {ext_source_type for (ext_source_type, _schema_name) in _DATA_IMPORT_SOURCE_MAP.values()}
        sources = list(
            ExternalDataSource.objects.filter(
                team=team,
                source_type__in=dwh_source_types,
                created_via=ExternalDataSource.CreatedVia.MCP,
                deleted=False,
            )
        )
        if not sources:
            self.stdout.write("  · DWH sources: 0")
            return

        schema_ids: list[str] = []
        with transaction.atomic():
            for source in sources:
                schemas = source.schemas.filter(deleted=False)
                schema_ids.extend(str(schema_id) for schema_id in schemas.values_list("id", flat=True))
                schemas.update(deleted=True, deleted_at=timezone.now())
                source.soft_delete()

        # Temporal teardown runs AFTER the soft-deletes are committed and is best-effort: a
        # missing schedule or an unreachable Temporal must never abort the reset. The schema
        # sync schedules and the source-level sync schedule share `delete_external_data_schedule`.
        for schedule_id in [*schema_ids, *(str(source.id) for source in sources)]:
            try:
                delete_external_data_schedule(schedule_id)
            except Exception as e:
                self.stdout.write(self.style.WARNING(f"    · could not delete sync schedule {schedule_id}: {e}"))
        for source in sources:
            try:
                delete_discover_schemas_schedule(str(source.id))
            except Exception as e:
                self.stdout.write(self.style.WARNING(f"    · could not delete discovery schedule {source.id}: {e}"))

        types = ", ".join(sorted({source.source_type for source in sources}))
        self.stdout.write(f"  ✓ DWH sources: {len(sources)} ({types})")

    def _remove_report(self, install_dir):
        if not install_dir:
            return
        report_path = os.path.join(install_dir, SELF_DRIVING_REPORT_FILE)
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
