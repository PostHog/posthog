from argparse import ArgumentParser
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand

from products.meep.backend.facade.api import import_workspace


class Command(BaseCommand):
    help = "Import public topic and view snapshots from one owner's legacy topics.sqlite backup."

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument("database", type=Path)
        parser.add_argument("--project", type=int, required=True)
        parser.add_argument("--owner", type=int, required=True)
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args: Any, **options: Any) -> None:
        count = import_workspace(options["database"], options["project"], options["owner"], options["apply"])
        self.stdout.write(f"{count} new snapshots {'imported' if options['apply'] else 'validated (dry run)'}.")
