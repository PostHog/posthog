import logging
from dataclasses import dataclass
from typing import Any, Final

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from posthog.cdp.email_sender import from_email_integration_ids, override_off_domain_reason
from posthog.models.integration import Integration
from posthog.plugins.plugin_server_api import reload_hog_flows_on_workers

from products.workflows.backend.models.hog_flow.hog_flow import HogFlow

logger = logging.getLogger(__name__)

# Scoped to workflows, where the placeholder was reported and where the email input is liquid, so
# clearing the stored value fully repairs it. Email destination hog functions share the sender
# picker but can compile the address into bytecode, so a value-only clear would not be enough there;
# authoring-time validation in posthog/cdp/validation.py covers both surfaces going forward.
#
# Columns on a workflow that hold email step content, mapped to the timestamp that tracks each.
# `draft` carries an in-progress edit and gets its own timestamp so a draft-only rewrite stays out
# of the live row's history and skips a worker reload nothing is executing yet.
FIELD_TIMESTAMPS: Final[dict[str, str]] = {"actions": "updated_at", "draft": "draft_updated_at"}


@dataclass(frozen=False)
class ClearCounts:
    rows_scanned: int = 0
    rows_changed: int = 0
    senders_cleared: int = 0
    errors: int = 0


def clear_off_domain_from_email(from_value: dict[str, Any], domain_by_integration_id: dict[int, dict]) -> bool:
    """Drop a literal sender address that sits off every selected sender's verified domain.

    Returns True when the address was cleared. A templated or empty address is left alone: only a
    stored literal that the runtime would silently discard is the placeholder we backfill.
    """
    override_email = from_value.get("email")
    if not isinstance(override_email, str) or not override_email.strip() or "{" in override_email:
        return False

    configs = [
        domain_by_integration_id[i] for i in from_email_integration_ids(from_value) if i in domain_by_integration_id
    ]
    if not configs:
        return False

    # Honored whenever it lands on a selected sender's domain, so only clear an address that
    # matches none of them — this preserves an address a customer deliberately set for one sender.
    if all(override_off_domain_reason(config, override_email) is not None for config in configs):
        del from_value["email"]
        return True
    return False


def _clear_field(field_value: Any, domain_by_integration_id: dict[int, dict]) -> int:
    """Clear off-domain sender addresses in a workflow field. Returns the count.

    `actions` is stored as a list; `draft` is the full flow dict that nests its actions under
    `actions`. Both are mutated in place, so saving the whole field persists the change.
    """
    actions = field_value.get("actions") if isinstance(field_value, dict) else field_value
    if not isinstance(actions, list):
        return 0
    cleared = 0
    for action in actions:
        if not isinstance(action, dict) or action.get("type") != "function_email":
            continue
        inputs = (action.get("config") or {}).get("inputs")
        if not isinstance(inputs, dict):
            continue
        for input_value in inputs.values():
            value = input_value.get("value") if isinstance(input_value, dict) else None
            from_value = value.get("from") if isinstance(value, dict) else None
            if isinstance(from_value, dict) and clear_off_domain_from_email(from_value, domain_by_integration_id):
                cleared += 1
    return cleared


class Command(BaseCommand):
    help = (
        "Clear a workflow email step's stored sender address when it is not on the selected sender's "
        "verified domain. An old sender picker persisted a placeholder address the author never typed; "
        "the editor renders it as a deliberate custom sender and the runtime silently ignores it."
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--dry-run", action="store_true", help="Report what would change, write nothing")
        parser.add_argument(
            "--team-id",
            type=int,
            nargs="+",
            help="Team(s) to scan. Required unless --all-teams is passed.",
        )
        parser.add_argument(
            "--all-teams",
            action="store_true",
            help="Scan every team. Without this, --team-id is mandatory.",
        )
        parser.add_argument("--id", dest="row_id", type=str, help="Limit to one workflow")
        parser.add_argument("--batch-size", type=int, default=100, help="Rows per batch (default 100)")
        parser.add_argument("--list-rows", action="store_true", help="Print every affected workflow id")

    def handle(self, *args: Any, **options: Any) -> None:
        self._domain_cache: dict[int, dict[int, dict]] = {}
        dry_run: bool = options["dry_run"]
        team_ids: list[int] | None = options.get("team_id")
        all_teams: bool = options["all_teams"]
        # Team scope is opt-in in both directions so a run that forgets --team-id can't sweep every
        # customer's workflows by accident.
        if not team_ids and not all_teams:
            raise CommandError("Pass --team-id <id> [<id> ...], or --all-teams to scan every team")
        if team_ids and all_teams:
            raise CommandError("Pass either --team-id or --all-teams, not both")
        if options["batch_size"] < 1:
            raise CommandError("--batch-size must be 1 or more")

        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN - no writes"))
        scope = "ALL TEAMS" if all_teams else f"team(s) {', '.join(str(t) for t in team_ids or [])}"
        self.stdout.write(f"Scope: {scope}")

        base_queryset = HogFlow.objects.all()
        if team_ids:
            base_queryset = base_queryset.filter(team_id__in=team_ids)
        if options.get("row_id"):
            base_queryset = base_queryset.filter(id=options["row_id"])

        row_ids = list(base_queryset.order_by("id").values_list("id", flat=True))
        self.stdout.write(f"{len(row_ids)} workflow(s) to scan")

        counts = ClearCounts()
        batch_size: int = options["batch_size"]
        for start in range(0, len(row_ids), batch_size):
            for row_id in row_ids[start : start + batch_size]:
                counts.rows_scanned += 1
                try:
                    cleared = self._process_row(row_id, dry_run=dry_run)
                except Exception as e:
                    counts.errors += 1
                    logger.exception("Failed to process workflow %s: %s", row_id, e)
                    self.stdout.write(self.style.ERROR(f"  {row_id}: {e}"))
                    continue
                if cleared:
                    counts.rows_changed += 1
                    counts.senders_cleared += cleared
                    if options["list_rows"]:
                        self.stdout.write(f"  {row_id}: {cleared} sender(s) cleared")

        summary = (
            f"\n{'Would clear' if dry_run else 'Cleared'}: {counts.senders_cleared} sender(s) across "
            f"{counts.rows_changed} workflow(s). Scanned {counts.rows_scanned}. Errors: {counts.errors}"
        )
        self.stdout.write(self.style.SUCCESS(summary) if not counts.errors else self.style.ERROR(summary))

        if counts.errors:
            raise CommandError(f"{counts.errors} workflow(s) failed - see the errors above and re-run")

    def _domain_by_integration_id(self, team_id: int) -> dict[int, dict]:
        # Cache per team: an all-teams run scans many workflows per team, all needing the same lookup.
        if team_id not in self._domain_cache:
            self._domain_cache[team_id] = {
                integration.id: integration.config
                for integration in Integration.objects.filter(team_id=team_id, kind="email")
            }
        return self._domain_cache[team_id]

    def _process_row(self, row_id: Any, dry_run: bool) -> int:
        if dry_run:
            row = HogFlow.objects.get(pk=row_id)
            domain_by_integration_id = self._domain_by_integration_id(row.team_id)
            return sum(_clear_field(getattr(row, field), domain_by_integration_id) for field in FIELD_TIMESTAMPS)

        # Re-read under a row lock and mutate that copy, not the one the id scan saw, so a customer
        # saving the same workflow in between is not overwritten by a stale blob.
        with transaction.atomic():
            row = HogFlow.objects.select_for_update().get(pk=row_id)
            domain_by_integration_id = self._domain_by_integration_id(row.team_id)

            changed_fields: list[str] = []
            cleared = 0
            for field in FIELD_TIMESTAMPS:
                field_cleared = _clear_field(getattr(row, field), domain_by_integration_id)
                if field_cleared:
                    changed_fields.append(field)
                    cleared += field_cleared

            if not cleared:
                return 0

            timestamp_fields: list[str] = []
            live_change = False
            for field in changed_fields:
                timestamp_field = FIELD_TIMESTAMPS[field]
                live_change = live_change or timestamp_field == "updated_at"
                if timestamp_field in timestamp_fields:
                    continue
                timestamp_fields.append(timestamp_field)
                # updated_at is auto_now, so listing it is enough; the rest need an explicit value.
                if timestamp_field != "updated_at":
                    setattr(row, timestamp_field, timezone.now())

            row.save(update_fields=[*changed_fields, *timestamp_fields])

            # A live edit needs workers to drop their cached copy. Publish on commit so a worker
            # can't re-read the row before the UPDATE lands; a draft-only change executes nowhere.
            if live_change:
                team_id, row_pk = row.team_id, str(row.pk)
                transaction.on_commit(lambda: reload_hog_flows_on_workers(team_id=team_id, hog_flow_ids=[row_pk]))

        return cleared
