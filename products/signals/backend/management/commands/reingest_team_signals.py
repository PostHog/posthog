from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from asgiref.sync import async_to_sync
from temporalio.common import RetryPolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

from posthog.models import Team
from posthog.temporal.common.client import async_connect

from products.signals.backend.temporal.reingestion import TeamSignalReingestionWorkflow
from products.signals.backend.temporal.types import TeamSignalReingestionWorkflowInputs


async def _start_team_signal_reingestion_workflow(team_id: int, delete_only: bool) -> None:
    client = await async_connect()
    await client.start_workflow(
        TeamSignalReingestionWorkflow.run,
        TeamSignalReingestionWorkflowInputs(team_id=team_id, delete_only=delete_only),
        id=TeamSignalReingestionWorkflow.workflow_id_for(team_id),
        task_queue=settings.VIDEO_EXPORT_TASK_QUEUE,
        execution_timeout=timedelta(hours=24),
        retry_policy=RetryPolicy(maximum_attempts=1),
    )


class Command(BaseCommand):
    help = "Start the team-wide signal reingestion workflow for a team."

    def add_arguments(self, parser):
        parser.add_argument("--team-id", type=int, required=True, help="The ID of the team to reingest signals for.")
        parser.add_argument(
            "--delete",
            action="store_true",
            dest="delete_only",
            help="Delete all team signals and clear report ORM state without re-emitting them.",
        )

    def handle(self, *args, **options):
        team_id = options["team_id"]
        delete_only = options["delete_only"]

        try:
            team = Team.objects.get(id=team_id)
        except Team.DoesNotExist as err:
            raise CommandError(f"Team {team_id} not found") from err

        workflow_id = TeamSignalReingestionWorkflow.workflow_id_for(team_id)
        action = "delete-only" if delete_only else "reingestion"

        try:
            async_to_sync(_start_team_signal_reingestion_workflow)(team_id, delete_only)
        except WorkflowAlreadyStartedError:
            self.stdout.write(
                self.style.WARNING(
                    f"Team signal {action} workflow already running for team {team_id} ({team.name}) [workflow_id={workflow_id}]"
                )
            )
            return

        self.stdout.write(
            self.style.SUCCESS(
                f"Started team signal {action} workflow for team {team_id} ({team.name}) [workflow_id={workflow_id}]"
            )
        )
