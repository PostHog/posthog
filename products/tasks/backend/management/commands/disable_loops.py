import re
import sys
import uuid
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db.models import QuerySet

from products.tasks.backend.loop_lifecycle import DEFAULT_PAUSE_MESSAGE, pause_loop
from products.tasks.backend.models import Loop

FILTER_OPTIONS = ("loop_id", "team_id", "organization_id")
REASON_PATTERN = re.compile(r"^[a-z0-9_]{1,64}$")


class Command(BaseCommand):
    help = (
        "Pause loops: set enabled=False with a disabled_reason, pause their Temporal schedules and notify "
        "their owners. Loops that are already paused or deleted are left unchanged. "
        "Pass at least one filter, or --all to pause every loop."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--reason",
            required=True,
            metavar="CODE",
            help=(
                "Stored on Loop.disabled_reason (lowercase letters, digits and underscores, max 64 chars). "
                "The desktop app has dedicated copy for known codes such as usage_limited; other codes "
                "render as auto-paused."
            ),
        )
        parser.add_argument(
            "--message",
            metavar="TEXT",
            help=f"Body of the needs-attention notification sent to each owner. Defaults to {DEFAULT_PAUSE_MESSAGE!r}",
        )
        parser.add_argument("--all", action="store_true", help="Pause every loop. Cannot be combined with filters.")
        parser.add_argument("--loop-id", nargs="+", metavar="UUID", help="Only these loops")
        parser.add_argument("--team-id", nargs="+", type=int, metavar="ID", help="Only loops in these teams")
        parser.add_argument(
            "--organization-id", nargs="+", metavar="UUID", help="Only loops in teams of these organizations"
        )
        parser.add_argument(
            "--cancel-runs",
            action="store_true",
            help="Also cancel each loop's in-flight runs and signal their sandboxes to stop",
        )
        parser.add_argument("--no-notify", action="store_true", help="Skip the needs-attention notification")
        parser.add_argument("--dry-run", action="store_true", help="List matching loops without changing anything")
        parser.add_argument("--yes", action="store_true", help="Skip the confirmation prompt")

    def handle(self, *args: Any, **options: Any) -> None:
        reason = options["reason"]
        if not REASON_PATTERN.match(reason):
            raise CommandError("--reason must be 1-64 characters of lowercase letters, digits and underscores")
        has_filters = any(options[name] for name in FILTER_OPTIONS)
        if options["all"] and has_filters:
            raise CommandError("--all cannot be combined with filters")
        if not options["all"] and not has_filters:
            raise CommandError("Pass at least one filter (--loop-id, --team-id, --organization-id) or --all")

        # Validate --loop-id against deleted loops too, so a deleted loop's id is skipped rather than
        # rejected as unknown; deleted loops are then excluded from the set we actually pause.
        matched = self._apply_filters(Loop.objects.unscoped(), options).filter(deleted=False)
        to_pause = list(matched.filter(enabled=True).select_related("created_by").order_by("team_id", "created_at"))
        already_paused = matched.count() - len(to_pause)

        for loop in to_pause:
            owner = loop.created_by.email if loop.created_by else "-"
            self.stdout.write(f"{loop.id}  team {loop.team_id}  {loop.name}  owner {owner}")
        self.stdout.write(f"{len(to_pause)} to pause, {already_paused} already paused (skipped)")

        if not to_pause:
            self.stdout.write(self.style.WARNING("No loops to pause."))
            return
        if options["dry_run"]:
            self.stdout.write(self.style.WARNING(f"Dry run: {len(to_pause)} loop(s) would be paused."))
            return

        self._confirm(
            f"Pause {len(to_pause)} loop(s) with reason {reason!r}? Type 'yes' to continue: ", yes=options["yes"]
        )

        paused = 0
        cancelled_runs = 0
        failed: list[Loop] = []
        for loop in to_pause:
            try:
                cancelled_runs += pause_loop(
                    loop,
                    reason,
                    message=options["message"],
                    cancel_runs=options["cancel_runs"],
                    notify=not options["no_notify"],
                )
                paused += 1
            except Exception as error:
                failed.append(loop)
                self.stderr.write(f"Failed to pause loop {loop.id}: {error!r}")

        summary = f"Paused {paused} loop(s) with reason {reason!r}."
        if options["cancel_runs"]:
            summary += f" Cancelled {cancelled_runs} in-flight run(s)."
        self.stdout.write(self.style.SUCCESS(summary))
        if failed:
            raise CommandError(
                f"{len(failed)} loop(s) failed part-way: {', '.join(str(loop.id) for loop in failed)}. "
                "Re-running skips any that were already marked paused, so check their schedules and runs by hand."
            )

    def _apply_filters(self, queryset: QuerySet[Loop], options: dict[str, Any]) -> QuerySet[Loop]:
        if options["loop_id"]:
            loop_ids = self._parse_uuids(options["loop_id"], "--loop-id")
            queryset = queryset.filter(id__in=loop_ids)
            found = set(queryset.values_list("id", flat=True))
            unknown = sorted(str(loop_id) for loop_id in loop_ids if loop_id not in found)
            if unknown:
                raise CommandError(f"Unknown loop ids: {', '.join(unknown)}")
        if options["team_id"]:
            queryset = queryset.filter(team_id__in=options["team_id"])
        if options["organization_id"]:
            organization_ids = self._parse_uuids(options["organization_id"], "--organization-id")
            queryset = queryset.filter(team__organization_id__in=organization_ids)
        return queryset

    @staticmethod
    def _parse_uuids(raw_values: list[str], flag: str) -> list[uuid.UUID]:
        parsed: list[uuid.UUID] = []
        for raw in raw_values:
            try:
                parsed.append(uuid.UUID(raw.strip()))
            except ValueError:
                raise CommandError(f"{flag} is not a valid UUID: {raw!r}")
        return parsed

    @staticmethod
    def _confirm(prompt: str, *, yes: bool) -> None:
        if yes:
            return
        if not sys.stdin.isatty():
            raise CommandError("Refusing to pause loops non-interactively without --yes")
        if input(prompt).strip() != "yes":
            raise CommandError("Aborted.")
