"""
Ingest raw external source records from a JSON file through a registered emitter, then emit as signals.

Usage:
    python manage.py ingest_source_json path/to/records.json --team-id 1 --source-type Linear --schema-name issues

The JSON file should contain an array of record objects matching the format the emitter expects
(same field names as the data warehouse table). See existing emitters for expected fields:
  - Linear issues: id, title, description, url, identifier, number, priority, ...
  - GitHub issues: id, title, body, html_url, number, labels, ...
  - Zendesk tickets: id, subject, description, url, type, tags, ...
"""

import json
import asyncio
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from posthog.models import Team
from posthog.temporal.data_imports.signals.registry import _SIGNAL_TABLE_CONFIGS, SignalEmitterOutput, get_signal_config
from posthog.temporal.data_imports.workflow_activities.emit_signals import _build_emitter_outputs

from products.signals.backend.api import emit_signal


class Command(BaseCommand):
    help = "Ingest raw source records from a JSON file through a registered signal emitter, then emit as signals."

    def add_arguments(self, parser):
        parser.add_argument("file", type=str, help="Path to JSON file (array of record objects)")
        parser.add_argument("--team-id", type=int, required=True, help="Team ID to emit signals for")
        parser.add_argument(
            "--source-type",
            type=str,
            required=True,
            help="External data source type (e.g., Linear, GitHub, Zendesk)",
        )
        parser.add_argument(
            "--schema-name",
            type=str,
            required=True,
            help="Schema/table name (e.g., issues, tickets)",
        )
        parser.add_argument("--limit", type=int, default=None, help="Max records to process")
        parser.add_argument("--dry-run", action="store_true", help="Run emitter but don't emit signals")

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("This command can only be run with DEBUG=True")

        file_path = Path(options["file"])
        if not file_path.exists():
            raise CommandError(f"File does not exist: {file_path}")

        source_type = options["source_type"]
        schema_name = options["schema_name"]

        config = get_signal_config(source_type, schema_name)
        if config is None:
            registered = ", ".join(f"{st}/{sn}" for st, sn in _SIGNAL_TABLE_CONFIGS)
            raise CommandError(f"No emitter registered for {source_type}/{schema_name}. Registered: {registered}")

        try:
            team = Team.objects.get(id=options["team_id"])
        except Team.DoesNotExist:
            raise CommandError(f"Team {options['team_id']} not found")

        with open(file_path) as f:
            records = json.load(f)

        if not isinstance(records, list):
            raise CommandError("JSON file must contain an array of record objects")

        if options["limit"]:
            records = records[: options["limit"]]

        self.stdout.write(f"Processing {len(records)} records through {source_type}/{schema_name} emitter")

        outputs = _build_emitter_outputs(team_id=team.id, records=records, emitter=config.emitter)
        skipped = len(records) - len(outputs)
        self.stdout.write(f"Emitter produced {len(outputs)} signals ({skipped} records skipped)")

        if not outputs:
            self.stdout.write(self.style.WARNING("No signals to emit"))
            return

        if options["dry_run"]:
            for output in outputs:
                self.stdout.write(
                    f"  [{output.source_product}/{output.source_type}] {output.source_id}: {output.description[:100]}..."
                )
            self.stdout.write(self.style.SUCCESS(f"Dry run complete. {len(outputs)} signals would be emitted."))
            return

        asyncio.run(self._emit(team, outputs))

    async def _emit(self, team: Team, outputs: list[SignalEmitterOutput]):
        success = 0
        failed = 0

        for i, output in enumerate(outputs):
            try:
                await emit_signal(
                    team=team,
                    source_product=output.source_product,
                    source_type=output.source_type,
                    source_id=output.source_id,
                    description=output.description,
                    weight=output.weight,
                    extra=output.extra,
                )
                success += 1
                self.stdout.write(f"  [{i + 1}/{len(outputs)}] Emitted {output.source_id}")
            except Exception as e:
                self.stderr.write(self.style.ERROR(f"  [{i + 1}/{len(outputs)}] Failed {output.source_id}: {e}"))
                failed += 1

        self.stdout.write(
            self.style.SUCCESS(f"Done. {success} signals emitted, {failed} failed out of {len(outputs)} total.")
        )
