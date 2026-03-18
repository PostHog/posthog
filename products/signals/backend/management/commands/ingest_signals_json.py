import json
import asyncio
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from posthog.models import Team

from products.signals.backend.api import emit_signal


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

        # Each line is a JSON array, from the embedding table, is:
        # [0] "signals"       - product name
        # [1] "signal"        - document type
        # [2] uuid            - document id
        # [3] timestamp       - timestamp
        # [4] timestamp       - inserted_at
        # [5] description     - signal description text
        # [6] metadata json   - json string containing source_product, source_type, source_id, weight, extra, etc.
        rows = []
        with open(file_path) as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                    rows.append(row)
                except json.JSONDecodeError as e:
                    self.stderr.write(self.style.WARNING(f"Skipping malformed JSON on line {line_num}: {e}"))

        if not rows:
            raise CommandError(f"No valid signal rows found in {file_path}")

        self.stdout.write(f"Found {len(rows)} signals to ingest for team {team.id}")

        asyncio.run(self._ingest(team, rows))

    async def _ingest(self, team: Team, rows: list):
        success = 0
        failed = 0

        for i, row in enumerate(rows):
            try:
                description = row[5]
                metadata = json.loads(row[6]) if isinstance(row[6], str) else row[6]

                source_product = metadata.get("source_product", "unknown")
                source_type = metadata.get("source_type", "unknown")
                source_id = metadata.get("source_id", "")
                weight = metadata.get("weight", 0.5)
                extra = metadata.get("extra")

                await emit_signal(
                    team=team,
                    source_product=source_product,
                    source_type=source_type,
                    source_id=source_id,
                    description=description,
                    weight=weight,
                    extra=extra,
                )
                success += 1
            except Exception as e:
                signal_id = row[2] if len(row) > 2 else f"row {i}"
                self.stderr.write(self.style.ERROR(f"Failed to emit signal {signal_id}: {e}"))
                failed += 1

            if (i + 1) % 50 == 0:
                self.stdout.write(f"  progress: {i + 1}/{len(rows)} ({success} ok, {failed} failed)")

        self.stdout.write(
            self.style.SUCCESS(f"Done. {success} signals emitted, {failed} failed out of {len(rows)} total.")
        )
