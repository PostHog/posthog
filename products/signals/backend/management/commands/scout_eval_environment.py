from __future__ import annotations

import argparse

from django.core.management.base import BaseCommand, CommandError

from products.signals.backend.scout_harness.eval_environment.cli import add_arguments, execute


class Command(BaseCommand):
    help = "Prepare, freeze, inspect, and run a private scout evaluation environment against local PostHog."

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        add_arguments(parser)

    def handle(self, *args: object, **options: object) -> None:
        if execute(argparse.Namespace(**options)):
            raise CommandError("The scout evaluation command did not complete.")
