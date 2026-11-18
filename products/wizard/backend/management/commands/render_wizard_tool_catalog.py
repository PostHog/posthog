"""Render the wizard tool catalog for the image build.

Usage:
    python manage.py render_wizard_tool_catalog
    python manage.py render_wizard_tool_catalog --output /tmp/tool-catalog.json
"""

from argparse import ArgumentParser
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand

from products.wizard.backend.tool_catalog.catalog import CATALOG_JSON, write_catalog


class Command(BaseCommand):
    help = "Render the wizard tool catalog from the warehouse source declarations to a JSON file."

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument("--output", type=Path, default=CATALOG_JSON, help="Where to write the catalog.")

    def handle(self, *args: Any, output: Path, **options: Any) -> None:
        write_catalog(output)
        self.stdout.write(f"Wrote the wizard tool catalog to {output}")
