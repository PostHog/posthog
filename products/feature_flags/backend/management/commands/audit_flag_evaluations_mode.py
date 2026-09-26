"""List every organization whose teams hold more than one flag_evaluations mode.

TeamFeatureFlagsConfig.default_values_for_team gives a new team the highest mode of its siblings,
so the next project of a mixed organization takes the highest mode among its teams. Run this after
set_flag_evaluations_mode, and fix each organization it lists with that command.
"""

from typing import Any

from django.core.management.base import BaseCommand

from products.feature_flags.backend.flag_evaluations_mode import find_mixed_mode_organizations


class Command(BaseCommand):
    help = "List organizations whose teams hold more than one flag_evaluations mode"

    def handle(self, *args: Any, **options: Any) -> None:
        mixed = find_mixed_mode_organizations()
        for organization in mixed:
            counts = ", ".join(
                f"mode {mode}: {count} team(s)" for mode, count in sorted(organization.team_count_by_mode.items())
            )
            self.stdout.write(f"organization {organization.organization_id}: {counts}")
        self.stdout.write(f"{len(mixed)} organization(s) hold more than one mode.")
