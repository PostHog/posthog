from django.core.management.base import BaseCommand, CommandError

from posthog.models.scoping.manager import resolve_effective_team_id

from products.tasks.backend.models import Channel, Task
from products.tasks.backend.search_index import rebuild_team_search_index


class Command(BaseCommand):
    help = "Rebuild the Desktop task/PR/artifact/space search projection for one project"

    def add_arguments(self, parser):
        parser.add_argument("team_id", type=int, nargs="?")
        parser.add_argument("--all", action="store_true", dest="all_teams")

    def handle(self, *args, **options):
        team_id = options["team_id"]
        if options["all_teams"] == (team_id is not None):
            raise CommandError("Pass exactly one of team_id or --all")
        if options["all_teams"]:
            source_team_ids = set(Task.objects.values_list("team_id", flat=True).distinct())
            source_team_ids.update(Channel.objects.values_list("team_id", flat=True).distinct())
            team_ids = sorted({resolve_effective_team_id(source_team_id) for source_team_id in source_team_ids})
        else:
            team_ids = [team_id]
        for current_team_id in team_ids:
            rebuild_team_search_index(current_team_id)
            self.stdout.write(f"Rebuilt task search index for team {current_team_id}")
        self.stdout.write(self.style.SUCCESS("Task search index rebuild complete"))
