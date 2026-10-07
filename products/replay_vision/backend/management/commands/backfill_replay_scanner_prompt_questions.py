from typing import Any

from django.core.management.base import BaseCommand, CommandParser

from products.replay_vision.backend.prompt_questions import backfill_prompt_questions


class Command(BaseCommand):
    help = "Condense each Replay Vision scanner's prompt into the question the observation page shows"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--team-id", type=int, default=None, help="Only this team's scanners")
        parser.add_argument(
            "--include-inline",
            action="store_true",
            help="Also give inline scanners a template's question; they never get a model-written one",
        )
        parser.add_argument("--limit", type=int, default=None, help="Stop after writing this many questions")
        parser.add_argument("--dry-run", action="store_true", help="Count the scanners due a question, write nothing")

    def handle(self, *args: Any, **options: Any) -> None:
        result = backfill_prompt_questions(
            team_id=options["team_id"],
            include_inline=bool(options["include_inline"]),
            limit=options["limit"],
            dry_run=bool(options["dry_run"]),
        )
        verb = "Would write" if options["dry_run"] else "Wrote"
        self.stdout.write(f"Checked {result.checked} scanners. {verb} {result.written} questions.")
