import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Final

from django.core.management.base import BaseCommand, CommandError
from django.db import models, transaction
from django.db.models.functions import Cast
from django.utils import timezone

from posthog.plugins.plugin_server_api import reload_hog_flows_on_workers, reload_hog_functions_on_workers

from products.cdp.backend.models.hog_functions.hog_function import HogFunction
from products.messaging.backend.models.message_template import MessageTemplate
from products.workflows.backend.models.hog_flow.hog_flow import HogFlow
from products.workflows.backend.models.hog_flow.hog_flow_template import HogFlowTemplate

logger = logging.getLogger(__name__)

WorkerReload = Callable[[int, str], None]

# Only executed config has a worker-side cache to invalidate; templates are copied at creation time
# and never read by a worker, so they need no reload.
WORKER_RELOADS: Final[dict[str, WorkerReload]] = {
    "hog_flows": lambda team_id, row_id: reload_hog_flows_on_workers(team_id=team_id, hog_flow_ids=[row_id]),
    "hog_functions": lambda team_id, row_id: reload_hog_functions_on_workers(
        team_id=team_id, hog_function_ids=[row_id]
    ),
}

# Every column that can hold rendered email content, mapped to the timestamp that tracks it.
# `actions`/`inputs` carry both the editable value (html, design) and the compiled hog bytecode the
# executor renders from when an input isn't liquid, so a rewrite has to cover the whole blob -
# fixing only value.html would leave those sends unchanged.
TARGETS: Final[dict[str, tuple[type[models.Model], dict[str, str]]]] = {
    "hog_flows": (HogFlow, {"actions": "updated_at", "draft": "draft_updated_at"}),
    "hog_flow_templates": (HogFlowTemplate, {"actions": "updated_at"}),
    "message_templates": (MessageTemplate, {"content": "updated_at"}),
    "hog_functions": (HogFunction, {"inputs": "updated_at", "draft": "draft_updated_at"}),
}


@dataclass(frozen=False)
class RewriteCounts:
    rows_scanned: int = 0
    rows_changed: int = 0
    occurrences: int = 0
    errors: int = 0


def rewrite_blob(blob: Any, from_url: str, to_url: str) -> tuple[Any, int]:
    """Replace every occurrence of from_url inside a JSON blob. Returns the new blob and a count."""
    if blob is None:
        return blob, 0
    serialized = json.dumps(blob)
    occurrences = serialized.count(from_url)
    if not occurrences:
        return blob, 0
    return json.loads(serialized.replace(from_url, to_url)), occurrences


class Command(BaseCommand):
    help = (
        "Rewrite an asset URL wherever it is stored in email content: workflow actions and drafts, "
        "workflow templates, message templates, and hog function inputs."
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--from-url", required=True, help="URL (or URL prefix) to replace")
        parser.add_argument("--to-url", required=True, help="Replacement URL")
        parser.add_argument("--dry-run", action="store_true", help="Report what would change, write nothing")
        parser.add_argument(
            "--team-id",
            type=int,
            nargs="+",
            help="Team(s) to rewrite. Required unless --all-teams is passed.",
        )
        parser.add_argument(
            "--all-teams",
            action="store_true",
            help="Rewrite every team. Without this, --team-id is mandatory.",
        )
        parser.add_argument("--id", dest="row_id", type=str, help="Limit to one row (workflow, template, function)")
        parser.add_argument(
            "--targets",
            type=str,
            default=",".join(TARGETS),
            help=f"Comma-separated subset of: {', '.join(TARGETS)}",
        )
        parser.add_argument("--batch-size", type=int, default=100, help="Rows per transaction (default 100)")
        parser.add_argument("--list-rows", action="store_true", help="Print every affected row id")

    def handle(self, *args: Any, **options: Any) -> None:
        from_url: str = options["from_url"]
        to_url: str = options["to_url"]
        dry_run: bool = options["dry_run"]
        targets = [t.strip() for t in options["targets"].split(",") if t.strip()]

        team_ids: list[int] | None = options.get("team_id")
        all_teams: bool = options["all_teams"]
        # Team scope is opt-in in both directions: an asset URL is shared across teams, so a run
        # that forgets --team-id would silently rewrite every customer's workflows.
        if not team_ids and not all_teams:
            raise CommandError("Pass --team-id <id> [<id> ...], or --all-teams to rewrite every team")
        if team_ids and all_teams:
            raise CommandError("Pass either --team-id or --all-teams, not both")

        if from_url == to_url:
            raise CommandError("--from-url and --to-url are identical")
        # A from-url contained in the to-url would match its own replacement, so a second run would
        # keep nesting it. Refuse rather than produce a mangled URL on a re-run.
        if from_url in to_url:
            raise CommandError("--from-url must not be a substring of --to-url (the rewrite would not be idempotent)")
        unknown = set(targets) - set(TARGETS)
        if unknown:
            raise CommandError(f"Unknown target(s): {', '.join(sorted(unknown))}. Valid: {', '.join(TARGETS)}")
        # 0 makes range() raise mid-run and a negative step yields no batches at all, which reads as
        # a clean "nothing to do" while every matched row keeps the old URL.
        if options["batch_size"] < 1:
            raise CommandError("--batch-size must be 1 or more")

        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN - no writes"))
        scope = "ALL TEAMS" if all_teams else f"team(s) {', '.join(str(t) for t in team_ids or [])}"
        self.stdout.write(f"Scope: {scope}")
        self.stdout.write(f"Replacing {from_url}\n       with {to_url}\n")

        totals = RewriteCounts()
        for target in targets:
            counts = self._process_target(target, from_url, to_url, options)
            totals.rows_scanned += counts.rows_scanned
            totals.rows_changed += counts.rows_changed
            totals.occurrences += counts.occurrences
            totals.errors += counts.errors

        summary = (
            f"\n{'Would change' if dry_run else 'Changed'}: {totals.rows_changed} row(s), "
            f"{totals.occurrences} occurrence(s). Scanned {totals.rows_scanned}. Errors: {totals.errors}"
        )
        self.stdout.write(self.style.SUCCESS(summary) if not totals.errors else self.style.ERROR(summary))

        # Exit non-zero on a partial run. Rows that failed still carry the old URL, and a caller that
        # only reads the exit code would otherwise treat the rewrite as complete.
        if totals.errors:
            raise CommandError(f"{totals.errors} row(s) failed to rewrite - see the errors above and re-run")

    def _process_target(self, target: str, from_url: str, to_url: str, options: dict[str, Any]) -> RewriteCounts:
        model, field_timestamps = TARGETS[target]
        fields = tuple(field_timestamps)
        counts = RewriteCounts()

        # _default_manager, not .objects: the loop is generic over four models, and Model itself
        # doesn't declare a manager. unscoped() where it exists - a fix like this is deliberately
        # cross-team, so a fail-closed manager would otherwise raise TeamScopeError.
        manager = model._default_manager
        base_queryset = manager.unscoped() if hasattr(manager, "unscoped") else manager.all()
        if options.get("team_id"):
            base_queryset = base_queryset.filter(team_id__in=options["team_id"])
        if options.get("row_id"):
            base_queryset = base_queryset.filter(id=options["row_id"])

        # The text casts belong only on the id-matching query, where they stay in the WHERE clause.
        # Loading rows off the un-annotated base queryset avoids the database returning a full text
        # copy of every large JSON column alongside the value we actually rewrite.
        matcher = base_queryset
        match = models.Q()
        for field in fields:
            matcher = matcher.annotate(**{f"_text_{field}": Cast(field, models.TextField())})
            match |= models.Q(**{f"_text_{field}__contains": from_url})

        row_ids = list(matcher.filter(match).order_by("id").values_list("id", flat=True))
        self.stdout.write(f"{target}: {len(row_ids)} row(s) matched")
        if not row_ids:
            return counts

        batch_size: int = options["batch_size"]
        for start in range(0, len(row_ids), batch_size):
            batch = row_ids[start : start + batch_size]
            for row_id in batch:
                counts.rows_scanned += 1
                try:
                    occurrences = self._rewrite_row(
                        base_queryset,
                        row_id,
                        field_timestamps,
                        WORKER_RELOADS.get(target),
                        from_url,
                        to_url,
                        dry_run=options["dry_run"],
                    )
                except Exception as e:
                    counts.errors += 1
                    logger.exception("Failed to rewrite %s %s: %s", target, row_id, e)
                    self.stdout.write(self.style.ERROR(f"  {row_id}: {e}"))
                    continue
                if occurrences:
                    counts.rows_changed += 1
                    counts.occurrences += occurrences
                    if options["list_rows"]:
                        self.stdout.write(f"  {row_id}: {occurrences} occurrence(s)")

        return counts

    def _rewrite_row(
        self,
        base_queryset: models.QuerySet,
        row_id: Any,
        field_timestamps: dict[str, str],
        publish_reload: WorkerReload | None,
        from_url: str,
        to_url: str,
        dry_run: bool,
    ) -> int:
        if dry_run:
            row = base_queryset.get(pk=row_id)
            return sum(rewrite_blob(getattr(row, field), from_url, to_url)[1] for field in field_timestamps)

        # Read the row again under a row lock and rewrite that value, not the one the id scan saw.
        # A customer saving the same workflow in between would otherwise have their edit overwritten
        # by the stale blob this command is holding - the same lost write the API path guards against
        # with select_for_update plus its staleness fence.
        with transaction.atomic():
            row = base_queryset.select_for_update().get(pk=row_id)

            changed_fields: list[str] = []
            occurrences = 0
            for field in field_timestamps:
                new_value, found = rewrite_blob(getattr(row, field), from_url, to_url)
                if found:
                    setattr(row, field, new_value)
                    changed_fields.append(field)
                    occurrences += found

            if not occurrences:
                return 0

            # Bump the timestamp that tracks each column we touched, so the editor's stale-write
            # detection sees the change instead of letting an open tab save the dead URL back.
            # Keeping a draft-only rewrite on draft_updated_at also keeps it out of the live row's
            # history, and lets the post_save receivers skip a worker reload nothing is executing yet.
            timestamp_fields: list[str] = []
            live_change = False
            for field in changed_fields:
                timestamp_field = field_timestamps[field]
                live_change = live_change or timestamp_field == "updated_at"
                if timestamp_field in timestamp_fields:
                    continue
                timestamp_fields.append(timestamp_field)
                # updated_at is auto_now, so listing it is enough; the rest need an explicit value.
                if timestamp_field != "updated_at":
                    setattr(row, timestamp_field, timezone.now())

            # One row per save, never bulk_update: workers only drop their cached copy when a reload
            # is published for the row, and bulk_update fires no signal at all.
            row.save(update_fields=[*changed_fields, *timestamp_fields])

            # The post_save receiver publishes from inside this transaction, so a worker can re-read
            # the row before the UPDATE commits and cache the old blob for another refresh window.
            # Publishing again on commit is what workers actually act on; the duplicate is harmless.
            # Draft-only rewrites publish nothing, matching the receiver that skips them.
            if live_change and publish_reload is not None:
                team_id, row_pk = row.team_id, str(row.pk)
                transaction.on_commit(lambda: publish_reload(team_id, row_pk))

        return occurrences
