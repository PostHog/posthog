import asyncio

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from posthog.clickhouse.client import sync_execute
from posthog.models import Team

from products.error_tracking.backend.embedding import PARTITIONED_SHARDED_DOCUMENT_EMBEDDINGS
from products.error_tracking.backend.indexed_embedding import EMBEDDING_TABLES
from products.signals.backend.models import SignalReport, SignalReportArtefact
from products.signals.backend.temporal.grouping import TeamSignalGroupingWorkflow
from products.signals.backend.temporal.summary import SignalReportSummaryWorkflow

DELETE_SQL = """
ALTER TABLE {table} DELETE
WHERE product = 'signals'
  AND team_id = %(team_id)s
"""


class Command(BaseCommand):
    help = "Clean up all signals pipeline data from ClickHouse and Postgres. DEBUG only."

    def add_arguments(self, parser):
        parser.add_argument(
            "--team-id",
            type=int,
            required=True,
            help="Team ID to clean up signals for",
        )
        parser.add_argument(
            "--yes",
            action="store_true",
            help="Skip confirmation prompt",
        )

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("This command can only be run with DEBUG=True")

        try:
            team = Team.objects.get(id=options["team_id"])
        except Team.DoesNotExist:
            raise CommandError(f"Team {options['team_id']} not found")

        if not options["yes"]:
            self.stdout.write(
                self.style.WARNING(
                    f"This will DELETE all signals data for team {team.id} from ClickHouse and Postgres."
                )
            )
            confirm = input("Type 'yes' to confirm: ")
            if confirm != "yes":
                self.stdout.write("Aborted.")
                return

        # 1. Delete from all ClickHouse embedding tables
        tables_to_clean = [PARTITIONED_SHARDED_DOCUMENT_EMBEDDINGS] + [t.sharded_table_name() for t in EMBEDDING_TABLES]

        for table in tables_to_clean:
            self.stdout.write(f"Deleting signals from {table}...")
            try:
                ch_result = sync_execute(
                    DELETE_SQL.format(table=table),
                    {"team_id": team.id},
                    settings={"mutations_sync": 1},
                )
                self.stdout.write(f"  ✓ {table}: {ch_result}")
            except Exception as e:
                self.stdout.write(self.style.WARNING(f"  ✗ {table}: {e}"))

        # 2. Delete Django models (artefacts cascade from reports)
        artefact_count = SignalReportArtefact.objects.filter(team=team).count()
        report_count = SignalReport.objects.filter(team=team).count()

        self.stdout.write(f"Deleting {artefact_count} SignalReportArtefacts...")
        SignalReportArtefact.objects.filter(team=team).delete()

        self.stdout.write(f"Deleting {report_count} SignalReports...")
        SignalReport.objects.filter(team=team).delete()

        # 3. Terminate Temporal workflows
        self._terminate_workflows(team, report_count)

        self.stdout.write(
            self.style.SUCCESS(
                f"Done. Cleaned up {report_count} reports, {artefact_count} artefacts, "
                f"and ClickHouse signals from {len(tables_to_clean)} tables for team {team.id}."
            )
        )

    def _terminate_workflows(self, team, report_count):
        try:
            from posthog.temporal.common.client import sync_connect

            client = sync_connect()
        except Exception as e:
            self.stdout.write(self.style.WARNING(f"Could not connect to Temporal: {e}"))
            return

        terminated = 0

        # Terminate grouping workflow
        grouping_wf_id = TeamSignalGroupingWorkflow.workflow_id_for(team.id)
        if self._terminate_workflow(client, grouping_wf_id, "grouping"):
            terminated += 1

        # Terminate any summary workflows for this team's reports
        report_ids = list(SignalReport.objects.filter(team=team).values_list("id", flat=True))
        for rid in report_ids:
            wf_id = SignalReportSummaryWorkflow.workflow_id_for(team.id, str(rid))
            if self._terminate_workflow(client, wf_id, f"summary for {rid}"):
                terminated += 1

        if terminated:
            self.stdout.write(f"Terminated {terminated} Temporal workflow(s).")
        else:
            self.stdout.write("No running Temporal workflows to terminate.")

    def _terminate_workflow(self, client, workflow_id, label):
        try:
            handle = client.get_workflow_handle(workflow_id)
            desc = asyncio.run(handle.describe())
            if desc.status and desc.status.name == "RUNNING":
                self.stdout.write(f"Terminating {label} workflow: {workflow_id}...")
                asyncio.run(handle.terminate(reason="cleanup_signals management command"))
                return True
        except Exception:
            pass
        return False
