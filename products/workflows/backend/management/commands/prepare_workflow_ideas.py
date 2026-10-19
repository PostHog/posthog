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
        "Generate workflow ideas for the given projects and build each one now, so the ideas wait for the team on "
        f"the workflows page and a click creates the draft at once. Only organizations with {FEATURE_FLAG_KEY} get "
        "ideas. This runs the models, so it only runs for the IDs you pass."
    )

    def add_arguments(self, parser):
        parser.add_argument("--team-ids", type=int, nargs="+", default=[], help="Project IDs to prepare ideas for.")
        parser.add_argument(
            "--org-ids", nargs="+", default=[], help="Organization IDs. Every project in them gets ideas."
        )
        parser.add_argument(
            "--replace",
            action="store_true",
            help="Replace the ideas a project still has waiting. Without it, those projects are skipped.",
        )

    def handle(self, *args, **options):
        team_ids: list[int] = options["team_ids"]
        org_ids: list[str] = options["org_ids"]
        if not team_ids and not org_ids:
            raise CommandError("Pass --team-ids or --org-ids. There is no default, because this runs the models.")

        teams = {
            team.id: team
            for team in Team.objects.select_related("organization").filter(id__in=team_ids, parent_team_id__isnull=True)
        }
        teams.update(
            {
                team.id: team
                for team in Team.objects.select_related("organization").filter(
                    organization_id__in=org_ids, parent_team_id__isnull=True
                )
            }
        )
        for missing in sorted(set(team_ids) - set(teams)):
            self.stdout.write(f"team {missing}: skipped, no such project")
        if not teams:
            raise CommandError("No projects found for the IDs given.")

        for team in sorted(teams.values(), key=lambda item: item.id):
            self.stdout.write(f"team {team.id}: {self._prepare(team, replace=options['replace'])}")

    def _prepare(self, team: Team, *, replace: bool) -> str:
        user = data_suggestions_acting_user(team)
        if user is None:
            return f"skipped, organization {team.organization_id} has no active owner or admin"
        if not is_data_suggestions_enabled(user, str(team.organization_id)):
            return f"skipped, {FEATURE_FLAG_KEY} is off for organization {team.organization_id}"
        waiting = waiting_premade_count(team.id)
        if waiting and not replace:
            return f"skipped, {waiting} waiting (pass --replace to make new ones)"
        # The draft check reads team-scoped rows, and a command has no request to set the team.
        with team_scope(team.id):
            result = prepare_premade_ideas(
                team=team,
                user=user,
                validate_draft=lambda draft_team, workflow: validated_draft(draft_team, workflow, EventSource.WEB),
                replace=replace,
            )
        if result.status != "ready":
            return f"no ideas, suggestions are {result.status}"
        stored = ", ".join(result.stored) or "none"
        return f"stored {len(result.stored)} ({stored}), {result.failed_builds} failed to build"
