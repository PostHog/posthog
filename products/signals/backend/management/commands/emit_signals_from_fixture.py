import json
import asyncio
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from posthog.models import Team
from posthog.temporal.data_imports.signals import get_signal_config
from posthog.temporal.data_imports.signals.pipeline import run_signal_pipeline

# Maps the CLI --type arg to (registry source_type, registry schema_name, fixture filename).
# These three sources are auto-registered at module load by registry._register_all_emitters().
_SOURCES = {
    "zendesk": ("Zendesk", "tickets", "zendesk_tickets.json"),
    "github": ("Github", "issues", "github_issues.json"),
    "linear": ("Linear", "issues", "linear_issues.json"),
}

_FIXTURES_DIR = Path(__file__).resolve().parents[3] / "eval" / "fixtures"


class Command(BaseCommand):
    help = (
        "Run the signal emission pipeline against a static fixture file (zendesk, github, or linear).\n\n"
        "Bypasses the data warehouse fetcher entirely — loads fixture records straight into "
        "run_signal_pipeline so the real emitter, summarization, actionability filter, and "
        "emit_signal path can be exercised locally without a data import or warehouse table."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--type",
            choices=sorted(_SOURCES.keys()),
            required=True,
            help="Which fixture/source to emit (zendesk, github, or linear)",
        )
        parser.add_argument(
            "--team-id",
            type=int,
            required=True,
            help="Team ID to emit signals for",
        )
        parser.add_argument(
            "--fixture",
            type=str,
            default=None,
            help=f"Optional override path to a fixture JSON file (defaults to {_FIXTURES_DIR}/<source>.json)",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Only emit N records from the fixture (useful for quick smoke tests)",
        )
        parser.add_argument(
            "--offset",
            type=int,
            default=0,
            help="Skip the first N records before applying --limit (0-indexed; e.g. --offset 1 --limit 1 emits only the second record)",
        )

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("This command can only be run with DEBUG=True")

        source_type, schema_name, default_fixture = _SOURCES[options["type"]]

        config = get_signal_config(source_type, schema_name)
        if config is None:
            raise CommandError(f"No signal config registered for {source_type}/{schema_name}")

        fixture_path = Path(options["fixture"]) if options["fixture"] else _FIXTURES_DIR / default_fixture
        if not fixture_path.exists():
            raise CommandError(f"Fixture file does not exist: {fixture_path}")

        try:
            team = Team.objects.get(id=options["team_id"])
        except Team.DoesNotExist:
            raise CommandError(f"Team {options['team_id']} not found")

        with open(fixture_path) as f:
            records = json.load(f)
        if not isinstance(records, list):
            raise CommandError(f"Fixture file must contain a JSON array, got {type(records).__name__}")

        offset = options["offset"]
        if offset < 0:
            raise CommandError(f"--offset must be a non-negative integer, got {offset}")
        if offset:
            records = records[offset:]

        limit = options["limit"]
        if limit is not None:
            if limit <= 0:
                raise CommandError(f"--limit must be a positive integer, got {limit}")
            records = records[:limit]

        self.stdout.write(
            f"Loaded {len(records)} {options['type']} records from {fixture_path}, running pipeline for team {team.id}"
        )

        result = asyncio.run(
            run_signal_pipeline(
                team=team,
                config=config,
                records=records,
                extra={"command": "emit_signals_from_fixture", "source": options["type"]},
            )
        )
        self.stdout.write(self.style.SUCCESS(f"Pipeline finished: {result}"))
