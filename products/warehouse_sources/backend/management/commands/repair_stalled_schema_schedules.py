"""Put schemas back on their schedule after the schedule stopped firing.

`ExternalDataSchema.should_sync` and the Temporal schedule's paused flag are written together
and then drift apart: the flag is set once, when the schedule is created or rewritten, and
nothing reconciles it afterwards. A schedule paused out of band therefore takes a schema's
syncs down while every Postgres column still reports it as syncing. `sweep_stalled_schema_schedules`
reports that state; this command repairs it.

The repair rewrites the schedule from `should_sync`, which unpauses a paused one and recreates a
missing one, and repaints a stale Running status so the next tick is not skipped as an overlap.
It does not fire a run, because runs bill: the schema's own next tick does the work.

Scope: only schemas with no run at all since the stall window opened. A schema whose run started
and never finished has a wedged Temporal workflow instead, which needs terminating rather than
rescheduling; `unstick_external_data_jobs` handles those. This command lists them and skips them.

Dry-run by default.
"""

from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

import structlog

from products.warehouse_sources.backend.stalled_schedules import (
    DEFAULT_MIN_STALL,
    DEFAULT_MISSED_INTERVALS,
    StalledSchema,
    find_stalled_schemas,
    repair_stalled_schema,
)

logger = structlog.get_logger(__name__)

MAX_SCHEMAS_DEFAULT = 100


class Command(BaseCommand):
    help = (
        "Repair schemas whose Temporal schedule stopped firing: unpause or recreate the schedule "
        "and clear a stale Running status. Skips schemas whose run is wedged (use "
        "unstick_external_data_jobs) and buffered CDC sources. Dry-run unless --live-run is given."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--team-id", type=int, help="Scope by team")
        parser.add_argument("--source-type", type=str, help="Scope by source type, e.g. Supabase")
        parser.add_argument(
            "--missed-intervals",
            type=int,
            default=DEFAULT_MISSED_INTERVALS,
            help=(
                "Consecutive runs a schema must miss to count as stalled "
                f"(default {DEFAULT_MISSED_INTERVALS}). Raise it to target only the worst."
            ),
        )
        parser.add_argument(
            "--max-schemas",
            type=int,
            default=MAX_SCHEMAS_DEFAULT,
            help=f"Abort if more than this many schemas match (default {MAX_SCHEMAS_DEFAULT})",
        )
        parser.add_argument(
            "--include-buffered",
            action="store_true",
            help=(
                "Also repair schemas on a buffered CDC source. Their schedule paces buffer "
                "consumption, so restarting it out of sequence can merge files against a table "
                "the buffered lane already writes. Prefer re-running migrate_cdc_source_to_buffered."
            ),
        )
        parser.add_argument("--live-run", action="store_true", help="Apply changes (default is dry-run)")
        parser.add_argument("--yes", action="store_true", help="Skip interactive confirmation")

    def handle(self, *args: Any, **options: Any) -> None:
        live_run: bool = options["live_run"]
        include_buffered: bool = options["include_buffered"]

        max_schemas: int = options["max_schemas"]
        # One over the cap, so an unexpectedly wide match is refused rather than loaded whole.
        stalled = find_stalled_schemas(
            missed_intervals=options["missed_intervals"],
            min_stall=DEFAULT_MIN_STALL,
            team_id=options.get("team_id"),
            source_type=options.get("source_type"),
            limit=max_schemas + 1,
        )
        if not stalled:
            self.stdout.write("No stalled schemas match - nothing to do.")
            return

        if len(stalled) > max_schemas:
            raise CommandError(
                f"More than {max_schemas} schemas match, above the --max-schemas cap. "
                "Narrow the targeting or raise --max-schemas explicitly."
            )

        # --include-buffered only overrides the buffered-CDC exclusion; every other exclusion in
        # repairable_here stays in force — none of them are what that flag is for.
        actionable = [
            s
            for s in stalled
            if s.repairable_here
            or (
                include_buffered
                and s.kind == "no_runs"
                and not s.admin_paused
                and s.has_sync_interval
                and not s.cdc_streaming
                and not s.cdc_halted
            )
        ]
        actionable_ids = {s.schema_id for s in actionable}
        skipped = [s for s in stalled if s.schema_id not in actionable_ids]

        self.stdout.write(f"{len(stalled)} stalled schema(s):")
        for schema in stalled:
            marker = "repair" if schema.schema_id in actionable_ids else f"skip ({self._skip_reason(schema)})"
            self.stdout.write(
                f"  schema={schema.schema_id} team={schema.team_id} source={schema.source_type} "
                f"name={schema.name} stalled={schema.stalled_for.total_seconds() / 3600:.1f}h -> {marker}"
            )

        verb = "Would repair" if not live_run else "Repairing"
        self.stdout.write(f"{verb} {len(actionable)} schema(s); skipping {len(skipped)}.")
        if any(s.kind == "stuck_job" for s in skipped):
            self.stdout.write(
                "Schemas marked stuck_job need unstick_external_data_jobs, which terminates the "
                "wedged workflow. Run it first, then re-run this command."
            )

        if not live_run:
            self.stdout.write("Dry run - no changes written. Re-run with --live-run to apply.")
            return
        if not actionable:
            return

        self._confirm(f"Repair {len(actionable)} schema(s)? Type 'repair' to continue: ", options["yes"])

        failures = 0
        skipped_on_reload = 0
        for schema in actionable:
            # One schema that cannot be repaired must not abort the rest of the sweep.
            try:
                schedule_rewritten = repair_stalled_schema(schema)
            except Exception:
                failures += 1
                logger.exception(
                    "repair_stalled_schema_schedules_failed",
                    schema_id=schema.schema_id,
                    team_id=schema.team_id,
                )
                self.stdout.write(self.style.ERROR(f"  schema={schema.schema_id} FAILED (see logs) - continuing"))
                continue
            if not schedule_rewritten:
                # A revalidation guard inside repair_stalled_schema found the row no longer
                # eligible on reload (e.g. disabled, or flipped to a state a fresh sweep would
                # skip) and returned without raising. That is not the same outcome as a rewrite,
                # so it must not count or log as one.
                skipped_on_reload += 1
                self.stdout.write(self.style.WARNING(f"  schema={schema.schema_id} skipped (no longer eligible)"))
                continue
            logger.info(
                "repair_stalled_schema_schedules_repaired",
                schema_id=schema.schema_id,
                team_id=schema.team_id,
                source_type=schema.source_type,
                stalled_for_hours=round(schema.stalled_for.total_seconds() / 3600, 1),
            )
            self.stdout.write(self.style.SUCCESS(f"  schema={schema.schema_id} rescheduled"))

        repaired = len(actionable) - failures - skipped_on_reload
        self.stdout.write(f"Repaired {repaired} schema(s), {failures} failed, {skipped_on_reload} skipped on reload.")
        self.stdout.write("Each schema runs on its own next tick; no run was triggered, so nothing was billed.")

    def _skip_reason(self, schema: StalledSchema) -> str:
        if schema.kind == "stuck_job":
            return "wedged run, use unstick_external_data_jobs"
        if schema.admin_paused:
            return "paused for an in-flight admin-triggered run"
        if not schema.has_sync_interval:
            return "no sync_frequency_interval set"
        if schema.cdc_streaming:
            return "streaming CDC schema, use repair_cdc"
        if schema.cdc_halted:
            return "CDC halted, use repair_cdc"
        return "buffered CDC source"

    def _confirm(self, prompt: str, yes: bool) -> None:
        if yes:
            return
        if input(prompt).strip() != "repair":
            raise CommandError("Aborted.")
