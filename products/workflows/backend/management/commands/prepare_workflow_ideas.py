from django.core.management.base import BaseCommand, CommandError

from posthog.models import Team

from products.workflows.backend.facade.data_suggestions import (
    data_suggestions_acting_user,
    is_data_suggestions_enabled,
    prepare_data_suggestions,
)
from products.workflows.backend.models import WorkflowIdea


class Command(BaseCommand):
    help = (
        "Generate workflow ideas for projects and build each one now, so the ideas are waiting before we contact the "
        "team. Only organizations with the workflows-data-suggestions flag get ideas."
    )

    def add_arguments(self, parser):
        parser.add_argument("--team-ids", type=int, nargs="*", default=[], help="Project IDs to prepare ideas for.")
        parser.add_argument(
            "--org-ids", nargs="*", default=[], help="Organization IDs. Every project in them gets ideas."
        )
        parser.add_argument(
            "--refresh", action="store_true", help="Generate new ideas even when the project already has some."
        )

    def handle(self, *args, **options):
        teams = list(
            Team.objects.select_related("organization").filter(id__in=options["team_ids"], parent_team_id__isnull=True)
        ) + list(
            Team.objects.select_related("organization").filter(
                organization_id__in=options["org_ids"], parent_team_id__isnull=True
            )
        )
        if not teams:
            raise CommandError("No projects found. Pass --team-ids or --org-ids.")
        for team in {team.id: team for team in teams}.values():
            user = data_suggestions_acting_user(team)
            if user is None:
                self.stdout.write(f"team {team.id}: skipped, the organization has no active owner or admin")
                continue
            if not is_data_suggestions_enabled(user, str(team.organization_id)):
                self.stdout.write(f"team {team.id}: skipped, workflows-data-suggestions is off for the organization")
                continue
            result = prepare_data_suggestions(team=team, user=user, refresh=options["refresh"])
            built = (
                WorkflowIdea.objects.for_team(team.id)
                .filter(id__in=[suggestion.id for suggestion in result.suggestions])
                .exclude(definition={})
                .count()
            )
            self.stdout.write(
                f"team {team.id}: {result.status}, {len(result.suggestions)} ideas waiting, {built} built"
            )
