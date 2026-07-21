import json
from dataclasses import asdict
from typing import cast

from django.core.management.base import BaseCommand, CommandError, CommandParser

from products.mcp_store.backend.probe import probe_mcp_server


class Command(BaseCommand):
    help = "Probe a remote MCP server end-to-end, up to the OAuth consent screen."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("url", help="URL of the MCP server to probe.")

    def handle(self, *args: object, **options: object) -> None:
        result = probe_mcp_server(cast(str, options["url"]))
        payload = {**asdict(result), "passed_activation_gate": result.passed_activation_gate}
        self.stdout.write(json.dumps(payload, indent=2))
        if not result.speaks_mcp:
            raise CommandError("Server did not respond like an MCP server")
