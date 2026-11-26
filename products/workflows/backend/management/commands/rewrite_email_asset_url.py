import json
import logging
from dataclasses import dataclass
from typing import Any

from django.core.management.base import BaseCommand, CommandError

from products.workflows.backend.services.email_content_rows import TARGETS, find_row_ids, rewrite_row

logger = logging.getLogger(__name__)


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
        counts = RewriteCounts()
        team_ids: list[int] | None = options.get("team_id")
        row_ids = find_row_ids(target, from_url, team_ids=team_ids, row_id=options.get("row_id"))

        self.stdout.write(f"{target}: {len(row_ids)} row(s) matched")
        if not row_ids:
            return counts

        batch_size: int = options["batch_size"]
        for start in range(0, len(row_ids), batch_size):
            batch = row_ids[start : start + batch_size]
            for row_id in batch:
                counts.rows_scanned += 1
                try:
                    occurrences = rewrite_row(
                        target,
                        row_id,
                        lambda blob: rewrite_blob(blob, from_url, to_url),
                        team_ids=team_ids,
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
