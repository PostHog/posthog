"""Frozen pipeline discovery and artifact-integrity verification."""

from __future__ import annotations

import json
import hashlib
from dataclasses import dataclass
from pathlib import Path

STATIC_ROOT = Path(__file__).resolve().parent.parent / "static" / "grouping_pipeline"


@dataclass(frozen=True)
class FrozenPipeline:
    root: Path
    artifact_dir: Path
    configuration: dict[str, object]
    artifact_hashes: dict[str, str]
    pipeline_fingerprint: str
    runtime_source_sha256: str


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def runtime_source_sha256() -> str:
    digest = hashlib.sha256()
    root = Path(__file__).resolve().parent
    for path in sorted(root.glob("*.py")):
        digest.update(path.name.encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def load_frozen_pipeline(root: Path = STATIC_ROOT) -> FrozenPipeline:
    pipeline_path = root / "pipeline.json"
    value = json.loads(pipeline_path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{pipeline_path} must contain a JSON object")
    manifest_path = root / str(value.get("artifact_manifest", ""))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected = manifest.get("artifacts") if isinstance(manifest, dict) else None
    if not isinstance(expected, dict) or not expected:
        raise ValueError(f"{manifest_path} has no artifact hashes")
    observed: dict[str, str] = {}
    for raw_name, raw_expected_hash in expected.items():
        name = str(raw_name)
        expected_hash = str(raw_expected_hash)
        path = manifest_path.parent / name
        if not path.is_file():
            raise FileNotFoundError(path)
        observed[name] = sha256_file(path)
        if observed[name] != expected_hash:
            raise ValueError(f"artifact hash mismatch: {path}")

    source_hash = runtime_source_sha256()
    fingerprint_payload = json.dumps(
        {"pipeline": value, "artifacts": observed, "runtime_source_sha256": source_hash},
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return FrozenPipeline(
        root=root,
        artifact_dir=manifest_path.parent,
        configuration=value,
        artifact_hashes=observed,
        pipeline_fingerprint=hashlib.sha256(fingerprint_payload).hexdigest(),
        runtime_source_sha256=source_hash,
    )
