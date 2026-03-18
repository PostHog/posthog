import json
import time
import asyncio

from django.core.management.base import BaseCommand, CommandError

from posthog.schema import EmbeddingModelName

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

from posthog.models import Team

from products.signals.backend.models import SignalReport
from products.signals.backend.temporal.grouping import TeamSignalGroupingWorkflow
from products.signals.backend.temporal.summary import SignalReportSummaryWorkflow

EMBEDDING_MODEL = EmbeddingModelName.TEXT_EMBEDDING_3_SMALL_1536


class Command(BaseCommand):
    help = (
        "Show unified signal pipeline status across Temporal, ClickHouse, and Postgres.\n\n"
        "Checks the grouping workflow, ClickHouse embeddings, and SignalReport table "
        "to give a complete view of pipeline state for a team."
    )

    def add_arguments(self, parser):
        parser.add_argument("--team-id", type=int, required=True, help="Team ID to check")
        parser.add_argument("--wait", action="store_true", help="Poll until all reports reach a terminal state")
        parser.add_argument(
            "--poll-interval", type=int, default=5, help="Seconds between polls in --wait mode (default: 5)"
        )
        parser.add_argument(
            "--timeout", type=int, default=300, help="Max seconds to wait in --wait mode (default: 300)"
        )
        parser.add_argument("--json", action="store_true", dest="json_output", help="Output as JSON")
        parser.add_argument("--report-id", type=str, help="Show status for a specific report")
        parser.add_argument(
            "--expected-signals",
            type=int,
            default=0,
            help="In --wait mode, wait until at least this many signals appear in ClickHouse",
        )

    def handle(self, *args, **options):
        try:
            team = Team.objects.get(id=options["team_id"])
        except Team.DoesNotExist:
            raise CommandError(f"Team {options['team_id']} not found")

        if options["wait"]:
            self._wait_loop(team, options)
        else:
            status = self._collect_status(team, options.get("report_id"))
            self._output(status, options["json_output"])

    def _wait_loop(self, team, options):
        poll_interval = options["poll_interval"]
        timeout = options["timeout"]
        json_output = options["json_output"]
        report_id = options.get("report_id")
        expected_signals = options.get("expected_signals", 0)
        start = time.time()
        prev_ch_count = -1
        stable_polls = 0

        while True:
            status = self._collect_status(team, report_id)
            elapsed = time.time() - start

            ch_count = status["clickhouse"].get("total_signals", 0)

            if self._is_settled(status, expected_signals, ch_count, prev_ch_count, stable_polls):
                if not json_output:
                    self.stdout.write(self.style.SUCCESS(f"Pipeline settled after {elapsed:.0f}s"))
                self._output(status, json_output)
                return

            if elapsed > timeout:
                if not json_output:
                    self.stderr.write(self.style.WARNING(f"Timeout after {timeout}s — pipeline not yet settled"))
                self._output(status, json_output)
                return

            if not json_output:
                self.stdout.write(
                    f"  [{elapsed:.0f}s] waiting... (CH: {ch_count} signals, reports: {self._status_summary(status)})"
                )

            if ch_count == prev_ch_count:
                stable_polls += 1
            else:
                stable_polls = 0
            prev_ch_count = ch_count

            time.sleep(poll_interval)

    def _is_settled(self, status, expected_signals, ch_count, prev_ch_count, stable_polls):
        pg = status["postgres"]
        transient = pg.get("candidate", 0) + pg.get("in_progress", 0)
        if transient > 0:
            return False

        # If we know how many signals to expect, wait for them
        if expected_signals > 0:
            return ch_count >= expected_signals

        # Otherwise, wait for CH count to stabilize (>0 and unchanged for 2 polls)
        if ch_count == 0:
            return False
        return ch_count == prev_ch_count and stable_polls >= 1

    def _status_summary(self, status):
        pg = status["postgres"]
        parts = [f"{count} {s}" for s, count in pg.items() if s != "total" and count > 0]
        return ", ".join(parts) if parts else "no reports"

    def _collect_status(self, team, report_id=None):
        temporal_status = self._check_temporal(team, report_id)
        clickhouse_status = self._check_clickhouse(team, report_id)
        postgres_status = self._check_postgres(team, report_id)
        return {
            "team_id": team.id,
            "temporal": temporal_status,
            "clickhouse": clickhouse_status,
            "postgres": postgres_status,
        }

    def _check_temporal(self, team, report_id=None):
        try:
            from posthog.temporal.common.client import sync_connect

            client = sync_connect()
        except Exception as e:
            return {"error": f"Could not connect to Temporal: {e}"}

        result = {}

        # Check grouping workflow
        grouping_wf_id = TeamSignalGroupingWorkflow.workflow_id_for(team.id)
        result["grouping_workflow"] = self._describe_workflow(client, grouping_wf_id)

        # Check summary workflows for reports
        if report_id:
            report_ids = [report_id]
        else:
            report_ids = list(
                SignalReport.objects.filter(team=team, status__in=["candidate", "in_progress"]).values_list(
                    "id", flat=True
                )
            )

        summary_workflows = {}
        for rid in report_ids:
            wf_id = SignalReportSummaryWorkflow.workflow_id_for(team.id, str(rid))
            summary_workflows[str(rid)] = self._describe_workflow(client, wf_id)

        result["summary_workflows"] = summary_workflows
        return result

    def _describe_workflow(self, client, workflow_id):
        try:
            handle = client.get_workflow_handle(workflow_id)
            desc = asyncio.run(handle.describe())
            return {
                "workflow_id": workflow_id,
                "status": desc.status.name if desc.status else "UNKNOWN",
                "start_time": desc.start_time.isoformat() if desc.start_time else None,
                "close_time": desc.close_time.isoformat() if desc.close_time else None,
            }
        except Exception as e:
            error_str = str(e)
            if "not found" in error_str.lower() or "no rows" in error_str.lower():
                return {"workflow_id": workflow_id, "status": "NOT_FOUND"}
            return {"workflow_id": workflow_id, "status": "ERROR", "error": error_str}

    def _check_clickhouse(self, team, report_id=None):
        try:
            count_query = """
                SELECT
                    count() as total,
                    max(inserted_at) as last_inserted,
                    min(inserted_at) as first_inserted
                FROM (
                    SELECT
                        document_id,
                        argMax(metadata, inserted_at) as metadata,
                        max(inserted_at) as inserted_at
                    FROM document_embeddings
                    WHERE model_name = {model_name}
                      AND product = 'signals'
                      AND document_type = 'signal'
                    GROUP BY document_id
                )
                WHERE NOT JSONExtractBool(metadata, 'deleted')
            """
            placeholders = {"model_name": ast.Constant(value=EMBEDDING_MODEL.value)}

            if report_id:
                count_query = """
                    SELECT
                        count() as total,
                        max(inserted_at) as last_inserted,
                        min(inserted_at) as first_inserted
                    FROM (
                        SELECT
                            document_id,
                            argMax(metadata, inserted_at) as metadata,
                            max(inserted_at) as inserted_at
                        FROM document_embeddings
                        WHERE model_name = {model_name}
                          AND product = 'signals'
                          AND document_type = 'signal'
                        GROUP BY document_id
                    )
                    WHERE JSONExtractString(metadata, 'report_id') = {report_id}
                      AND NOT JSONExtractBool(metadata, 'deleted')
                """
                placeholders["report_id"] = ast.Constant(value=report_id)

            result = execute_hogql_query(
                query_type="SignalPipelineStatusCount",
                query=count_query,
                team=team,
                placeholders=placeholders,
            )

            if result.results and result.results[0]:
                total, last_inserted, first_inserted = result.results[0]
                if total == 0:
                    return {"total_signals": 0, "last_inserted": None, "first_inserted": None}
                return {
                    "total_signals": total,
                    "last_inserted": str(last_inserted) if last_inserted else None,
                    "first_inserted": str(first_inserted) if first_inserted else None,
                }
            return {"total_signals": 0, "last_inserted": None, "first_inserted": None}
        except Exception as e:
            return {"error": f"ClickHouse query failed: {e}"}

    def _check_postgres(self, team, report_id=None):
        qs = SignalReport.objects.filter(team=team)
        if report_id:
            qs = qs.filter(id=report_id)

        status_counts = {}
        total = 0
        for status_choice in SignalReport.Status:
            count = qs.filter(status=status_choice.value).count()
            if count > 0:
                status_counts[status_choice.value] = count
            total += count
        status_counts["total"] = total
        return status_counts

    def _output(self, status, json_output):
        if json_output:
            self.stdout.write(json.dumps(status, indent=2, default=str))
            return

        self.stdout.write(self.style.MIGRATE_HEADING("\nTemporal:"))
        temporal = status["temporal"]
        if "error" in temporal:
            self.stdout.write(f"  {self.style.WARNING(temporal['error'])}")
        else:
            gw = temporal["grouping_workflow"]
            style = self.style.SUCCESS if gw["status"] == "RUNNING" else self.style.WARNING
            self.stdout.write(f"  Grouping workflow: {gw['workflow_id']} — {style(gw['status'])}")
            if gw.get("start_time"):
                self.stdout.write(f"    started: {gw['start_time']}")

            sw = temporal.get("summary_workflows", {})
            if sw:
                self.stdout.write(f"  Summary workflows ({len(sw)}):")
                for rid, wf in sw.items():
                    style = self.style.SUCCESS if wf["status"] == "COMPLETED" else self.style.WARNING
                    self.stdout.write(f"    {rid}: {style(wf['status'])}")
            else:
                self.stdout.write("  Summary workflows: none in transient state")

        self.stdout.write(self.style.MIGRATE_HEADING("\nClickHouse (document_embeddings):"))
        ch = status["clickhouse"]
        if "error" in ch:
            self.stdout.write(f"  {self.style.WARNING(ch['error'])}")
        else:
            self.stdout.write(f"  Total signals: {ch['total_signals']}")
            if ch["last_inserted"]:
                self.stdout.write(f"  Last inserted: {ch['last_inserted']}")
            if ch["first_inserted"]:
                self.stdout.write(f"  First inserted: {ch['first_inserted']}")

        self.stdout.write(self.style.MIGRATE_HEADING("\nPostgres (SignalReport):"))
        pg = status["postgres"]
        if pg["total"] == 0:
            self.stdout.write("  No reports")
        else:
            for s, count in pg.items():
                if s == "total":
                    continue
                self.stdout.write(f"  {s}: {count}")
            self.stdout.write(f"  total: {pg['total']}")

        self.stdout.write("")
