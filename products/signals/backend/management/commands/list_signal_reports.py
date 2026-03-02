import json
import textwrap

from django.core.management.base import BaseCommand, CommandError

from posthog.schema import EmbeddingModelName

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

from posthog.models import Team

from products.signals.backend.models import SignalReport, SignalReportArtefact

EMBEDDING_MODEL = EmbeddingModelName.TEXT_EMBEDDING_3_SMALL_1536


class Command(BaseCommand):
    help = (
        "List signal reports with their grouped signals and artefacts.\n\n"
        "Shows reports from Postgres with optional signal details from ClickHouse."
    )

    def add_arguments(self, parser):
        parser.add_argument("--team-id", type=int, required=True, help="Team ID")
        parser.add_argument(
            "--status",
            type=str,
            help="Filter by status (potential, candidate, in_progress, ready, pending_input, failed)",
        )
        parser.add_argument("--report-id", type=str, help="Show a specific report")
        parser.add_argument("--signals", action="store_true", help="Include full signal details from ClickHouse")
        parser.add_argument("--json", action="store_true", dest="json_output", help="Output as JSON")
        parser.add_argument("--limit", type=int, default=50, help="Max reports to show (default: 50)")

    def handle(self, *args, **options):
        try:
            team = Team.objects.get(id=options["team_id"])
        except Team.DoesNotExist:
            raise CommandError(f"Team {options['team_id']} not found")

        qs = SignalReport.objects.filter(team=team).order_by("-signal_count")

        if options["report_id"]:
            qs = qs.filter(id=options["report_id"])
        if options["status"]:
            if options["status"] not in SignalReport.Status.values:
                raise CommandError(
                    f"Invalid status: {options['status']}. Valid: {', '.join(SignalReport.Status.values)}"
                )
            qs = qs.filter(status=options["status"])

        reports = list(qs[: options["limit"]])

        if not reports:
            if options["json_output"]:
                self.stdout.write(json.dumps({"reports": [], "count": 0}))
            else:
                self.stdout.write("No reports found.")
            return

        include_signals = options["signals"] or options["report_id"]
        report_data = []
        for report in reports:
            entry = self._build_report_entry(team, report, include_signals)
            report_data.append(entry)

        if options["json_output"]:
            self.stdout.write(json.dumps({"reports": report_data, "count": len(report_data)}, indent=2, default=str))
        else:
            self._print_reports(report_data, include_signals)

    def _build_report_entry(self, team, report, include_signals):
        entry = {
            "id": str(report.id),
            "title": report.title,
            "summary": report.summary,
            "status": report.status,
            "signal_count": report.signal_count,
            "total_weight": report.total_weight,
            "created_at": report.created_at.isoformat(),
            "updated_at": report.updated_at.isoformat(),
            "promoted_at": report.promoted_at.isoformat() if report.promoted_at else None,
            "last_run_at": report.last_run_at.isoformat() if report.last_run_at else None,
            "error": report.error,
        }

        # Artefacts
        artefacts = SignalReportArtefact.objects.filter(report=report)
        entry["artefacts"] = []
        for art in artefacts:
            try:
                content = json.loads(art.content)
            except (json.JSONDecodeError, TypeError):
                content = art.content
            entry["artefacts"].append(
                {
                    "type": art.type,
                    "content": content,
                }
            )

        # Signals from ClickHouse
        if include_signals:
            entry["signals"] = self._fetch_signals(team, report)

        return entry

    def _fetch_signals(self, team, report):
        try:
            query = """
                SELECT
                    document_id,
                    content,
                    metadata,
                    toString(timestamp) as timestamp
                FROM (
                    SELECT
                        document_id,
                        argMax(content, inserted_at) as content,
                        argMax(metadata, inserted_at) as metadata,
                        argMax(timestamp, inserted_at) as timestamp
                    FROM document_embeddings
                    WHERE model_name = {model_name}
                      AND product = 'signals'
                      AND document_type = 'signal'
                    GROUP BY document_id
                )
                WHERE JSONExtractString(metadata, 'report_id') = {report_id}
                  AND NOT JSONExtractBool(metadata, 'deleted')
                ORDER BY timestamp ASC
            """
            result = execute_hogql_query(
                query_type="SignalReportListFetchSignals",
                query=query,
                team=team,
                placeholders={
                    "model_name": ast.Constant(value=EMBEDDING_MODEL.value),
                    "report_id": ast.Constant(value=str(report.id)),
                },
            )

            signals = []
            for row in result.results or []:
                document_id, content, metadata_str, timestamp = row
                metadata = json.loads(metadata_str)
                signals.append(
                    {
                        "signal_id": document_id,
                        "source_product": metadata.get("source_product", ""),
                        "source_type": metadata.get("source_type", ""),
                        "source_id": metadata.get("source_id", ""),
                        "weight": metadata.get("weight", 0.0),
                        "timestamp": timestamp,
                        "content": content[:200] + "..." if len(content) > 200 else content,
                        "match_metadata": metadata.get("match_metadata"),
                    }
                )
            return signals
        except Exception as e:
            return [{"error": f"Failed to fetch signals: {e}"}]

    def _print_reports(self, reports, include_signals):
        for i, report in enumerate(reports):
            if i > 0:
                self.stdout.write("─" * 80)

            status = report["status"]
            style = {
                "ready": self.style.SUCCESS,
                "failed": self.style.ERROR,
                "potential": self.style.WARNING,
                "candidate": self.style.WARNING,
                "in_progress": self.style.WARNING,
                "pending_input": self.style.NOTICE,
            }.get(status, self.style.WARNING)

            title = report["title"] or "(no title)"
            self.stdout.write(f"\nReport {report['id'][:8]}... — {self.style.MIGRATE_HEADING(title)}")
            self.stdout.write(
                f"  Status: {style(status)} | Signals: {report['signal_count']} | Weight: {report['total_weight']}"
            )
            self.stdout.write(f"  Created: {report['created_at']}")

            if report["summary"]:
                wrapped = textwrap.fill(report["summary"], width=76, initial_indent="  ", subsequent_indent="  ")
                self.stdout.write(f"  Summary: {wrapped}")

            if report["error"]:
                self.stdout.write(f"  Error: {self.style.ERROR(report['error'])}")

            if report["artefacts"]:
                self.stdout.write(f"  Artefacts ({len(report['artefacts'])}):")
                for art in report["artefacts"]:
                    content = art["content"]
                    if isinstance(content, dict):
                        choice = content.get("choice", "")
                        explanation = content.get("explanation", "")
                        self.stdout.write(f"    {art['type']}: {choice}")
                        if explanation:
                            wrapped = textwrap.fill(
                                explanation, width=72, initial_indent="      ", subsequent_indent="      "
                            )
                            self.stdout.write(wrapped)
                    else:
                        self.stdout.write(f"    {art['type']}: {content}")

            if include_signals and "signals" in report:
                signals = report["signals"]
                if signals and "error" in signals[0]:
                    self.stdout.write(f"  Signals: {self.style.ERROR(signals[0]['error'])}")
                else:
                    self.stdout.write(f"  Signals ({len(signals)}):")
                    for sig in signals:
                        source = f"{sig['source_product']}/{sig['source_type']}"
                        content_preview = sig["content"].replace("\n", " ")[:120]
                        self.stdout.write(f"    [{source}] (w={sig['weight']}) {content_preview}")

        self.stdout.write(f"\n{len(reports)} report(s) shown.\n")
