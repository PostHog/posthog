import asyncio
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from posthog.models import Team

from products.signals.backend.ingest import IngestResult, ingest_signals, parse_signals_json


class Command(BaseCommand):
    help = (
        "Ingest signals from an exported signals.json file via emit_signal().\n\n"
        "Generate the input file with:\n"
        '  posthog-cli exp query run "select product, document_type, document_id, timestamp, '
        "inserted_at, content, metadata from document_embeddings where model_name = "
        "'text-embedding-3-small-1536' and product = 'signals' limit 1000\" > signals.json"
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "file",
            type=str,
            help="Path to the signals JSON file to ingest",
        )
        parser.add_argument(
            "--team-id",
            type=int,
            required=True,
            help="Team ID to emit signals for",
        )

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("This command can only be run with DEBUG=True")

        file_path = Path(options["file"])
        if not file_path.exists():
            raise CommandError(f"File does not exist: {file_path}")

        try:
            team = Team.objects.get(id=options["team_id"])
        except Team.DoesNotExist:
            raise CommandError(f"Team {options['team_id']} not found")

        with open(file_path) as f:
            rows = parse_signals_json(f)

        if not rows:
            raise CommandError(f"No valid signal rows found in {file_path}")

        self.stdout.write(f"Found {len(rows)} signals to ingest for team {team.id}")

        result: IngestResult = asyncio.run(ingest_signals(team, rows))

        for error in result.errors:
            self.stderr.write(self.style.ERROR(error))

        self.stdout.write(
            self.style.SUCCESS(
                f"Done. {result.success} signals emitted, {result.failed} failed out of {result.total} total."
            )
        )
