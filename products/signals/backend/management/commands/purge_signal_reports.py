import uuid
from collections import Counter
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import router, transaction
from django.db.models.deletion import Collector

import structlog
from asgiref.sync import async_to_sync

from posthog.models import Team

from products.signals.backend.management.commands.delete_all_signal_reports_for_team import (
    ACTION_DELETE,
    DEFAULT_BATCH_SIZE,
    _run_workflows_batched,
)
from products.signals.backend.models import SignalReport, SignalReportRefund
from products.signals.backend.report_embeddings import emit_report_tombstone
from products.signals.backend.spend import SignalMetadataChange, submit_signal_metadata_updates
from products.signals.backend.temporal.signal_queries import fetch_report_signal_ids

logger = structlog.get_logger(__name__)

# The ClickHouse read is capped; a report past it is refused rather than half cleared.
MAX_SIGNALS_PER_REPORT = 5000


class Command(BaseCommand):
    help = (
        "Permanently delete chosen signal reports for one team: clear their signals' text in ClickHouse, "
        "then hard delete the report rows in Postgres. Preview only unless --execute is passed."
    )

    def add_arguments(self, parser):
        parser.add_argument("--team-id", type=int, required=True, help="Team that owns every report.")
        parser.add_argument("--report-ids", nargs="+", default=[], help="Report IDs to purge.")
        parser.add_argument("--report-ids-file", type=Path, help="File with one report ID per line.")
        parser.add_argument(
            "--soft-delete",
            action="store_true",
            help="With --execute, run the signal-report-deletion workflow for reports that are not deleted yet. "
            "Without it, every report must already have status 'deleted'.",
        )
        parser.add_argument("--execute", action="store_true", help="Write. Without it the command only previews.")

    def handle(self, *args, **options):
        team_id: int = options["team_id"]
        execute: bool = options["execute"]
        report_ids = _parse_report_ids(options["report_ids"], options["report_ids_file"])
        if not report_ids:
            raise CommandError("Pass --report-ids or --report-ids-file.")
        team = Team.objects.filter(id=team_id).first()
        if team is None:
            raise CommandError(f"Team {team_id} does not exist.")

        reports = _load_reports(team_id, report_ids)
        signal_ids = {report_id: _fetch_signal_ids(team, report_id) for report_id in report_ids}
        not_deleted = [rid for rid in report_ids if reports[rid].status != SignalReport.Status.DELETED]

        self._print_preview(report_ids, reports, signal_ids)

        if not execute:
            if not_deleted and not options["soft_delete"]:
                self.stdout.write(
                    self.style.WARNING(
                        f"{len(not_deleted)} report(s) are not deleted yet. --execute will refuse them "
                        "unless you delete them in the inbox first or pass --soft-delete."
                    )
                )
            self.stdout.write(self.style.SUCCESS("Preview only. Nothing was written. Pass --execute to purge."))
            return

        if not_deleted:
            if not options["soft_delete"]:
                raise CommandError(
                    f"Reports not deleted yet: {', '.join(not_deleted)}. "
                    "Delete them in the inbox first, or pass --soft-delete."
                )
            self._soft_delete(team_id, not_deleted)

        self._clear_clickhouse_content(team_id, report_ids, reports, signal_ids)
        deleted_rows = self._hard_delete(team_id, report_ids)

        logger.info(
            "signals.purge_signal_reports.completed",
            team_id=team_id,
            report_ids=report_ids,
            signal_count=sum(len(ids) for ids in signal_ids.values()),
            deleted_rows=deleted_rows,
        )
        self.stdout.write(self.style.SUCCESS(f"Purged {len(report_ids)} report(s) for team {team_id}."))

    def _print_preview(
        self, report_ids: list[str], reports: dict[str, SignalReport], signal_ids: dict[str, list[str]]
    ) -> None:
        for report_id in report_ids:
            report = reports[report_id]
            self.stdout.write(
                f"Report {report_id}: status={report.status}, created_at={report.created_at.isoformat()}, "
                f"signals in ClickHouse={len(signal_ids[report_id])}"
            )
            for label, count in sorted(_cascade_counts([report_id]).items()):
                self.stdout.write(f"  hard delete removes {count} row(s) from {label}")

        all_signal_ids = [signal_id for report_id in report_ids for signal_id in signal_ids[report_id]]
        self.stdout.write("ClickHouse filters for physical removal from document_embeddings (product = 'signals'):")
        self.stdout.write(f"  document_type = 'signal' AND document_id IN ({_quoted(all_signal_ids)})")
        self.stdout.write(f"  document_type = 'report' AND document_id IN ({_quoted(report_ids)})")

    def _soft_delete(self, team_id: int, report_ids: list[str]) -> None:
        self.stdout.write(f"Running the deletion workflow for {len(report_ids)} report(s)...")
        async_to_sync(_run_workflows_batched)(
            team_id, [(report_id, "") for report_id in report_ids], ACTION_DELETE, DEFAULT_BATCH_SIZE
        )
        still_live = list(
            SignalReport.objects.filter(team_id=team_id, id__in=report_ids)
            .exclude(status=SignalReport.Status.DELETED)
            .values_list("id", flat=True)
        )
        if still_live:
            raise CommandError(
                f"Deletion workflow did not delete: {', '.join(str(i) for i in still_live)}. Nothing was purged."
            )

    def _clear_clickhouse_content(
        self,
        team_id: int,
        report_ids: list[str],
        reports: dict[str, SignalReport],
        signal_ids: dict[str, list[str]],
    ) -> None:
        for report_id in report_ids:
            async_to_sync(submit_signal_metadata_updates)(
                team_id=team_id,
                signal_ids=signal_ids[report_id],
                change=SignalMetadataChange(deleted=True, clear_content=True, expected_report_id=report_id),
            )
            emit_report_tombstone(team_id=team_id, report_id=report_id, created_at=reports[report_id].created_at)
            self.stdout.write(f"Queued text removal for report {report_id} and {len(signal_ids[report_id])} signal(s).")

    def _hard_delete(self, team_id: int, report_ids: list[str]) -> dict[str, int]:
        other_report_ids = set(
            SignalReport.objects.filter(team_id=team_id).exclude(id__in=report_ids).values_list("id", flat=True)
        )
        with transaction.atomic():
            _, deleted_rows = SignalReport.objects.filter(
                team_id=team_id, id__in=report_ids, status=SignalReport.Status.DELETED
            ).delete()
            deleted_reports = deleted_rows.get(SignalReport._meta.label, 0)
            if deleted_reports != len(report_ids):
                raise CommandError(
                    f"Deleted {deleted_reports} report(s), expected {len(report_ids)}. Rolled back; nothing was purged."
                )

        if SignalReport.objects.filter(id__in=report_ids).exists():
            raise CommandError("Some reports still exist after the hard delete.")
        surviving = set(SignalReport.objects.filter(id__in=other_report_ids).values_list("id", flat=True))
        if surviving != other_report_ids:
            raise CommandError(f"{len(other_report_ids - surviving)} other report(s) of the team disappeared.")

        for label, count in sorted(deleted_rows.items()):
            self.stdout.write(f"  deleted {count} row(s) from {label}")
        return deleted_rows


def _parse_report_ids(cli_ids: list[str], ids_file: Path | None) -> list[str]:
    raw = list(cli_ids)
    if ids_file is not None:
        raw.extend(
            line.strip()
            for line in ids_file.read_text().splitlines()
            if line.strip() and not line.strip().startswith("#")
        )
    report_ids: list[str] = []
    for value in raw:
        try:
            report_id = str(uuid.UUID(value))
        except ValueError:
            raise CommandError(f"Not a report ID: {value!r}")
        if report_id not in report_ids:
            report_ids.append(report_id)
    return report_ids


def _load_reports(team_id: int, report_ids: list[str]) -> dict[str, SignalReport]:
    reports = {str(report.id): report for report in SignalReport.objects.filter(id__in=report_ids)}
    missing = [rid for rid in report_ids if rid not in reports]
    if missing:
        raise CommandError(f"Reports not found: {', '.join(missing)}")
    wrong_team = [rid for rid in report_ids if reports[rid].team_id != team_id]
    if wrong_team:
        raise CommandError(f"Reports do not belong to team {team_id}: {', '.join(wrong_team)}")
    refunded = SignalReportRefund.objects.for_team(team_id, canonical=True).filter(report_id__in=report_ids)
    refunded_ids = sorted(str(rid) for rid in refunded.values_list("report_id", flat=True))
    if refunded_ids:
        raise CommandError(
            f"Reports with a refund record cannot be hard deleted: {', '.join(refunded_ids)}. "
            "The refund is a financial record; resolve it with billing first."
        )
    return reports


def _fetch_signal_ids(team: Team, report_id: str) -> list[str]:
    signal_ids = fetch_report_signal_ids(team=team, report_id=report_id, limit=MAX_SIGNALS_PER_REPORT + 1)
    if len(signal_ids) > MAX_SIGNALS_PER_REPORT:
        raise CommandError(f"Report {report_id} has more than {MAX_SIGNALS_PER_REPORT} signals; purge it by hand.")
    return signal_ids


def _cascade_counts(report_ids: list[str]) -> Counter[str]:
    collector = Collector(using=router.db_for_write(SignalReport))
    collector.collect(list(SignalReport.objects.filter(id__in=report_ids)))
    counts: Counter[str] = Counter()
    for model, instances in collector.data.items():
        counts[model._meta.label] += len(instances)
    for queryset in collector.fast_deletes:
        count = queryset.count()
        if count:
            counts[queryset.model._meta.label] += count
    return counts


def _quoted(values: list[str]) -> str:
    return ", ".join(f"'{value}'" for value in values)
