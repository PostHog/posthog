"""Portable replay bundle construction, sealing, and strict inspection."""

from __future__ import annotations

import os
import sys
import json
import math
import hashlib
import tempfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import numpy as np
from jsonschema import Draft202012Validator, FormatChecker

from products.signals.backend.grouping_replay.artifacts import FrozenPipeline, load_frozen_pipeline, sha256_file
from products.signals.backend.grouping_replay.engine import Signal

BUNDLE_SCHEMA_VERSION = "posthog-signals-grouping-replay/v1"


def _timestamp_iso(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, tz=UTC).isoformat().replace("+00:00", "Z")


def _report_title(content: str) -> str:
    line = " ".join(content.split()).strip()
    return line[:137] + "..." if len(line) > 140 else line


def _portable_signature(signature: dict[str, object]) -> dict[str, object]:
    return {
        name: value.astype(float).tolist() if isinstance(value, np.ndarray) else value
        for name, value in signature.items()
    }


def canonical_bundle_sha256(bundle: dict[str, object]) -> str:
    payload = {key: value for key, value in bundle.items() if key != "integrity"}
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def build_bundle(
    *,
    signals: list[Signal],
    replay: dict[str, object],
    mode: str,
    source_name: str,
    source_sha256: str,
    pipeline: FrozenPipeline,
    enrichment: dict[str, object],
    signature_concurrency: int,
    embedding_concurrency: int,
    oracle_calls: int,
    oracle_cache_hits: int,
) -> dict[str, object]:
    assignment = cast(dict[str, str], replay["assignment"])
    decisions = cast(list[dict[str, object]], replay["decisions"])
    events = cast(dict[str, list[dict[str, object]]], replay["events"])
    members_by_engine_report: dict[str, list[Signal]] = defaultdict(list)
    for signal in signals:
        members_by_engine_report[str(assignment[signal.id])].append(signal)
    ordered_reports = sorted(members_by_engine_report.items(), key=lambda item: (item[1][0].ts, item[0]))
    portable_ids = {
        engine_report_id: f"lab3-report-{index:06d}"
        for index, (engine_report_id, _members) in enumerate(ordered_reports, start=1)
    }

    reports: list[dict[str, object]] = []
    for engine_report_id, members in ordered_reports:
        source_products = Counter(member.product or "unknown" for member in members)
        source_summary = ", ".join(f"{count}x {name}" for name, count in source_products.most_common())
        reports.append(
            {
                "report_id": portable_ids[engine_report_id],
                "engine_report_id": engine_report_id,
                "title": _report_title(members[0].content),
                "summary": (
                    f"Offline Lab 3 Python grouping with {len(members)} signals ({source_summary}). "
                    "This title and summary are deterministic review placeholders; report research did not run."
                ),
                "signal_ids": [member.id for member in members],
                "signal_count": len(members),
                "total_weight": sum(member.weight for member in members),
                "first_seen": _timestamp_iso(members[0].ts),
                "last_seen": _timestamp_iso(members[-1].ts),
                "source_products": dict(source_products),
            }
        )

    bundled_signals: list[dict[str, object]] = [
        {
            "document_id": signal.id,
            "timestamp": _timestamp_iso(signal.ts),
            "content": signal.content,
            "source_product": signal.product,
            "source_type": signal.source_type,
            "source_id": signal.source_id,
            "weight": signal.weight,
            # Preserve the provider vector in the portable bundle. The engine keeps a separate
            # normalized copy for cosine operations, but imported rows should match the source data.
            "embedding": signal.source_embedding.astype(float).tolist(),
            "concern_signature": _portable_signature(signal.signature),
            "metadata": signal.metadata,
            "report_id": portable_ids[str(assignment[signal.id])],
        }
        for signal in signals
    ]

    pipeline_config = pipeline.configuration
    preflight = cast(dict[str, object], pipeline_config["preflight"])
    engine_config = cast(dict[str, object], pipeline_config["engine_config"])
    modes = cast(dict[str, dict[str, object]], pipeline_config["modes"])
    preflight_configuration = {
        **preflight,
        "signature_concurrency": signature_concurrency,
        "embedding_concurrency": embedding_concurrency,
    }
    member_repair_events = events.get("report_shuffling", [])
    split_events = events.get("split", [])
    applied_statuses = {"whole_merge", "into_left", "into_right", "subset_extract"}
    runtime = {
        "signals": len(signals),
        "reports": len(reports),
        "split_events": len(split_events),
        "member_repair_attempts": len(member_repair_events),
        "member_repair_applied": sum(event.get("status") in applied_statuses for event in member_repair_events),
        "member_repair_llm_calls": oracle_calls,
        "member_repair_llm_cache_hits": oracle_cache_hits,
    }
    bundle: dict[str, object] = {
        "schema_version": BUNDLE_SCHEMA_VERSION,
        "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "mode": mode,
        "pipeline": {
            "name": pipeline_config["name"],
            "fingerprint": pipeline.pipeline_fingerprint,
            "implementation": "python-only-onnxruntime",
            "artifact_hashes": pipeline.artifact_hashes,
            "engine_source_sha256": pipeline.runtime_source_sha256,
            "enrichment_source_sha256": pipeline.runtime_source_sha256,
            "engine_binary_sha256": sha256_file(Path(sys.executable).resolve()),
            "runner_sha256": pipeline.runtime_source_sha256,
            "configuration": {**engine_config, **cast(dict[str, object], modes[mode]["engine_overrides"])},
            "preflight_configuration": preflight_configuration,
            "mode_configuration": modes[mode],
        },
        "input": {
            "source_name": source_name,
            "sha256": source_sha256,
            "signal_count": len(signals),
            "concern_signature_count": len(signals),
            "concern_signature_coverage": 1.0,
            "concern_signature_embedding_count": len(signals),
            "concern_signature_embedding_coverage": 1.0,
        },
        "runtime": runtime,
        "enrichment": enrichment,
        "warnings": [],
        "reports": reports,
        "signals": bundled_signals,
        "decisions": decisions,
        "events": {"member_repair": member_repair_events, "split": split_events, "merge": []},
    }
    bundle["integrity"] = {"algorithm": "sha256", "canonical_payload_sha256": canonical_bundle_sha256(bundle)}
    return bundle


def write_bundle(path: Path, bundle: dict[str, object]) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            os.fchmod(handle.fileno(), 0o600)
            handle.write(json.dumps(bundle, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
        os.chmod(path, 0o600)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


@dataclass(frozen=True)
class BundleInspection:
    bundle: dict[str, object]
    mode: str
    signal_count: int
    report_count: int
    pipeline_fingerprint: str
    canonical_payload_sha256: str


def _require_dict(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"bundle {field} must be an object")
    return cast(dict[str, object], value)


def _require_list(value: object, field: str) -> list[object]:
    if not isinstance(value, list):
        raise ValueError(f"bundle {field} must be an array")
    return cast(list[object], value)


def _validate_pipeline_record(pipeline: dict[str, object], frozen: FrozenPipeline, mode: str) -> str:
    configuration = frozen.configuration
    modes = _require_dict(configuration.get("modes"), "frozen modes")
    mode_configuration = _require_dict(modes.get(mode), f"frozen modes.{mode}")
    engine_configuration = _require_dict(configuration.get("engine_config"), "frozen engine_config")
    engine_overrides = _require_dict(
        mode_configuration.get("engine_overrides"), f"frozen modes.{mode}.engine_overrides"
    )
    expected_engine_configuration = {**engine_configuration, **engine_overrides}
    expected_preflight = _require_dict(configuration.get("preflight"), "frozen preflight")

    if pipeline.get("name") != configuration.get("name"):
        raise ValueError("bundle pipeline name does not match the frozen pipeline")
    if pipeline.get("implementation") != "python-only-onnxruntime":
        raise ValueError("bundle pipeline implementation is not the frozen Python runtime")
    fingerprint = pipeline.get("fingerprint")
    if not isinstance(fingerprint, str) or fingerprint != frozen.pipeline_fingerprint:
        raise ValueError("bundle pipeline fingerprint does not match the current frozen runtime")
    if _require_dict(pipeline.get("artifact_hashes"), "pipeline.artifact_hashes") != frozen.artifact_hashes:
        raise ValueError("bundle artifact provenance does not match the frozen pipeline")
    for field in ("engine_source_sha256", "enrichment_source_sha256", "runner_sha256"):
        if pipeline.get(field) != frozen.runtime_source_sha256:
            raise ValueError(f"bundle {field} does not match the current frozen runtime")
    if _require_dict(pipeline.get("configuration"), "pipeline.configuration") != expected_engine_configuration:
        raise ValueError("bundle engine configuration does not match the frozen operating point")
    if _require_dict(pipeline.get("mode_configuration"), "pipeline.mode_configuration") != mode_configuration:
        raise ValueError("bundle mode configuration does not match the frozen operating point")

    preflight = _require_dict(pipeline.get("preflight_configuration"), "pipeline.preflight_configuration")
    if set(preflight) != set(expected_preflight):
        raise ValueError("bundle preflight configuration fields do not match the frozen pipeline")
    for field, expected_value in expected_preflight.items():
        if field not in {"signature_concurrency", "embedding_concurrency"} and preflight.get(field) != expected_value:
            raise ValueError(f"bundle preflight configuration changed {field}")
    signature_concurrency = preflight.get("signature_concurrency")
    embedding_concurrency = preflight.get("embedding_concurrency")
    if isinstance(signature_concurrency, bool) or not isinstance(signature_concurrency, int):
        raise ValueError("bundle signature concurrency must be an integer")
    if isinstance(embedding_concurrency, bool) or not isinstance(embedding_concurrency, int):
        raise ValueError("bundle embedding concurrency must be an integer")
    if not 1 <= signature_concurrency <= 128 or not 1 <= embedding_concurrency <= 8:
        raise ValueError("bundle provider concurrency exceeds the frozen runtime limits")
    return fingerprint


def _validate_runtime_record(bundle: dict[str, object], *, signal_count: int, report_count: int, mode: str) -> None:
    runtime = _require_dict(bundle.get("runtime"), "runtime")
    events = _require_dict(bundle.get("events"), "events")
    member_repair_events = _require_list(events.get("member_repair"), "events.member_repair")
    split_events = _require_list(events.get("split"), "events.split")
    _require_list(events.get("merge"), "events.merge")
    applied_statuses = {"whole_merge", "into_left", "into_right", "subset_extract"}
    expected = {
        "signals": signal_count,
        "reports": report_count,
        "split_events": len(split_events),
        "member_repair_attempts": len(member_repair_events),
        "member_repair_applied": sum(
            isinstance(event, dict) and event.get("status") in applied_statuses for event in member_repair_events
        ),
    }
    for field, expected_value in expected.items():
        if runtime.get(field) != expected_value:
            raise ValueError(f"bundle runtime {field} is inconsistent")
    calls = runtime.get("member_repair_llm_calls")
    cache_hits = runtime.get("member_repair_llm_cache_hits")
    if (
        isinstance(calls, bool)
        or not isinstance(calls, int)
        or calls < 0
        or isinstance(cache_hits, bool)
        or not isinstance(cache_hits, int)
        or cache_hits < 0
    ):
        raise ValueError("bundle runtime oracle counters are invalid")
    if mode == "oracle-off" and (calls != 0 or cache_hits != 0):
        raise ValueError("oracle-off bundle records oracle activity")


def inspect_bundle(path: Path) -> BundleInspection:
    value = json.loads(path.read_text(encoding="utf-8"))
    bundle = _require_dict(value, "root")
    frozen = load_frozen_pipeline()
    schema = json.loads((frozen.root / "bundle.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(bundle)
    if bundle.get("schema_version") != BUNDLE_SCHEMA_VERSION:
        raise ValueError("unsupported replay bundle schema")
    mode = str(bundle.get("mode"))
    if mode not in {"oracle-off", "oracle-on"}:
        raise ValueError("bundle mode must be oracle-off or oracle-on")
    integrity = _require_dict(bundle.get("integrity"), "integrity")
    if integrity.get("algorithm") != "sha256":
        raise ValueError("bundle integrity algorithm must be sha256")
    observed_integrity = canonical_bundle_sha256(bundle)
    if integrity.get("canonical_payload_sha256") != observed_integrity:
        raise ValueError("bundle canonical integrity hash mismatch")

    pipeline = _require_dict(bundle.get("pipeline"), "pipeline")
    fingerprint = _validate_pipeline_record(pipeline, frozen, mode)

    raw_signals = _require_list(bundle.get("signals"), "signals")
    raw_reports = _require_list(bundle.get("reports"), "reports")
    if not raw_signals or not raw_reports:
        raise ValueError("bundle must contain signals and reports")
    signal_ids: set[str] = set()
    members_by_report: dict[str, list[str]] = defaultdict(list)
    weights_by_report: dict[str, float] = defaultdict(float)
    for raw_signal in raw_signals:
        signal = _require_dict(raw_signal, "signals[]")
        document_id = signal.get("document_id")
        report_id = signal.get("report_id")
        if not isinstance(document_id, str) or not document_id or document_id in signal_ids:
            raise ValueError(f"invalid or duplicate signal document_id: {document_id}")
        if not isinstance(report_id, str) or not report_id:
            raise ValueError(f"signal {document_id} has no report reference")
        embedding = signal.get("embedding")
        if (
            not isinstance(embedding, list)
            or len(embedding) != 1536
            or any(
                isinstance(item, bool) or not isinstance(item, int | float) or not math.isfinite(item)
                for item in embedding
            )
        ):
            raise ValueError(f"signal {document_id} must contain 1,536 finite embedding values")
        signal_ids.add(document_id)
        members_by_report[report_id].append(document_id)
        weight = signal.get("weight")
        if isinstance(weight, bool) or not isinstance(weight, int | float) or not math.isfinite(weight) or weight < 0:
            raise ValueError(f"signal {document_id} has invalid weight")
        weights_by_report[report_id] += float(weight)

    report_ids: set[str] = set()
    listed_members: set[str] = set()
    for raw_report in raw_reports:
        report = _require_dict(raw_report, "reports[]")
        report_id = report.get("report_id")
        if not isinstance(report_id, str) or not report_id or report_id in report_ids:
            raise ValueError(f"invalid or duplicate report_id: {report_id}")
        members = report.get("signal_ids")
        if not isinstance(members, list) or not members or not all(isinstance(item, str) for item in members):
            raise ValueError(f"report {report_id} has invalid signal_ids")
        if len(set(members)) != len(members):
            raise ValueError(f"report {report_id} repeats signal membership")
        if members != members_by_report.get(report_id):
            raise ValueError(f"report {report_id} membership differs from signal references or order")
        if report.get("signal_count") != len(members):
            raise ValueError(f"report {report_id} signal_count is inconsistent")
        total_weight = report.get("total_weight")
        if (
            isinstance(total_weight, bool)
            or not isinstance(total_weight, int | float)
            or not math.isfinite(total_weight)
            or total_weight < 0
            or not math.isclose(float(total_weight), weights_by_report[report_id], rel_tol=1e-9, abs_tol=1e-9)
        ):
            raise ValueError(f"report {report_id} total_weight is inconsistent")
        if listed_members & set(members):
            raise ValueError(f"report {report_id} overlaps another report")
        listed_members.update(members)
        report_ids.add(report_id)
    if listed_members != signal_ids or set(members_by_report) != report_ids:
        raise ValueError("bundle report membership does not cover every signal exactly once")
    input_summary = _require_dict(bundle.get("input"), "input")
    if input_summary.get("signal_count") != len(raw_signals):
        raise ValueError("bundle input signal_count is inconsistent")
    for count_field in ("concern_signature_count", "concern_signature_embedding_count"):
        if input_summary.get(count_field) != len(raw_signals):
            raise ValueError(f"bundle input {count_field} is inconsistent")
    for coverage_field in ("concern_signature_coverage", "concern_signature_embedding_coverage"):
        if input_summary.get(coverage_field) != 1.0:
            raise ValueError(f"bundle input {coverage_field} must be complete")
    preflight = _require_dict(pipeline.get("preflight_configuration"), "pipeline.preflight_configuration")
    enrichment = _require_dict(bundle.get("enrichment"), "enrichment")
    for enrichment_field, preflight_field in (
        ("signature_model", "signature_model"),
        ("signature_prompt_version", "signature_prompt_version"),
        ("embedding_model", "embedding_model"),
    ):
        if enrichment.get(enrichment_field) != preflight.get(preflight_field):
            raise ValueError(f"bundle enrichment {enrichment_field} does not match the frozen preflight")
    _validate_runtime_record(bundle, signal_count=len(raw_signals), report_count=len(raw_reports), mode=mode)

    return BundleInspection(
        bundle=bundle,
        mode=mode,
        signal_count=len(raw_signals),
        report_count=len(raw_reports),
        pipeline_fingerprint=fingerprint,
        canonical_payload_sha256=observed_integrity,
    )
