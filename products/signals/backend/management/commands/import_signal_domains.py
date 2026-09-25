import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from pydantic import ValidationError

from products.signals.backend.facade.api import import_signal_product_domains


class Command(BaseCommand):
    help = (
        "Preview or apply product domains using owners.yaml and an explicit repository-owner to project-role mapping."
    )

    def add_arguments(self, parser):
        parser.add_argument("--team-id", type=int, required=True)
        parser.add_argument("--repo-root", type=Path, required=True)
        parser.add_argument("--definitions", type=Path, required=True)
        parser.add_argument(
            "--apply", action="store_true", help="Persist the reviewed import. Default is preview only."
        )

    def handle(self, *args, **options):
        try:
            result = import_signal_product_domains(
                team_id=options["team_id"],
                repo_root=str(options["repo_root"]),
                definitions_json=options["definitions"].read_text(),
                apply=options["apply"],
            )
        except (OSError, ValueError, ValidationError) as error:
            raise CommandError(str(error)) from error
        self.stdout.write(json.dumps({"applied": options["apply"], "domains": result}, indent=2))
