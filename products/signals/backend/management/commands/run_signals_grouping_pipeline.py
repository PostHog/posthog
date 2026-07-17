from __future__ import annotations

import os
import json
import math
import hashlib
from datetime import datetime
from pathlib import Path
from typing import cast

from django.core.management.base import BaseCommand, CommandError, CommandParser

from posthog.models import Team

from products.signals.backend.grouping_replay import ReplayMode, ReplayOptions, replay_signals_sync

EXPORT_SCHEMA_VERSION = "posthog-signals-grouping-export/v1"
EMBEDDING_DIMENSIONS = 1536
DEFAULT_HAIKU_CONCURRENCY = 128
DEFAULT_EMBEDDING_CONCURRENCY = 8
MAX_HAIKU_CONCURRENCY = 128
MAX_EMBEDDING_CONCURRENCY = 8
MAX_REPLAY_SIGNALS = 10_000


class Command(BaseCommand):
    help = "Run the frozen offline grouping replay and emit a portable, integrity-protected bundle."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("input", type=str, help="Grouping export directory or signals JSONL file")
        parser.add_argument("output", type=str, help="New portable replay bundle JSON file")
        parser.add_argument(
            "--mode",
            choices=("oracle-off", "oracle-on"),
            default="oracle-off",
            help="Replay mode (default: oracle-off)",
        )
        parser.add_argument(
            "--work-dir",
            type=str,
            help="Append-only enrichment/cache directory (default: a sibling of the output bundle)",
        )
        parser.add_argument(
            "--team-id",
            type=int,
            help="Team attribution for PostHog gateway calls when the append-only cache is incomplete",
        )
        parser.add_argument(
            "--haiku-concurrency",
            type=int,
            default=DEFAULT_HAIKU_CONCURRENCY,
            help=f"Concurrent concern-signature requests (default: {DEFAULT_HAIKU_CONCURRENCY})",
        )
        parser.add_argument(
            "--embedding-concurrency",
            type=int,
            default=DEFAULT_EMBEDDING_CONCURRENCY,
            help=f"Concurrent embedding requests (default: {DEFAULT_EMBEDDING_CONCURRENCY})",
        )
        parser.add_argument(
            "--experimental-oracle-on",
            action="store_true",
            help="Acknowledge that oracle-on is experimental, changes membership, and incurs provider cost",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Validate paths, export integrity, and every signal without running providers or writing output",
        )

    def handle(self, *args: object, **options: object) -> None:
        input_path = _path_option(options, "input").expanduser().resolve()
        output_path = _path_option(options, "output").expanduser().resolve()
        mode_value = options.get("mode")
        if mode_value not in {"oracle-off", "oracle-on"}:
            raise CommandError("--mode must be oracle-off or oracle-on")
        mode = cast(ReplayMode, mode_value)
        experimental_oracle = options.get("experimental_oracle_on") is True
        if mode == "oracle-on" and not experimental_oracle:
            raise CommandError("oracle-on requires the explicit --experimental-oracle-on acknowledgement")

        haiku_concurrency = _positive_integer_option(options, "haiku_concurrency")
        embedding_concurrency = _positive_integer_option(options, "embedding_concurrency")
        if haiku_concurrency > MAX_HAIKU_CONCURRENCY:
            raise CommandError(f"--haiku-concurrency cannot exceed {MAX_HAIKU_CONCURRENCY}")
        if embedding_concurrency > MAX_EMBEDDING_CONCURRENCY:
            raise CommandError(f"--embedding-concurrency cannot exceed {MAX_EMBEDDING_CONCURRENCY}")
        team_id = _optional_integer_option(options, "team_id")
        if team_id is not None and not Team.objects.filter(id=team_id).exists():
            raise CommandError(f"No team exists with ID {team_id}")

        if output_path.exists():
            raise CommandError(f"Output path already exists: {output_path}")
        if not output_path.parent.is_dir():
            raise CommandError(f"Output parent directory does not exist: {output_path.parent}")
        if input_path == output_path:
            raise CommandError("Input and output paths must differ")

        work_value = options.get("work_dir")
        if work_value is None:
            work_directory = output_path.with_name(f".{output_path.stem}.work")
        elif isinstance(work_value, str) and work_value:
            work_directory = Path(work_value).expanduser().resolve()
        else:
            raise CommandError("--work-dir must be a non-empty path")
        if work_directory.exists() and not work_directory.is_dir():
            raise CommandError(f"Work path is not a directory: {work_directory}")
        if not work_directory.exists() and not work_directory.parent.is_dir():
            raise CommandError(f"Work directory parent does not exist: {work_directory.parent}")
        if output_path == work_directory or input_path == work_directory:
            raise CommandError("Input, output, and work paths must be distinct")

        signal_count = _validate_replay_input(input_path)
        if options.get("dry_run") is True:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Validated {signal_count} signals; no providers were called and no files were written"
                )
            )
            return

        # The runtime treats the work directory as an append-only cache. The command never removes or
        # rewrites it, so interrupted and repeated runs retain provider results with their provenance.
        work_directory.mkdir(mode=0o700, parents=False, exist_ok=True)
        os.chmod(work_directory, 0o700)
        replay_options = ReplayOptions(
            mode=mode,
            team_id=team_id,
            run_dir=work_directory,
            signature_concurrency=haiku_concurrency,
            embedding_concurrency=embedding_concurrency,
        )
        runtime_input_path = input_path / "signals.jsonl" if input_path.is_dir() else input_path
        try:
            result = replay_signals_sync(runtime_input_path, output_path, options=replay_options)
        except Exception as error:
            # Provider exceptions can contain source text. Keep the command boundary content-free and
            # preserve any successful provider results in the append-only work directory for retry.
            raise CommandError(
                f"Grouping replay failed ({type(error).__name__}); successful cached work was preserved for retry"
            ) from error

        self.stdout.write(
            self.style.SUCCESS(
                f"Wrote {result.report_count} reports for {result.signal_count} signals to {result.output_path}"
            )
        )
        self.stdout.write(f"Pipeline fingerprint: {result.pipeline_fingerprint}")


def _validate_replay_input(input_path: Path) -> int:
    if input_path.is_dir():
        return _validate_export_directory(input_path)
    if not input_path.is_file():
        raise CommandError(f"Input path does not exist: {input_path}")
    if input_path.suffix.lower() != ".jsonl":
        raise CommandError("Replay input files must be signals JSONL; use the import command for portable bundles")
    return _validate_signals_jsonl(input_path, require_embedding=False)


def _validate_export_directory(directory: Path) -> int:
    manifest_path = directory / "manifest.json"
    signals_path = directory / "signals.jsonl"
    reports_path = directory / "reports.jsonl"
    for required_path in (manifest_path, signals_path, reports_path):
        if not required_path.is_file():
            raise CommandError(f"Export directory is missing {required_path.name}")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise CommandError("Export manifest is unreadable or invalid JSON") from error
    if not isinstance(manifest, dict) or manifest.get("schema_version") != EXPORT_SCHEMA_VERSION:
        raise CommandError(f"Export manifest is not {EXPORT_SCHEMA_VERSION}")
    files = manifest.get("files")
    if not isinstance(files, dict):
        raise CommandError("Export manifest has no file integrity records")
    _verify_export_file(signals_path, files.get("signals.jsonl"))
    _verify_export_file(reports_path, files.get("reports.jsonl"))
    signal_count = _validate_signals_jsonl(signals_path, require_embedding=True)
    counts = manifest.get("counts")
    if not isinstance(counts, dict) or counts.get("signals") != signal_count:
        raise CommandError("Export manifest signal count does not match signals.jsonl")
    return signal_count


def _verify_export_file(path: Path, integrity_value: object) -> None:
    if not isinstance(integrity_value, dict):
        raise CommandError(f"Export manifest has no integrity record for {path.name}")
    expected = integrity_value.get("sha256")
    if not isinstance(expected, str) or len(expected) != 64:
        raise CommandError(f"Export manifest has an invalid hash for {path.name}")
    observed = hashlib.sha256(path.read_bytes()).hexdigest()
    if observed != expected:
        raise CommandError(f"Export integrity check failed for {path.name}")


def _validate_signals_jsonl(path: Path, *, require_embedding: bool) -> int:
    seen_ids: set[str] = set()
    count = 0
    try:
        handle = path.open(encoding="utf-8")
    except OSError as error:
        raise CommandError(f"Could not read {path}") from error
    with handle:
        for line_number, raw_line in enumerate(handle, 1):
            if not raw_line.strip():
                continue
            try:
                signal = json.loads(raw_line)
            except json.JSONDecodeError as error:
                raise CommandError(f"Invalid JSON on signal line {line_number}") from error
            if not isinstance(signal, dict):
                raise CommandError(f"Signal line {line_number} must contain an object")
            document_id = signal.get("document_id")
            if not isinstance(document_id, str) or not document_id:
                raise CommandError(f"Signal line {line_number} has no document_id")
            if document_id in seen_ids:
                raise CommandError(f"Signal line {line_number} repeats a document_id")
            seen_ids.add(document_id)
            content = signal.get("content")
            if not isinstance(content, str) or not content.strip():
                raise CommandError(f"Signal line {line_number} has empty content")
            timestamp = signal.get("timestamp")
            _validate_timestamp(timestamp, line_number=line_number)
            embedding = signal.get("embedding")
            if embedding is None and not require_embedding:
                pass
            elif not isinstance(embedding, list) or len(embedding) != EMBEDDING_DIMENSIONS:
                raise CommandError(f"Signal line {line_number} has an invalid embedding dimension")
            elif not all(_is_finite_number(value) for value in embedding):
                raise CommandError(f"Signal line {line_number} has a non-finite embedding")
            metadata = signal.get("metadata")
            if metadata is not None and not isinstance(metadata, dict):
                raise CommandError(f"Signal line {line_number} metadata must be an object")
            weight = signal.get("weight")
            if weight is not None and not _is_nonnegative_finite_number(weight):
                raise CommandError(f"Signal line {line_number} has a negative or non-finite weight")
            count += 1
            if count > MAX_REPLAY_SIGNALS:
                raise CommandError(
                    f"Replay input exceeds the safe limit of {MAX_REPLAY_SIGNALS} signals; "
                    "split larger evaluations into bounded time ranges"
                )
    if count < 1:
        raise CommandError("Replay input contains no signals")
    return count


def _validate_timestamp(value: object, *, line_number: int) -> None:
    if isinstance(value, bool):
        raise CommandError(f"Signal line {line_number} has an invalid timestamp")
    if isinstance(value, (int, float)):
        if not math.isfinite(float(value)):
            raise CommandError(f"Signal line {line_number} has an invalid timestamp")
        return
    if not isinstance(value, str) or not value.strip():
        raise CommandError(f"Signal line {line_number} has no timestamp")
    try:
        datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as error:
        raise CommandError(f"Signal line {line_number} has an invalid timestamp") from error


def _is_finite_number(value: object) -> bool:
    if isinstance(value, bool):
        return False
    try:
        return math.isfinite(float(value))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False


def _is_nonnegative_finite_number(value: object) -> bool:
    if not _is_finite_number(value):
        return False
    try:
        return float(value) >= 0  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False


def _path_option(options: dict[str, object], name: str) -> Path:
    value = options.get(name)
    if not isinstance(value, str) or not value:
        raise CommandError(f"{name} must be a non-empty path")
    return Path(value)


def _positive_integer_option(options: dict[str, object], name: str) -> int:
    value = options.get(name)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise CommandError(f"--{name.replace('_', '-')} must be at least 1")
    return value


def _optional_integer_option(options: dict[str, object], name: str) -> int | None:
    value = options.get(name)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise CommandError(f"--{name.replace('_', '-')} must be an integer")
    return value
