from __future__ import annotations

import json
import math
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TypedDict

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import transaction
from django.utils import timezone

from posthog.clickhouse.client import sync_execute
from posthog.models import Team

from products.signals.backend.artefact_schemas import (
    ActionabilityAssessment,
    ActionabilityChoice,
    NoteArtefact,
    Priority,
    PriorityAssessment,
    SafetyJudgment,
    artefact_type_for,
)
from products.signals.backend.grouping_replay import inspect_bundle
from products.signals.backend.models import SignalReport, SignalReportArtefact

BUNDLE_SCHEMA_VERSION = "posthog-signals-grouping-replay/v1"
EMBEDDING_MODEL_NAME = "text-embedding-3-small-1536"
EMBEDDING_DIMENSIONS = 1536
BUFFER_TABLE = "writable_posthog_document_embeddings_buffer"
EMBEDDING_TABLE = "distributed_posthog_document_embeddings_text_embedding_3_small_1536"
CLICKHOUSE_BATCH_SIZE = 500
CLICKHOUSE_COLLISION_BATCH_SIZE = 1_000
POSTGRES_BATCH_SIZE = 2_000
DISPLAY_DEFAULT_SIGNAL_INCREMENT = 1_000_000_000

type ImportArtefact = NoteArtefact | SafetyJudgment | ActionabilityAssessment | PriorityAssessment
type EmbeddingRow = tuple[int, str, str, str, str, str, datetime, datetime, str, str, list[float]]


class ValidatedBundle(TypedDict):
    bundle: dict[str, object]
    reports_by_id: dict[str, dict[str, object]]
    signals_by_report: dict[str, list[dict[str, object]]]
    mode: str
    fingerprint: str
    signature_coverage: float
    warning_count: int


class Command(BaseCommand):
    help = "Import a portable offline grouping replay for local Inbox display without invoking Temporal."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("bundle", type=str, help=f"Portable {BUNDLE_SCHEMA_VERSION} JSON bundle")
        parser.add_argument("--team-id", type=int, required=True, help="Local team that will own imported rows")
        parser.add_argument(
            "--min-signals",
            type=int,
            default=2,
            help="Only import reports with at least this many members (default: 2)",
        )
        parser.add_argument("--limit-reports", type=int, help="Import only the N largest eligible reports")
        parser.add_argument(
            "--document-id-prefix",
            required=True,
            help="Non-empty, unique namespace prefix for imported ClickHouse document IDs",
        )
        parser.add_argument(
            "--max-signal-age-days",
            type=int,
            default=80,
            help="Compress the replay timeline to this maximum age to stay inside ClickHouse TTL (default: 80)",
        )
        parser.add_argument("--dry-run", action="store_true", help="Fully validate and report counts without writes")
        parser.add_argument("--yes", action="store_true", help="Confirm Postgres and ClickHouse writes")

    def handle(self, *args: object, **options: object) -> None:
        if not settings.DEBUG:
            raise CommandError("This command can only run with DEBUG=True")

        bundle_path = _path_option(options, "bundle").expanduser().resolve()
        if not bundle_path.is_file():
            raise CommandError(f"Portable bundle does not exist: {bundle_path}")
        min_signals = _positive_integer_option(options, "min_signals")
        limit_reports = _optional_positive_integer_option(options, "limit_reports")
        max_signal_age_days = _positive_integer_option(options, "max_signal_age_days")
        team_id = _integer_option(options, "team_id")
        prefix_value = _document_id_prefix_option(options)

        team = Team.objects.filter(id=team_id).first()
        if team is None:
            raise CommandError(f"No team exists with ID {team_id}")

        validated = _load_and_validate_bundle(bundle_path)
        ranked = sorted(
            validated["signals_by_report"].items(),
            key=lambda item: (-len(item[1]), item[0]),
        )
        selected = [(report_id, signals) for report_id, signals in ranked if len(signals) >= min_signals]
        if limit_reports is not None:
            selected = selected[:limit_reports]
        if not selected:
            raise CommandError("No reports remain after applying the import filters")

        report_rows, artefact_rows, clickhouse_rows, time_scale = _prepare_import_rows(
            team_id=team.id,
            bundle_path=bundle_path,
            validated=validated,
            selected=selected,
            document_id_prefix=prefix_value,
            max_signal_age_days=max_signal_age_days,
        )
        # Reusing a namespace would create multiple physical versions of the same document IDs.
        # Fail before either database is mutated so imports remain unambiguous and retry-safe.
        _ensure_clickhouse_document_ids_available(
            team_id=team.id,
            document_ids=[row[5] for row in clickhouse_rows],
        )
        signal_count = len(clickhouse_rows)
        self.stdout.write(
            f"Validated {len(validated['reports_by_id'])} bundled reports; selected "
            f"{len(report_rows)} reports and {signal_count} signals"
        )
        if time_scale < 1.0:
            self.stdout.write(f"Timeline scale: {time_scale:.6f} (maximum age {max_signal_age_days} days)")
        if options.get("dry_run") is True:
            self.stdout.write(self.style.SUCCESS("Dry run complete; no Postgres or ClickHouse writes were made"))
            return
        if options.get("yes") is not True:
            raise CommandError("Refusing to write without --yes; use --dry-run to validate safely")

        # Postgres can be atomic, while ClickHouse cannot participate in that transaction. Commit the
        # display rows first, then write the precomputed vectors. A ClickHouse failure is reported as a
        # partial import instead of being hidden behind a misleading Postgres rollback.
        with transaction.atomic():
            SignalReport.objects.bulk_create(report_rows, batch_size=POSTGRES_BATCH_SIZE)
            SignalReportArtefact.objects.bulk_create(artefact_rows, batch_size=POSTGRES_BATCH_SIZE)
        self.stdout.write(f"Created {len(report_rows)} reports and {len(artefact_rows)} display artefacts")

        insert_sql = (
            f"INSERT INTO {BUFFER_TABLE} "
            "(team_id, product, document_type, model_name, rendering, document_id, "
            "timestamp, inserted_at, content, metadata, embedding) VALUES"
        )
        try:
            for start in range(0, len(clickhouse_rows), CLICKHOUSE_BATCH_SIZE):
                sync_execute(
                    insert_sql,
                    clickhouse_rows[start : start + CLICKHOUSE_BATCH_SIZE],
                    team_id=team.id,
                )
        except Exception as error:
            raise CommandError(
                "ClickHouse write failed after Postgres committed; remove the newly imported display reports before retrying"
            ) from error

        self.stdout.write(
            self.style.SUCCESS(
                f"Imported {len(report_rows)} display-only reports and {signal_count} precomputed signal rows"
            )
        )


def _ensure_clickhouse_document_ids_available(*, team_id: int, document_ids: list[str]) -> None:
    queries = (
        f"""
            SELECT document_id
            FROM {EMBEDDING_TABLE}
            WHERE team_id = %(team_id)s
              AND product = 'signals'
              AND document_type = 'signal'
              AND document_id IN %(document_ids)s
            LIMIT 1
        """,
        f"""
            SELECT document_id
            FROM {BUFFER_TABLE}
            WHERE team_id = %(team_id)s
              AND product = 'signals'
              AND document_type = 'signal'
              AND model_name = %(model_name)s
              AND document_id IN %(document_ids)s
            LIMIT 1
        """,
    )
    for start in range(0, len(document_ids), CLICKHOUSE_COLLISION_BATCH_SIZE):
        batch = tuple(document_ids[start : start + CLICKHOUSE_COLLISION_BATCH_SIZE])
        parameters = {"team_id": team_id, "model_name": EMBEDDING_MODEL_NAME, "document_ids": batch}
        for query in queries:
            rows = sync_execute(query, parameters, team_id=team_id, readonly=True)
            if rows:
                raise CommandError(
                    "The import namespace is already present in ClickHouse; choose a new --document-id-prefix"
                )


def _load_and_validate_bundle(bundle_path: Path) -> ValidatedBundle:
    try:
        inspection = inspect_bundle(bundle_path)
    except Exception as error:
        raise CommandError(f"Portable bundle validation failed ({type(error).__name__})") from error
    bundle_value = getattr(inspection, "bundle", None)
    if not isinstance(bundle_value, dict):
        raise CommandError("Portable bundle inspector returned no parsed bundle")
    bundle: dict[str, object] = {str(key): value for key, value in bundle_value.items()}
    if bundle.get("schema_version") != BUNDLE_SCHEMA_VERSION:
        raise CommandError(f"Bundle is not {BUNDLE_SCHEMA_VERSION}")

    reports_value = bundle.get("reports")
    signals_value = bundle.get("signals")
    if not isinstance(reports_value, list) or not isinstance(signals_value, list):
        raise CommandError("Portable bundle must contain report and signal arrays")
    input_value = bundle.get("input")
    if not isinstance(input_value, dict) or input_value.get("signal_count") != len(signals_value):
        raise CommandError("Bundle input signal count does not match its signal array")

    mode_value = bundle.get("mode")
    if mode_value not in {"oracle-off", "oracle-on"}:
        raise CommandError("Bundle mode is invalid")
    mode = str(mode_value)
    pipeline_value = bundle.get("pipeline")
    if not isinstance(pipeline_value, dict):
        raise CommandError("Bundle has no pipeline record")
    fingerprint_value = pipeline_value.get("fingerprint")
    if not isinstance(fingerprint_value, str) or len(fingerprint_value) != 64:
        raise CommandError("Bundle has no valid pipeline fingerprint")

    reports_by_id: dict[str, dict[str, object]] = {}
    for index, raw_report in enumerate(reports_value):
        if not isinstance(raw_report, dict):
            raise CommandError(f"Bundled report {index + 1} must be an object")
        report = {str(key): value for key, value in raw_report.items()}
        report_id_value = report.get("report_id")
        if not isinstance(report_id_value, str) or not report_id_value:
            raise CommandError(f"Bundled report {index + 1} has no report_id")
        if report_id_value in reports_by_id:
            raise CommandError(f"Bundle repeats report_id {report_id_value}")
        reports_by_id[report_id_value] = report

    signals_by_report: dict[str, list[dict[str, object]]] = {report_id: [] for report_id in reports_by_id}
    seen_signal_ids: set[str] = set()
    for index, raw_signal in enumerate(signals_value):
        if not isinstance(raw_signal, dict):
            raise CommandError(f"Bundled signal {index + 1} must be an object")
        signal = {str(key): value for key, value in raw_signal.items()}
        document_id_value = signal.get("document_id")
        if not isinstance(document_id_value, str) or not document_id_value:
            raise CommandError(f"Bundled signal {index + 1} has no document_id")
        if document_id_value in seen_signal_ids:
            raise CommandError(f"Bundle repeats document_id {document_id_value}")
        seen_signal_ids.add(document_id_value)
        report_id_value = signal.get("report_id")
        if not isinstance(report_id_value, str) or report_id_value not in reports_by_id:
            raise CommandError(f"Signal {document_id_value} references an unknown report")
        content_value = signal.get("content")
        if not isinstance(content_value, str) or not content_value.strip():
            raise CommandError(f"Signal {document_id_value} has no content")
        _parse_timestamp(signal.get("timestamp"), f"signal {document_id_value}")
        _finite_number(signal.get("weight"), f"signal {document_id_value} weight", minimum=0.0)
        signal["embedding"] = _embedding(signal.get("embedding"), document_id=document_id_value)
        if not isinstance(signal.get("metadata"), dict):
            raise CommandError(f"Signal {document_id_value} metadata must be an object")
        signals_by_report[report_id_value].append(signal)

    for report_id, report in reports_by_id.items():
        members = signals_by_report[report_id]
        if not members:
            raise CommandError(f"Bundled report {report_id} has no signals")
        expected_ids = report.get("signal_ids")
        observed_ids = [str(signal["document_id"]) for signal in members]
        if not isinstance(expected_ids, list) or [str(value) for value in expected_ids] != observed_ids:
            raise CommandError(f"Bundled report {report_id} membership does not match the signal array")
        if report.get("signal_count") != len(members):
            raise CommandError(f"Bundled report {report_id} signal_count does not match its membership")
        total_weight = _finite_number(report.get("total_weight"), f"report {report_id} total_weight")
        member_weight = sum(
            _finite_number(member.get("weight"), f"signal {member['document_id']} weight", minimum=0.0)
            for member in members
        )
        if not math.isclose(total_weight, member_weight, rel_tol=1e-9, abs_tol=1e-9):
            raise CommandError(f"Bundled report {report_id} total_weight does not match its signals")

    coverage = _finite_number(input_value.get("concern_signature_coverage", 0.0), "signature coverage")
    if coverage < 0.0 or coverage > 1.0:
        raise CommandError("Bundle signature coverage must be between zero and one")
    warnings_value = bundle.get("warnings")
    if not isinstance(warnings_value, list):
        raise CommandError("Bundle warnings must be an array")
    return {
        "bundle": bundle,
        "reports_by_id": reports_by_id,
        "signals_by_report": signals_by_report,
        "mode": mode,
        "fingerprint": fingerprint_value,
        "signature_coverage": coverage,
        "warning_count": len(warnings_value),
    }


def _prepare_import_rows(
    *,
    team_id: int,
    bundle_path: Path,
    validated: ValidatedBundle,
    selected: list[tuple[str, list[dict[str, object]]]],
    document_id_prefix: str,
    max_signal_age_days: int,
) -> tuple[list[SignalReport], list[SignalReportArtefact], list[EmbeddingRow], float]:
    parsed_timestamps = {
        str(signal["document_id"]): _parse_timestamp(signal.get("timestamp"), f"signal {signal['document_id']}")
        for _, signals in selected
        for signal in signals
    }
    original_newest = max(parsed_timestamps.values())
    original_oldest = min(parsed_timestamps.values())
    original_span = original_newest - original_oldest
    maximum_span = timedelta(days=max_signal_age_days)
    time_scale = min(1.0, maximum_span / original_span) if original_span else 1.0
    now = timezone.now()
    imported_newest = now - timedelta(hours=1)

    def imported_timestamp(document_id: str) -> datetime:
        age = original_newest - parsed_timestamps[document_id]
        return (imported_newest - age * time_scale).astimezone(UTC)

    reports: list[SignalReport] = []
    artefacts: list[SignalReportArtefact] = []
    clickhouse_rows: list[EmbeddingRow] = []
    target_document_ids: set[str] = set()
    for bundled_report_id, member_signals in selected:
        bundled_report = validated["reports_by_id"][bundled_report_id]
        title_value = bundled_report.get("title")
        summary_value = bundled_report.get("summary")
        title = str(title_value) if title_value else "Offline grouping replay"
        summary = str(summary_value) if summary_value else "Offline grouping replay; report research did not run."
        total_weight = sum(
            _finite_number(signal.get("weight"), f"signal {signal['document_id']} weight", minimum=0.0)
            for signal in member_signals
        )
        report = SignalReport(
            team_id=team_id,
            status=SignalReport.Status.READY,
            title=title,
            summary=summary,
            signal_count=len(member_signals),
            total_weight=total_weight,
            signals_at_run=len(member_signals) + DISPLAY_DEFAULT_SIGNAL_INCREMENT,
        )
        reports.append(report)
        report_id = str(report.id)

        note = (
            f"Imported from portable offline replay '{bundle_path.name}' in {validated['mode']} mode. "
            f"Pipeline fingerprint: {validated['fingerprint']}. Concern-signature coverage: "
            f"{validated['signature_coverage']:.1%}. Bundle warnings: {validated['warning_count']}. "
            "Safety, actionability, and priority are display defaults only; no research or judging ran."
        )
        if time_scale < 1.0:
            note += f" The original timeline was compressed to {max_signal_age_days} days for local display."
        display_defaults: tuple[ImportArtefact, ...] = (
            NoteArtefact(note=note, author="offline grouping replay import"),
            SafetyJudgment(
                choice=True,
                explanation="Display default only: safety judging was skipped for this offline replay.",
            ),
            ActionabilityAssessment(
                explanation="Display default only: actionability judging was skipped for this offline replay.",
                actionability=ActionabilityChoice.IMMEDIATELY_ACTIONABLE,
                already_addressed=False,
            ),
            PriorityAssessment(
                explanation="Display default only: priority judging was skipped for this offline replay.",
                priority=Priority.P1,
                dollar_value=None,
            ),
        )
        for content in display_defaults:
            artefacts.append(
                SignalReportArtefact(
                    team_id=team_id,
                    report_id=report_id,
                    type=artefact_type_for(content),
                    content=content.model_dump_json(),
                )
            )

        for signal in member_signals:
            original_document_id = str(signal["document_id"])
            target_document_id = f"{document_id_prefix}{original_document_id}"
            if target_document_id in target_document_ids:
                raise CommandError("Document ID prefixing produced a duplicate target ID")
            target_document_ids.add(target_document_id)
            original_metadata = signal.get("metadata")
            if not isinstance(original_metadata, Mapping):
                raise CommandError(f"Signal {original_document_id} metadata must be an object")
            metadata = {
                "report_id": report_id,
                "source_product": str(signal.get("source_product") or ""),
                "source_type": str(signal.get("source_type") or ""),
                "source_id": str(signal.get("source_id") or ""),
                "weight": _finite_number(signal.get("weight"), f"signal {original_document_id} weight", minimum=0.0),
                "extra": {
                    "offline_grouping_replay": True,
                    "bundle": bundle_path.name,
                    "mode": validated["mode"],
                    "pipeline_fingerprint": validated["fingerprint"],
                    "engine_report_id": bundled_report_id,
                    "original_document_id": original_document_id,
                    "original_timestamp": str(signal["timestamp"]),
                    "timeline_scale": time_scale,
                    "concern_signature": signal.get("concern_signature"),
                    "original_metadata": dict(original_metadata),
                },
            }
            try:
                metadata_json = json.dumps(metadata, ensure_ascii=False, sort_keys=True, allow_nan=False)
            except (TypeError, ValueError) as error:
                raise CommandError(f"Signal {original_document_id} metadata is not portable JSON") from error
            embedding_value = signal.get("embedding")
            embedding = _embedding(embedding_value, document_id=original_document_id)
            clickhouse_rows.append(
                (
                    team_id,
                    "signals",
                    "signal",
                    EMBEDDING_MODEL_NAME,
                    "plain",
                    target_document_id,
                    imported_timestamp(original_document_id),
                    now,
                    str(signal["content"]),
                    metadata_json,
                    embedding,
                )
            )
    return reports, artefacts, clickhouse_rows, time_scale


def _embedding(value: object, *, document_id: str) -> list[float]:
    if not isinstance(value, list) or len(value) != EMBEDDING_DIMENSIONS:
        raise CommandError(f"Signal {document_id} has no {EMBEDDING_DIMENSIONS}-dimensional embedding")
    return [_finite_number(item, f"signal {document_id} embedding") for item in value]


def _parse_timestamp(value: object, label: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise CommandError(f"Invalid timestamp for {label}")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as error:
        raise CommandError(f"Invalid timestamp for {label}") from error
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _finite_number(value: object, label: str, *, minimum: float | None = None) -> float:
    if isinstance(value, bool):
        raise CommandError(f"{label} must be a finite number")
    try:
        parsed = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as error:
        raise CommandError(f"{label} must be a finite number") from error
    if not math.isfinite(parsed) or (minimum is not None and parsed < minimum):
        raise CommandError(f"{label} must be a finite number" + (f" at least {minimum}" if minimum is not None else ""))
    return parsed


def _path_option(options: dict[str, object], name: str) -> Path:
    value = options.get(name)
    if not isinstance(value, str) or not value:
        raise CommandError(f"{name} must be a non-empty path")
    return Path(value)


def _document_id_prefix_option(options: dict[str, object]) -> str:
    value = options.get("document_id_prefix")
    if not isinstance(value, str) or not value.strip():
        raise CommandError("--document-id-prefix must be a non-empty namespace")
    namespace = value.strip()
    if len(namespace) > 500:
        raise CommandError("--document-id-prefix must be at most 500 characters")
    return namespace


def _integer_option(options: dict[str, object], name: str) -> int:
    value = options.get(name)
    if isinstance(value, bool) or not isinstance(value, int):
        raise CommandError(f"--{name.replace('_', '-')} must be an integer")
    return value


def _positive_integer_option(options: dict[str, object], name: str) -> int:
    value = _integer_option(options, name)
    if value < 1:
        raise CommandError(f"--{name.replace('_', '-')} must be at least 1")
    return value


def _optional_positive_integer_option(options: dict[str, object], name: str) -> int | None:
    if options.get(name) is None:
        return None
    return _positive_integer_option(options, name)
