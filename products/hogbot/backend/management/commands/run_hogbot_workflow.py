from django.core.management.base import BaseCommand, CommandError

from posthog.models import Team

from products.hogbot.backend.gateway import get_or_start_hogbot


class Command(BaseCommand):
    help = "Start the hogbot workflow for a team and print the returned connection info"

    def add_arguments(self, parser):
        parser.add_argument("--team-id", type=int, required=True, help="Team ID to run hogbot for")
        parser.add_argument(
            "--server-command",
            type=str,
            required=True,
            help="Command used to start the hogbot server inside the sandbox",
        )

    def handle(self, *args, **options):
        team_id = options["team_id"]
        server_command = options["server_command"]

        if not Team.objects.filter(id=team_id).exists():
            raise CommandError(f"Team {team_id} not found")

        connection_info = get_or_start_hogbot(
            team_id=team_id,
            server_command=server_command,
            repository=None,
            github_integration_id=None,
            branch=None,
        )

        self.stdout.write(
            self.style.SUCCESS(
                "\n".join(
                    [
                        f"workflow_id: {connection_info.workflow_id}",
                        f"run_id: {connection_info.run_id}",
                        f"phase: {connection_info.phase}",
                        f"ready: {connection_info.ready}",
                        f"sandbox_id: {connection_info.sandbox_id}",
                        f"server_url: {connection_info.server_url}",
                        f"connect_token: {connection_info.connect_token}",
                    ]
                )
            )
        )
