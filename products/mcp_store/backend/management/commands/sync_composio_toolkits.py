from dataclasses import asdict

from django.core.management.base import BaseCommand, CommandParser

from products.mcp_store.backend.composio_sync import sync_composio_toolkits


class Command(BaseCommand):
    help = "Sync Composio's managed-auth toolkits into MCP server templates."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--dry-run", action="store_true", help="Report what would change without writing.")

    def handle(self, *args: object, **options: object) -> None:
        counts = sync_composio_toolkits(dry_run=bool(options["dry_run"]))
        for field, value in asdict(counts).items():
            self.stdout.write(f"{field}: {value}")
