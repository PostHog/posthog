"""Detector artifact blobs in object storage: one blob per insight and scoring profile.

A blob holds one `DetectorArtifact` per series key, as JSON. PyOD models are joblib bytes inside it,
so a blob is read only from a key this code wrote, and only after its bytes match the SHA-256 that
the state row stores. A key is never written twice, so a loaded blob is cached in the process by key.
"""

import json
import uuid
import base64
import hashlib
import threading
from collections import OrderedDict
from typing import Any

from posthog.dataclasses import frozen
from posthog.storage import object_storage
from posthog.tasks.alerts.detectors.base import ARTIFACT_SCHEMA_VERSION, DetectorArtifact

KEY_PREFIX = "anomaly_models"
# A blob holds the artifacts of at most `MAX_LIMITS.max_series` series, so the cache stays small.
_MAX_CACHED_BLOBS = 256


class ArtifactUnavailableError(Exception):
    """The blob is missing, its bytes do not match the stored hash, or a new release cannot read it. The next visit trains."""


@frozen
class StoredArtifacts:
    key: str
    sha256: str
    # The uuid of the blob, on every `$anomaly_score` event that its artifacts scored.
    model_id: str


def artifact_key(team_id: int, insight_id: int, profile: str, model_id: str) -> str:
    return f"{KEY_PREFIX}/{team_id}/{insight_id}/{profile}/{model_id}"


def model_id_of(key: str) -> str:
    return key.rsplit("/", 1)[-1]


def _artifact_json(artifact: DetectorArtifact) -> dict[str, Any]:
    return {
        "detector_type": artifact.detector_type,
        "schema_version": artifact.schema_version,
        "config": artifact.config,
        "params": artifact.params,
        "model_bytes": None if artifact.model_bytes is None else base64.b64encode(artifact.model_bytes).decode(),
        "children": [_artifact_json(child) for child in artifact.children],
    }


def _artifact_from_json(stored: dict[str, Any]) -> DetectorArtifact:
    model_bytes = stored.get("model_bytes")
    return DetectorArtifact(
        detector_type=stored["detector_type"],
        schema_version=stored["schema_version"],
        config=stored["config"],
        params=stored["params"],
        model_bytes=None if model_bytes is None else base64.b64decode(model_bytes),
        children=tuple(_artifact_from_json(child) for child in stored.get("children") or []),
    )


def serialize(artifacts: dict[str, DetectorArtifact]) -> bytes:
    return json.dumps(
        {"series": {key: _artifact_json(artifact) for key, artifact in artifacts.items()}}, sort_keys=True
    ).encode()


def deserialize(blob: bytes) -> dict[str, DetectorArtifact]:
    return {key: _artifact_from_json(stored) for key, stored in json.loads(blob)["series"].items()}


_cache: OrderedDict[str, tuple[str, dict[str, DetectorArtifact]]] = OrderedDict()
_cache_lock = threading.Lock()


def write_artifacts(
    team_id: int, insight_id: int, profile: str, artifacts: dict[str, DetectorArtifact]
) -> StoredArtifacts:
    model_id = str(uuid.uuid4())
    key = artifact_key(team_id, insight_id, profile, model_id)
    blob = serialize(artifacts)
    object_storage.write(key, blob)
    return StoredArtifacts(key=key, sha256=hashlib.sha256(blob).hexdigest(), model_id=model_id)


def load_artifacts(key: str, sha256: str) -> dict[str, DetectorArtifact]:
    with _cache_lock:
        cached = _cache.get(key)
        if cached is not None:
            _cache.move_to_end(key)
    if cached is not None and cached[0] == sha256:
        return cached[1]
    blob = object_storage.read_bytes(key, missing_ok=True) if key else None
    if blob is None:
        raise ArtifactUnavailableError(f"No artifact blob at {key!r}")
    if hashlib.sha256(blob).hexdigest() != sha256:
        raise ArtifactUnavailableError(f"The artifact blob at {key!r} does not match its hash")
    artifacts = deserialize(blob)
    if not all(_readable(artifact) for artifact in artifacts.values()):
        raise ArtifactUnavailableError(f"The artifact blob at {key!r} has an older schema version")
    with _cache_lock:
        _cache[key] = (sha256, artifacts)
        while len(_cache) > _MAX_CACHED_BLOBS:
            _cache.popitem(last=False)
    return artifacts


def _readable(artifact: DetectorArtifact) -> bool:
    return artifact.schema_version == ARTIFACT_SCHEMA_VERSION and all(_readable(child) for child in artifact.children)


def delete_artifacts(key: str) -> None:
    with _cache_lock:
        _cache.pop(key, None)
    object_storage.delete(key)


def clear_artifact_cache() -> None:
    with _cache_lock:
        _cache.clear()
