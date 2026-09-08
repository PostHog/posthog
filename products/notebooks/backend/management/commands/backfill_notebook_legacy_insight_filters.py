"""Rewrite notebook query nodes still holding legacy snake_case insight filters."""

from typing import Any

from django.core.management.base import BaseCommand, CommandError

from products.notebooks.backend.legacy_insight_filters import (
    MAX_BACKFILL_BATCH_SIZE,
    NotebookLegacyFilterBackfill,
    backfill_notebook_legacy_insight_filters,
)


class Command(BaseCommand):
    help = (
        "Rewrite legacy snake_case insight filters in stored notebook content into the current "
        "camelCase schema. Runs as a dry run unless --write is passed."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--write",
            action="store_true",
            help="Persist the rewrite. Without this the command only reports what it would change.",
        )
        parser.add_argument(
            "--team-id",
            type=int,
            default=None,
            help="Restrict to one team. Defaults to every team.",
        )
        parser.add_argument(
            "--short-id",
            action="append",
            dest="short_ids",
            default=None,
            help="Restrict to one notebook short id. Repeat the flag for several.",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=None,
            help=f"Stop after rewriting this many notebooks (max {MAX_BACKFILL_BATCH_SIZE}).",
        )
        parser.add_argument(
            "--include-deleted",
            action="store_true",
            help="Also rewrite notebooks marked deleted. They render for nobody, so skipped by default.",
        )
        parser.add_argument(
            "--list-notebooks",
            action="store_true",
            help="Print the team id and short id of every notebook that changed.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        try:
            result = backfill_notebook_legacy_insight_filters(
                team_id=options["team_id"],
                short_ids=options["short_ids"],
                dry_run=not options["write"],
                batch_size=options["batch_size"],
                include_deleted=options["include_deleted"],
            )
        except ValueError as error:
            raise CommandError(str(error)) from error

        self._report(result, list_notebooks=options["list_notebooks"])

    def _report(self, result: NotebookLegacyFilterBackfill, *, list_notebooks: bool) -> None:
        if result.dry_run:
            self.stdout.write(
                f"Scanned {result.scanned} notebook(s). {result.rewritten} would change. Nothing was written."
            )
        else:
            self.stdout.write(f"Scanned {result.scanned} notebook(s). Rewrote {result.rewritten}.")

        for shape, count in sorted(result.shapes.items()):
            self.stdout.write(f"  {shape}: {count} node(s)")

        if result.unparseable_queries:
            self.stdout.write(
                self.style.WARNING(
                    f"  {result.unparseable_queries} query string(s) were not valid JSON and were left untouched"
                )
            )

        if list_notebooks:
            for ref in result.rewritten_notebooks:
                self.stdout.write(f"  team {ref.team_id} notebook {ref.short_id}")

        if result.dry_run and result.rewritten:
            self.stdout.write("Re-run with --write to persist.")
