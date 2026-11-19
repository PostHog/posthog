"""Show who a self-driving percentage would enroll for activity summary generation. The command changes nothing.

It compares the current `activity-summary` config with the same config at the given percentage, so an
operator can check each rollout step before changing the flag payload.
"""

import json
import dataclasses

from django.core.management.base import BaseCommand, CommandError

from products.signals.backend.activity_summary.config import parse_config, read_config
from products.signals.backend.activity_summary.queue import Enrollment, enrollment


class Command(BaseCommand):
    help = "Print the organizations and teams that a self-driving percentage enrolls. Writes nothing."

    def add_arguments(self, parser):
        parser.add_argument("--percentage", type=float, required=True, help="The percentage to preview, 0 to 100.")
        parser.add_argument(
            "--config",
            type=json.loads,
            default=None,
            help="A flag payload as JSON, in place of the `activity-summary` flag.",
        )
        parser.add_argument("--list", action="store_true", help="Print the ids of the organizations that change.")

    def handle(self, *args, **options):
        percentage = options["percentage"]
        if not 0 <= percentage <= 100:
            raise CommandError("--percentage must be from 0 to 100.")
        current = parse_config(options["config"]) if options["config"] is not None else read_config()
        # The preview enables the config, so it also works before the first rollout step.
        preview = dataclasses.replace(current, enabled=True, self_driving_organization_percentage=percentage)
        before = enrollment(current)
        after = enrollment(preview)
        self._write(f"current ({current.self_driving_organization_percentage}%)", before)
        self._write(f"preview ({percentage}%)", after)
        added = sorted(set(after.organization_ids) - set(before.organization_ids))
        removed = sorted(set(before.organization_ids) - set(after.organization_ids))
        self.stdout.write(f"organizations added: {len(added)}, removed: {len(removed)}")
        if options["list"]:
            for organization_id in added:
                self.stdout.write(f"+ {organization_id}")
            for organization_id in removed:
                self.stdout.write(f"- {organization_id}")

    def _write(self, label: str, result: Enrollment) -> None:
        self.stdout.write(
            f"{label}: {len(result.qualifying_organization_ids)} qualifying organizations, "
            f"{len(result.organization_ids)} enrolled organizations, {len(result.team_ids)} enrolled teams"
        )
