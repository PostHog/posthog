from django.core.management.base import BaseCommand, CommandError

from products.managed_warehouse.backend.facade.api import list_moved_team_rows
from products.managed_warehouse.backend.facade.contracts import CPUnavailableError


class Command(BaseCommand):
    help = "List (or --remove) the warehouse team rows that earlier project moves left for an organization."

    def add_arguments(self, parser):
        parser.add_argument("--org", required=True, help="PostHog organization id")
        parser.add_argument("--remove", action="store_true", help="Remove the listed rows")

    def handle(self, *args, **options):
        try:
            stale = list_moved_team_rows(options["org"], remove=options["remove"])
        except (ValueError, CPUnavailableError) as error:
            raise CommandError(str(error)) from error
        for warehouse, team_ids in sorted(stale.items()):
            self.stdout.write(f"warehouse {warehouse}: teams {team_ids}")
        self.stdout.write(f"{'Removed' if options['remove'] else 'Found'} {sum(map(len, stale.values()))} rows.")
