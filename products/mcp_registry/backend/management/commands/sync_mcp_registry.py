from typing import Any

from django.core.management.base import BaseCommand

from products.mcp_registry.backend.tasks import run_sync_pipeline


class Command(BaseCommand):
    help = (
        "Run the MCP registry sync pipeline synchronously: crawl the official registry, "
        "aggregate measured servers from MCP Analytics, probe stale servers, compute rankings. "
        "Bypasses the feature-flag gate because this command is an explicit human action."
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--skip-crawl", action="store_true", help="Skip the official-registry crawl.")
        parser.add_argument("--skip-probe", action="store_true", help="Skip the liveness probe batch.")

    def handle(self, *args: Any, **options: Any) -> None:
        outcome = run_sync_pipeline(skip_crawl=options["skip_crawl"], skip_probe=options["skip_probe"])
        self.stdout.write(self.style.SUCCESS(f"mcp registry sync: {outcome}"))
