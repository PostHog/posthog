from typing import Any

from django.core.management.base import BaseCommand

from products.mcp_store.backend.catalog_sync import sync_mcp_catalog


class Command(BaseCommand):
    help = "Sync the code-defined MCP server catalog (catalog.py) into MCPServerTemplate rows"

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--skip-probe",
            action="store_true",
            help="Create new entries without probing them (they stay inactive until probed or activated in admin)",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        counts = sync_mcp_catalog(skip_probe=options["skip_probe"])
        self.stdout.write(
            f"created={counts.created} activated={counts.activated} updated={counts.updated} "
            f"unchanged={counts.unchanged} failed={counts.failed}"
        )
