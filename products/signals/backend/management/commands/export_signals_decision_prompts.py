import json
from dataclasses import replace

from django.core.management.base import BaseCommand, CommandError, CommandParser

from products.signals.backend.prompt_manifest import bundled_decision_prompts, decision_prompt_manifest
from products.signals.backend.system_one_prompts import fetch_prompt


class Command(BaseCommand):
    help = "Export current Signals decision settings and optional Jeeves wording variants; does not publish prompts."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--include-wording-experiments", action="store_true")
        parser.add_argument(
            "--verify-managed",
            action="store_true",
            help="Verify the activation label matches current bundled settings.",
        )

    def handle(self, *args: object, **options: object) -> None:
        if options["verify_managed"]:
            for baseline in bundled_decision_prompts():
                managed = fetch_prompt(baseline)
                if managed is None or replace(managed, version=None, source="bundled") != baseline:
                    raise CommandError(
                        f"{baseline.name}: activation label is missing, unreadable, or differs from bundled settings"
                    )
            self.stdout.write("All managed control prompts match bundled settings.")
            return
        self.stdout.write(json.dumps(decision_prompt_manifest(bool(options["include_wording_experiments"])), indent=2))
