from django.core.management.base import BaseCommand

from posthog.event_usage import EventSource
from posthog.models import Team
from posthog.models.scoping import team_scope

from products.workflows.backend.facade.data_suggestions import (
    data_suggestions_acting_user,
    prepare_premade_ideas,
    waiting_premade_count,
)
from products.workflows.backend.presentation.views.data_suggestion_drafts import validated_draft


class Command(BaseCommand):
    help = (
        "Generate workflow ideas for the given projects and build each one now, so a click creates the draft at once. "
        "This runs the models."
    )

    def add_arguments(self, parser):
        parser.add_argument("--team-ids", type=int, nargs="+", required=True, help="Project IDs.")

    def handle(self, *args, **options):
        team_ids: list[int] = options["team_ids"]
        teams = list(
            Team.objects.select_related("organization")
            .filter(id__in=team_ids, parent_team_id__isnull=True)
            .order_by("id")
        )
        for missing in sorted(set(team_ids) - {team.id for team in teams}):
            self.stdout.write(f"team {missing}: skipped, no such project")
        for team in teams:
            self.stdout.write(f"team {team.id}: {self._prepare(team)}")

    def _prepare(self, team: Team) -> str:
        user = data_suggestions_acting_user(team)
        if user is None:
            return f"skipped, organization {team.organization_id} has no active owner or admin"
        waiting = waiting_premade_count(team.id)
        if waiting:
            return f"skipped, {waiting} ideas already waiting"
        # The draft check reads team-scoped rows, and a command has no request to set the team.
        with team_scope(team.id):
            result = prepare_premade_ideas(
                team=team,
                user=user,
                validate_draft=lambda draft_team, workflow: validated_draft(draft_team, workflow, EventSource.WEB),
            )
        if result.status != "ready":
            return f"no ideas, suggestions are {result.status}"
        return f"stored {', '.join(result.stored) or 'nothing'}, {result.failed_builds} failed to build"
