import statistics
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from products.growth.backend.facade import api, contracts

_NO_ACTIVE_LISTS = (
    "No active IcpScoringConfig row. Seed one with sync_icp_scoring_lists --activate "
    "(or pass --tags-csv/--investors-csv)."
)
_LISTS_INCOMPLETE = "--tags-csv and --investors-csv must be given together"
_REGION_NOT_ALLOWED = "Signup enrichment is Cloud-only; refusing to backfill in this region"


class _Stats:
    def __init__(self) -> None:
        self.statuses: dict[str, int] = {}
        self.scores: list[int] = []

    def add(self, status: str, score: int | None) -> None:
        self.statuses[status] = self.statuses.get(status, 0) + 1
        if status == "scored" and score is not None:
            self.scores.append(score)

    def summary(self) -> str:
        total = sum(self.statuses.values())
        lines = [f"evaluated {total}"]
        for status, count in sorted(self.statuses.items(), key=lambda kv: -kv[1]):
            lines.append(f"  {status}: {count} ({count / total:.1%})")
        if self.scores:
            ordered = sorted(self.scores)
            share = lambda threshold: sum(1 for s in ordered if s >= threshold) / len(ordered)  # noqa: E731
            lines.append(
                f"  scored: median {statistics.median(ordered):.0f} | "
                f">=40 {share(40):.1%} | >=50 {share(50):.1%} | >=60 {share(60):.1%} | >=70 {share(70):.1%}"
            )
        return "\n".join(lines)


class Command(BaseCommand):
    help = (
        "Recompute ICP fit scores from each organization's latest archived provider fetch "
        "and write the score keys (fit-only; firmographic fields are "
        "backfill_enrichment_fields' job). --parity scores payload files from disk against "
        "an expected CSV instead, with no writes."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--limit", type=int, default=None, help="Backfill at most this many organizations")
        parser.add_argument("--delay", type=float, default=0.05, help="Seconds to sleep between writes")
        parser.add_argument("--dry-run", action="store_true", help="Report what would be written without writing")
        parser.add_argument("--stats", action="store_true", help="Print the score distribution summary at the end")
        parser.add_argument("--parity", action="store_true", help="Offline parity mode: no DB writes")
        parser.add_argument("--payloads", help="Parity: JSONL(.gz) file or directory of payload JSON files")
        parser.add_argument("--expected", help="Parity: CSV of expected score/status per domain")
        parser.add_argument("--tags-csv", help="Score with lists parsed from this tags export instead of the DB row")
        parser.add_argument("--investors-csv", help="Goes with --tags-csv")

    def handle(self, *args: Any, **options: Any) -> None:
        if options["parity"]:
            self._run_parity(options)
            return
        self._run_backfill(options)

    def _run_backfill(self, options: dict[str, Any]) -> None:
        try:
            api.ensure_fit_backfill_allowed()
        except contracts.RegionNotAllowed:
            raise CommandError(_REGION_NOT_ALLOWED)

        limit: int | None = options["limit"]
        delay: float = options["delay"]
        dry_run: bool = options["dry_run"]
        if limit is not None and limit < 1:
            raise CommandError("--limit must be a positive integer")
        if delay < 0:
            raise CommandError("--delay must be >= 0")

        try:
            items = api.backfill_icp_fit_scores(
                limit=limit,
                delay=delay,
                dry_run=dry_run,
                tags_csv=options.get("tags_csv"),
                investors_csv=options.get("investors_csv"),
            )
        except contracts.RegionNotAllowed:
            raise CommandError(_REGION_NOT_ALLOWED)
        except contracts.ScoringListsIncomplete:
            raise CommandError(_LISTS_INCOMPLETE)
        except contracts.NoActiveScoringLists:
            raise CommandError(_NO_ACTIVE_LISTS)
        except contracts.NoRegionalClient:
            raise CommandError("no PostHog client for this instance's region; refusing to backfill")

        stats = _Stats()
        verb = "would write" if dry_run else "wrote"
        considered = 0
        outcomes: dict[contracts.FitBackfillOutcome, int] = {
            "written": 0,
            "skipped_org_gone": 0,
            "skipped_wizard_unavailable": 0,
        }
        for item in items:
            considered += 1
            outcomes[item.outcome] += 1
            if item.outcome == "written" and item.status is not None:
                stats.add(item.status, item.score)
                self.stdout.write(f"{verb} {item.organization_id}: {item.status} score={item.score}")

        self.stdout.write(
            self.style.SUCCESS(
                f"considered {considered}, {verb} {outcomes['written']}, "
                f"skipped_org_gone {outcomes['skipped_org_gone']}, "
                f"skipped_wizard_unavailable {outcomes['skipped_wizard_unavailable']}"
            )
        )
        if options["stats"]:
            self.stdout.write(stats.summary())

    def _run_parity(self, options: dict[str, Any]) -> None:
        if not options.get("payloads"):
            raise CommandError("--parity requires --payloads")
        try:
            run = api.score_parity(
                payloads=options["payloads"],
                expected=options.get("expected"),
                tags_csv=options.get("tags_csv"),
                investors_csv=options.get("investors_csv"),
            )
        except contracts.ScoringListsIncomplete:
            raise CommandError(_LISTS_INCOMPLETE)
        except contracts.NoActiveScoringLists:
            raise CommandError(_NO_ACTIVE_LISTS)

        stats = _Stats()
        mismatches = 0
        compared = 0
        for item in run.items:
            stats.add(item.status, item.score)
            if item.diffs is None:
                continue
            compared += 1
            if item.diffs:
                mismatches += 1
                self.stdout.write(f"MISMATCH {item.domain}: " + ", ".join(item.diffs))

        self.stdout.write(stats.summary())
        if run.expectations:
            self.stdout.write(f"compared {compared} against expected; mismatches {mismatches}")
            if mismatches:
                raise CommandError(f"parity failed: {mismatches} mismatches")
            self.stdout.write(self.style.SUCCESS("parity passed"))
