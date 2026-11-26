import json
from dataclasses import asdict
from typing import IO, Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from posthog.models import Team

from products.workflows.backend.services.unlayer_images import (
    DEFAULT_MAX_BYTES,
    DEFAULT_MAX_IMAGES_PER_TEAM,
    RateLimiter,
    TeamReport,
    copy_team_images,
    media_base_url,
    team_ids_with_unlayer_images,
)


class Command(BaseCommand):
    help = (
        "Copy email images stored on Unlayer's servers into each team's email media library, and point the team's "
        "workflows, drafts, templates and destinations at the copies. Nothing on Unlayer is changed or deleted, and "
        "an image that can't be copied keeps its Unlayer address. Safe to run again."
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--team-id", type=int, nargs="+", help="Team(s) to migrate")
        parser.add_argument("--all-teams", action="store_true", help="Every team with an Unlayer image")
        parser.add_argument("--dry-run", action="store_true", help="Download and check images, but write nothing")
        parser.add_argument("--no-fetch", action="store_true", help="With --dry-run, skip downloading the images")
        parser.add_argument("--after-team-id", type=int, help="With --all-teams, start after this team (to resume)")
        parser.add_argument("--max-teams", type=int, help="With --all-teams, stop after this many teams")
        parser.add_argument("--rate", type=float, default=4.0, help="Requests to Unlayer per second (default 4)")
        parser.add_argument(
            "--max-bytes", type=int, default=DEFAULT_MAX_BYTES, help="Largest image to copy, in bytes (default 10 MB)"
        )
        parser.add_argument(
            "--max-images-per-team",
            type=int,
            default=DEFAULT_MAX_IMAGES_PER_TEAM,
            help="Leave a team with more images than this untouched and report it (default 1000)",
        )
        parser.add_argument("--report", type=str, help="Write one JSON line per image and row to this file")

    def handle(self, *args: Any, **options: Any) -> None:
        team_ids: list[int] | None = options.get("team_id")
        all_teams: bool = options["all_teams"]
        dry_run: bool = options["dry_run"]
        if not team_ids and not all_teams:
            raise CommandError("Pass --team-id <id> [<id> ...], or --all-teams")
        if team_ids and all_teams:
            raise CommandError("Pass either --team-id or --all-teams, not both")
        if options["no_fetch"] and not dry_run:
            raise CommandError("--no-fetch only works with --dry-run")
        if (options.get("after_team_id") is not None or options.get("max_teams") is not None) and not all_teams:
            raise CommandError("--after-team-id and --max-teams only work with --all-teams")
        if (options.get("max_teams") or 0) < 0 or (options.get("after_team_id") or 0) < 0:
            raise CommandError("--max-teams and --after-team-id can't be negative")
        if options["max_images_per_team"] < 1:
            raise CommandError("--max-images-per-team must be 1 or more")
        if options["rate"] <= 0:
            raise CommandError("--rate must be above 0")

        if all_teams:
            team_ids = team_ids_with_unlayer_images()
            if options.get("after_team_id") is not None:
                team_ids = [team_id for team_id in team_ids if team_id > options["after_team_id"]]
            if options.get("max_teams") is not None:
                team_ids = team_ids[: options["max_teams"]]

        base_url = media_base_url()
        # Copies are written into customers' emails, so they must point at an address recipients can load.
        if not settings.DEBUG and not base_url.startswith("https://"):
            raise CommandError(f"Copies would be served from {base_url}, which recipients can't load")

        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN - nothing is copied or rewritten"))
        self.stdout.write(f"Copies are served from {base_url}")
        self.stdout.write(f"{len(team_ids or [])} team(s) to process")

        limiter = RateLimiter(options["rate"])
        report_file: IO[str] | None = open(options["report"], "a") if options.get("report") else None  # noqa: SIM115
        failures = 0
        totals = {"copied": 0, "would_copy": 0, "reused": 0, "failed": 0, "replaced": 0, "left": 0}
        try:
            for team_id in team_ids or []:
                team = Team.objects.filter(pk=team_id).first()
                if team is None:
                    self.stdout.write(self.style.ERROR(f"team {team_id}: not found"))
                    failures += 1
                    continue
                try:
                    report = copy_team_images(
                        team,
                        dry_run=dry_run,
                        fetch=not options["no_fetch"],
                        limiter=limiter,
                        max_bytes=options["max_bytes"],
                        max_images=options["max_images_per_team"],
                    )
                except Exception as error:
                    # One team's failure must not stop the batch. Its rows keep their Unlayer addresses.
                    self.stdout.write(self.style.ERROR(f"team {team_id}: failed with {type(error).__name__}: {error}"))
                    failures += 1
                    continue
                if report.skipped is not None:
                    self.stdout.write(self.style.ERROR(f"team {team_id}: left untouched, {report.skipped}"))
                    failures += 1
                    continue
                failures += sum(1 for row in report.rows if row.status == "error")
                failures += sum(1 for image in report.images if image.may_succeed_later)
                for image in report.images:
                    if image.status in totals:
                        totals[image.status] += 1
                totals["replaced"] += sum(row.rewritten for row in report.rows)
                totals["left"] += sum(row.left_on_unlayer for row in report.rows)
                self.stdout.write(_summary(report))
                if report_file is not None:
                    _write_report(report_file, report)
                    report_file.flush()
        finally:
            if report_file is not None:
                report_file.close()

        self.stdout.write(
            f"Total: {totals['copied']} copied, {totals['would_copy']} would copy, {totals['reused']} reused, "
            f"{totals['failed']} failed; "
            f"{totals['replaced']} address(es) replaced, {totals['left']} still on Unlayer"
        )
        if team_ids:
            self.stdout.write(f"Last team processed: {team_ids[-1]}")
        if failures:
            # Everything that failed keeps its Unlayer address, which still works. A later run picks it up.
            raise CommandError(f"{failures} failure(s) that a later run may fix - see above, then run again")
        self.stdout.write(self.style.SUCCESS("Done"))


def _summary(report: TeamReport) -> str:
    images: dict[str, int] = {}
    for image in report.images:
        images[image.status] = images.get(image.status, 0) + 1
    rows: dict[str, int] = {}
    for row in report.rows:
        rows[row.status] = rows.get(row.status, 0) + 1
    rewritten = sum(row.rewritten for row in report.rows)
    left = sum(row.left_on_unlayer for row in report.rows)
    recovered = sum(1 for image in report.images if image.via_double_slash)
    return (
        f"team {report.team_id}: images {_counts(images)}; rows {_counts(rows)}; "
        f"{rewritten} address(es) replaced, {left} still on Unlayer, {recovered} recovered via //projects"
    )


def _counts(counts: dict[str, int]) -> str:
    return ", ".join(f"{status} {count}" for status, count in sorted(counts.items())) or "none"


def _write_report(file: IO[str], report: TeamReport) -> None:
    if report.skipped is not None:
        file.write(json.dumps({"team_id": report.team_id, "kind": "team", "skipped": report.skipped}) + "\n")
    for image in report.images:
        file.write(json.dumps({"team_id": report.team_id, "kind": "image", **asdict(image)}) + "\n")
    for row in report.rows:
        file.write(json.dumps({"team_id": report.team_id, "kind": "row", **asdict(row)}) + "\n")
