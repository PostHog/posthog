from django.core.management.base import BaseCommand, CommandError

from posthog.event_usage import EventSource
from posthog.models import Team
from posthog.models.scoping import team_scope

from products.workflows.backend.facade.data_suggestions import (
    FEATURE_FLAG_KEY,
    data_suggestions_acting_user,
    is_data_suggestions_enabled,
    prepare_premade_ideas,
    waiting_premade_count,
)
from products.workflows.backend.presentation.views.data_suggestion_drafts import validated_draft


class Command(BaseCommand):
    help = (
        "Generate workflow ideas for every project in the given organizations and build each one now, so a click "
        f"creates the draft at once. Organizations without {FEATURE_FLAG_KEY} are skipped. This runs the models."
    )

    def add_arguments(self, parser):
        parser.add_argument("--org-ids", nargs="+", required=True, help="Organization IDs.")

    def handle(self, *args, **options):
        teams = Team.objects.select_related("organization").filter(
            organization_id__in=options["org_ids"], parent_team_id__isnull=True
        )
        if not teams:
            raise CommandError("No projects found for the IDs given.")
        for team in teams:
            self.stdout.write(f"team {team.id}: {self._prepare(team)}")

    def _prepare(self, team: Team) -> str:
        user = data_suggestions_acting_user(team)
        if user is None:
            return f"skipped, organization {team.organization_id} has no active owner or admin"
        if not is_data_suggestions_enabled(user, str(team.organization_id)):
            return f"skipped, {FEATURE_FLAG_KEY} is off for organization {team.organization_id}"
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
