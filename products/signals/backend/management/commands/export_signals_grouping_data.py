from __future__ import annotations

import os
import json
import math
import uuid
import shutil
import hashlib
import tempfile
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import TypedDict, cast

from django.core.management.base import BaseCommand, CommandError, CommandParser

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

from posthog.models import Team

from products.signals.backend.models import SignalReport
from products.signals.backend.utils import EMBEDDING_MODEL

EXPORT_SCHEMA_VERSION = "posthog-signals-grouping-export/v1"
EMBEDDING_DIMENSIONS = 1536
MAX_REPLAY_SIGNALS = 10_000
DEFAULT_MAX_SIGNALS = MAX_REPLAY_SIGNALS
DEFAULT_PAGE_SIZE = 1_000


class ExportWarning(TypedDict):
    code: str
    message: str


class FileIntegrity(TypedDict):
    sha256: str
    bytes: int
    records: int


class Command(BaseCommand):
    help = "Export a bounded, self-contained Signals grouping dataset without running the live pipeline."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("output_directory", type=str, help="New directory to receive the export")
        parser.add_argument("--team-id", type=int, required=True, help="Team whose signals should be exported")
        parser.add_argument(
            "--since",
            required=True,
            help="Inclusive ISO-8601 lower timestamp bound; required to prevent an unbounded ClickHouse scan",
        )
        parser.add_argument("--until", help="Exclusive ISO-8601 upper timestamp bound (default: now)")
        parser.add_argument(
            "--max-signals",
            type=int,
            default=DEFAULT_MAX_SIGNALS,
            help=f"Hard export cap (default: {DEFAULT_MAX_SIGNALS})",
        )
        parser.add_argument(
            "--page-size",
            type=int,
            default=DEFAULT_PAGE_SIZE,
            help=f"ClickHouse keyset page size (default: {DEFAULT_PAGE_SIZE})",
        )

    def handle(self, *args: object, **options: object) -> None:
        team_id = _integer_option(options, "team_id")
        max_signals = _positive_integer_option(options, "max_signals")
        if max_signals > MAX_REPLAY_SIGNALS:
            raise CommandError(
                f"--max-signals cannot exceed the safe replay limit of {MAX_REPLAY_SIGNALS}; "
                "split larger evaluations into bounded time ranges"
            )
        page_size = _positive_integer_option(options, "page_size")
        since = _parse_timestamp(options.get("since"), "--since")
        until = _parse_timestamp(options.get("until"), "--until") if options.get("until") else datetime.now(UTC)
        if since >= until:
            raise CommandError("--since must be earlier than --until")

        output_value = options.get("output_directory")
        if not isinstance(output_value, str) or not output_value:
            raise CommandError("output_directory must be a non-empty path")
        output_directory = Path(output_value).expanduser().resolve()
        if output_directory.exists():
            raise CommandError(f"Output path already exists: {output_directory}")
        if not output_directory.parent.is_dir():
            raise CommandError(f"Output parent directory does not exist: {output_directory.parent}")

        team = Team.objects.filter(id=team_id).first()
        if team is None:
            raise CommandError(f"No team exists with ID {team_id}")

        signals, reached_cap = self._fetch_signals(
            team=team,
            since=since,
            until=until,
            max_signals=max_signals,
            page_size=page_size,
        )
        if not signals:
            raise CommandError("No live signals matched the requested team and timestamp range")

        reports, report_warnings = _report_rows(team_id=team_id, signals=signals)
        warnings = report_warnings
        if reached_cap:
            warnings.append(
                {
                    "code": "max_signals_reached",
                    "message": f"The export was truncated at the configured limit of {max_signals} signals.",
                }
            )

        manifest: dict[str, object] = {
            "schema_version": EXPORT_SCHEMA_VERSION,
            "created_at": datetime.now(UTC).isoformat(),
            "source": {
                "team_id": team_id,
                "embedding_model": EMBEDDING_MODEL.value,
                "since": since.isoformat(),
                "until": until.isoformat(),
            },
            "counts": {"signals": len(signals), "reports": len(reports)},
            "warnings": warnings,
            "files": {},
        }
        _write_export_atomically(
            output_directory=output_directory,
            signals=signals,
            reports=reports,
            manifest=manifest,
        )
        self.stdout.write(
            self.style.SUCCESS(f"Exported {len(signals)} signals and {len(reports)} reports to {output_directory}")
        )
        if warnings:
            self.stdout.write(self.style.WARNING(f"Export completed with {len(warnings)} manifest warning(s)"))

    def _fetch_signals(
        self,
        *,
        team: Team,
        since: datetime,
        until: datetime,
        max_signals: int,
        page_size: int,
    ) -> tuple[list[dict[str, object]], bool]:
        # The deletion predicate belongs outside the argMax subquery. Applying it to source rows can
        # resurrect a signal whose newest version is a tombstone.
        query = """
            SELECT document_id, timestamp, content, embedding, metadata
            FROM (
                SELECT
                    document_id,
                    argMax(timestamp, inserted_at) AS timestamp,
                    argMax(content, inserted_at) AS content,
                    argMax(embedding, inserted_at) AS embedding,
                    argMax(metadata, inserted_at) AS metadata
                FROM document_embeddings
                WHERE model_name = {model_name}
                  AND product = 'signals'
                  AND document_type = 'signal'
                GROUP BY document_id
            )
            WHERE NOT JSONExtractBool(metadata, 'deleted')
              AND timestamp >= {since}
              AND timestamp < {until}
              AND document_id > {after_document_id}
            ORDER BY document_id ASC
            LIMIT {page_limit}
        """
        signals: list[dict[str, object]] = []
        after_document_id = ""
        target_count = max_signals + 1
        while len(signals) < target_count:
            limit = min(page_size, target_count - len(signals))
            result = execute_hogql_query(
                query_type="SignalsGroupingReplayExport",
                query=query,
                team=team,
                placeholders={
                    "model_name": ast.Constant(value=EMBEDDING_MODEL.value),
                    "since": ast.Constant(value=since),
                    "until": ast.Constant(value=until),
                    "after_document_id": ast.Constant(value=after_document_id),
                    "page_limit": ast.Constant(value=limit),
                },
            )
            rows = result.results or []
            if not rows:
                break
            for raw_row in rows:
                signal = _signal_row(raw_row)
                document_id = str(signal["document_id"])
                if document_id <= after_document_id:
                    raise CommandError("ClickHouse returned an unstable signal page")
                after_document_id = document_id
                signals.append(signal)
            if len(rows) < limit:
                break

        reached_cap = len(signals) > max_signals
        return signals[:max_signals], reached_cap


def _signal_row(raw_row: tuple[object, ...]) -> dict[str, object]:
    if len(raw_row) != 5:
        raise CommandError("ClickHouse returned an unexpected signal row shape")
    document_id_value, timestamp_value, content_value, embedding_value, metadata_value = raw_row
    document_id = str(document_id_value or "")
    if not document_id:
        raise CommandError("ClickHouse returned a signal without a document ID")
    if not isinstance(content_value, str) or not content_value.strip():
        raise CommandError(f"Signal {document_id} has empty content and cannot be replayed")
    timestamp = _parse_timestamp(timestamp_value, f"signal {document_id} timestamp")
    metadata = _parse_metadata(metadata_value, document_id=document_id)
    embedding = _parse_embedding(embedding_value, document_id=document_id)
    weight = _finite_number(metadata.get("weight", 0.5), f"signal {document_id} weight", minimum=0.0)
    report_id = str(metadata.get("report_id") or "")
    if report_id:
        try:
            report_id = str(uuid.UUID(report_id))
        except ValueError:
            pass
    return {
        "document_id": document_id,
        "timestamp": timestamp.isoformat(),
        "content": content_value,
        "embedding": embedding,
        "source_product": str(metadata.get("source_product") or ""),
        "source_type": str(metadata.get("source_type") or ""),
        "source_id": str(metadata.get("source_id") or ""),
        "weight": weight,
        "report_id": report_id,
        "concern_signature": metadata.get("concern_signature"),
        "metadata": metadata,
    }


def _parse_metadata(value: object, *, document_id: str) -> dict[str, object]:
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as error:
            raise CommandError(f"Signal {document_id} has invalid metadata JSON") from error
    else:
        parsed = value
    if not isinstance(parsed, dict):
        raise CommandError(f"Signal {document_id} metadata is not an object")
    return {str(key): item for key, item in parsed.items()}


def _parse_embedding(value: object, *, document_id: str) -> list[float]:
    if not isinstance(value, (list, tuple)) or len(value) != EMBEDDING_DIMENSIONS:
        raise CommandError(f"Signal {document_id} does not have a {EMBEDDING_DIMENSIONS}-dimensional embedding")
    embedding = [_finite_number(item, f"signal {document_id} embedding") for item in value]
    return embedding


def _report_rows(
    *, team_id: int, signals: list[dict[str, object]]
) -> tuple[list[dict[str, object]], list[ExportWarning]]:
    member_ids_by_report: defaultdict[str, list[str]] = defaultdict(list)
    total_weight_by_report: defaultdict[str, float] = defaultdict(float)
    unassigned = 0
    for signal in signals:
        report_id = str(signal.get("report_id") or "")
        if not report_id:
            # Training requires an exact partition. Preserve an unassigned production signal as a
            # stable singleton instead of silently excluding it from reports.jsonl.
            report_id = f"unassigned:{signal['document_id']}"
            signal["report_id"] = report_id
            unassigned += 1
        member_ids_by_report[report_id].append(str(signal["document_id"]))
        total_weight_by_report[report_id] += float(cast(int | float, signal["weight"]))

    valid_ids: list[uuid.UUID] = []
    invalid_ids: set[str] = set()
    for report_id in member_ids_by_report:
        try:
            valid_ids.append(uuid.UUID(report_id))
        except ValueError:
            invalid_ids.add(report_id)

    # This is deliberately scoped by both tenant and primary key. Exported ClickHouse metadata is
    # untrusted input and must not be able to select a report owned by another team.
    report_objects = SignalReport.objects.filter(team_id=team_id, id__in=valid_ids).order_by("id")
    found_ids: set[str] = set()
    reports: list[dict[str, object]] = []
    for report in report_objects:
        report_id = str(report.id)
        found_ids.add(report_id)
        reports.append(
            {
                "report_id": report_id,
                "member_ids": sorted(member_ids_by_report[report_id]),
                "title": report.title,
                "summary": report.summary,
                "status": report.status,
                "counts": {
                    "exported_signal_count": len(member_ids_by_report[report_id]),
                    "signal_count": report.signal_count,
                    "total_weight": report.total_weight,
                },
                "timestamps": {
                    "created_at": report.created_at.isoformat(),
                    "updated_at": report.updated_at.isoformat(),
                    "promoted_at": report.promoted_at.isoformat() if report.promoted_at else None,
                    "last_run_at": report.last_run_at.isoformat() if report.last_run_at else None,
                },
                "metadata": {
                    "signals_at_run": report.signals_at_run,
                    "run_count": report.run_count,
                    "error": report.error,
                },
            }
        )

    warnings: list[ExportWarning] = []
    missing_ids = (set(member_ids_by_report) - found_ids) | invalid_ids
    for report_id in sorted(missing_ids):
        members = sorted(member_ids_by_report[report_id])
        reports.append(
            {
                "report_id": report_id,
                "member_ids": members,
                "title": None,
                "summary": None,
                "status": "unassigned" if report_id.startswith("unassigned:") else "missing",
                "counts": {
                    "exported_signal_count": len(members),
                    "signal_count": None,
                    "total_weight": total_weight_by_report[report_id],
                },
                "timestamps": {
                    "created_at": None,
                    "updated_at": None,
                    "promoted_at": None,
                    "last_run_at": None,
                },
                "metadata": {"source_report_missing": True},
            }
        )
    reports.sort(key=lambda report: str(report["report_id"]))
    if missing_ids:
        warnings.append(
            {
                "code": "missing_report_metadata",
                "message": f"Postgres metadata was unavailable for {len(missing_ids)} referenced report(s).",
            }
        )
    if unassigned:
        warnings.append(
            {
                "code": "unassigned_signals",
                "message": f"The export contains {unassigned} signal(s) without a report assignment.",
            }
        )
    return reports, warnings


def _write_export_atomically(
    *,
    output_directory: Path,
    signals: list[dict[str, object]],
    reports: list[dict[str, object]],
    manifest: dict[str, object],
) -> None:
    temporary_directory = Path(tempfile.mkdtemp(prefix=f".{output_directory.name}.tmp-", dir=output_directory.parent))
    os.chmod(temporary_directory, 0o700)
    try:
        signal_integrity = _write_jsonl(temporary_directory / "signals.jsonl", signals)
        report_integrity = _write_jsonl(temporary_directory / "reports.jsonl", reports)
        manifest["files"] = {
            "signals.jsonl": signal_integrity,
            "reports.jsonl": report_integrity,
        }
        _write_json(temporary_directory / "manifest.json", manifest)
        _fsync_directory(temporary_directory)
        os.replace(temporary_directory, output_directory)
        _fsync_directory(output_directory.parent)
    except Exception:
        shutil.rmtree(temporary_directory, ignore_errors=True)
        raise


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> FileIntegrity:
    hasher = hashlib.sha256()
    byte_count = 0
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as handle:
        for row in rows:
            encoded = _canonical_json(row) + b"\n"
            handle.write(encoded)
            hasher.update(encoded)
            byte_count += len(encoded)
        handle.flush()
        os.fsync(handle.fileno())
    return {"sha256": hasher.hexdigest(), "bytes": byte_count, "records": len(rows)}


def _write_json(path: Path, value: dict[str, object]) -> None:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False).encode() + b"\n"
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())


def _canonical_json(value: dict[str, object]) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _parse_timestamp(value: object, label: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError as error:
            raise CommandError(f"{label} must be an ISO-8601 timestamp") from error
    else:
        raise CommandError(f"{label} must be an ISO-8601 timestamp")
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
        suffix = f" at least {minimum}" if minimum is not None else ""
        raise CommandError(f"{label} must be a finite number{suffix}")
    return parsed


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
