import asyncio

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from posthog.clickhouse.client import sync_execute
from posthog.models import Team

from products.error_tracking.backend.embedding import PARTITIONED_SHARDED_DOCUMENT_EMBEDDINGS
from products.error_tracking.backend.indexed_embedding import EMBEDDING_TABLES
from products.signals.backend.models import SignalReport, SignalReportArtefact
from products.signals.backend.temporal.buffer import BufferSignalsWorkflow
from products.signals.backend.temporal.grouping_v2 import TeamSignalGroupingV2Workflow
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

        # Capture report metadata before deleting Postgres rows.
        report_workflow_info = list(SignalReport.objects.filter(team=team).values_list("id", "run_count"))
        artefact_count = SignalReportArtefact.objects.filter(team=team).count()
        report_count = len(report_workflow_info)

        self.stdout.write(f"Deleting {artefact_count} SignalReportArtefacts...")
        SignalReportArtefact.objects.filter(team=team).delete()

        self.stdout.write(f"Deleting {report_count} SignalReports...")
        SignalReport.objects.filter(team=team).delete()

        # 3. Terminate Temporal workflows
        self._terminate_workflows(team, report_workflow_info)

        self.stdout.write(
            self.style.SUCCESS(
                f"Done. Cleaned up {report_count} reports, {artefact_count} artefacts, "
                f"and ClickHouse signals from {len(tables_to_clean)} tables for team {team.id}."
            )
        )

    def _terminate_workflows(self, team, report_workflow_info):
        try:
            from posthog.temporal.common.client import sync_connect

            client = sync_connect()
        except Exception as e:
            self.stdout.write(self.style.WARNING(f"Could not connect to Temporal: {e}"))
            return

        terminated = 0

        # Terminate active ingestion workflows.
        buffer_wf_id = BufferSignalsWorkflow.workflow_id_for(team.id)
        if self._terminate_workflow(client, buffer_wf_id, "buffer"):
            terminated += 1

        grouping_v2_wf_id = TeamSignalGroupingV2Workflow.workflow_id_for(team.id)
        if self._terminate_workflow(client, grouping_v2_wf_id, "grouping-v2"):
            terminated += 1

        # Also terminate any leftover legacy v1 grouping workflow.
        from products.signals.backend.temporal.grouping import TeamSignalGroupingWorkflow

        legacy_grouping_wf_id = TeamSignalGroupingWorkflow.workflow_id_for(team.id)
        if self._terminate_workflow(client, legacy_grouping_wf_id, "legacy-grouping-v1"):
            terminated += 1

        # Terminate summary workflows for this team's reports.
        for rid, run_count in report_workflow_info:
            rid_str = str(rid)
            base_wf_id = SignalReportSummaryWorkflow.workflow_id_for(team.id, rid_str)
            candidate_ids = [base_wf_id]
            if run_count > 0:
                candidate_ids.extend(
                    [
                        f"{base_wf_id}:run-{run_count}",
                        f"{base_wf_id}:run-{run_count + 1}",
                    ]
                )

            for wf_id in candidate_ids:
                if self._terminate_workflow(client, wf_id, f"summary for {rid_str}"):
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
