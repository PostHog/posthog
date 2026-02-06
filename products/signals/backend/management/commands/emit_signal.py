import uuid
import asyncio

from django.core.management.base import BaseCommand

from products.signals.backend.api import emit_signal


class Command(BaseCommand):
    help = "Emit a test signal"

    def add_arguments(self, parser):
        parser.add_argument("--team-id", type=int, required=True)
        parser.add_argument("--description", type=str, required=True)
        parser.add_argument("--weight", type=float, default=0.5)

    def handle(self, *args, **options):
        signal_id = asyncio.run(
            emit_signal(
                team_id=options["team_id"],
                source_product="test",
                source_type="test",
                source_id=str(uuid.uuid4()),
                description=options["description"],
                weight=options["weight"],
            )
        )
        self.stdout.write(self.style.SUCCESS(f"Emitted signal: {signal_id}"))
