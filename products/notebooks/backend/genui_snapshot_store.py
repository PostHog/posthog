import re
import json
from hashlib import sha256
from uuid import UUID

from django.conf import settings

from posthog.storage import object_storage

GENUI_SNAPSHOT_PREFIX = "notebooks/genui"
GENUI_SNAPSHOT_CONTENT_TYPE = "application/json"
MAX_GENUI_SNAPSHOT_BYTES = 1024 * 1024

_HASH = re.compile(r"^[a-f0-9]{64}$")


class GenUISnapshotStoreError(Exception):
    pass


def _team_prefix(team_id: int) -> str:
    return f"{GENUI_SNAPSHOT_PREFIX}/team_{int(team_id)}/"


def build_snapshot_key(*, team_id: int, notebook_id: UUID, node_id: str, snapshot_hash: str) -> str:
    if not _HASH.fullmatch(snapshot_hash):
        raise GenUISnapshotStoreError("Invalid snapshot hash")
    node_digest = sha256(node_id.encode()).hexdigest()[:24]
    return f"{_team_prefix(team_id)}{notebook_id}/{node_digest}/{snapshot_hash}.json"


def write_snapshot(*, key: str, frames: dict[str, object]) -> int:
    serialized = json.dumps(frames, separators=(",", ":"), sort_keys=True)
    size = len(serialized.encode())
    if size > MAX_GENUI_SNAPSHOT_BYTES:
        raise GenUISnapshotStoreError("The dataframe previews are too large for a custom visualization snapshot")
    try:
        object_storage.write(
            key,
            serialized,
            extras={"ContentType": GENUI_SNAPSHOT_CONTENT_TYPE},
            bucket=settings.NOTEBOOKS_FRAME_STORE_S3_BUCKET,
        )
        head = object_storage.head_object(key, bucket=settings.NOTEBOOKS_FRAME_STORE_S3_BUCKET)
    except Exception as error:
        raise GenUISnapshotStoreError("The custom visualization snapshot could not be stored") from error
    if head is None:
        raise GenUISnapshotStoreError("The custom visualization snapshot could not be stored")
    return int(head.get("ContentLength") or size)


def read_snapshot(*, key: str, team_id: int) -> dict[str, object]:
    if not key.startswith(_team_prefix(team_id)):
        raise GenUISnapshotStoreError("Snapshot key is outside the requesting project")
    try:
        serialized = object_storage.read(key, bucket=settings.NOTEBOOKS_FRAME_STORE_S3_BUCKET)
    except Exception as error:
        raise GenUISnapshotStoreError("The custom visualization snapshot is unavailable") from error
    if serialized is None:
        raise GenUISnapshotStoreError("The custom visualization snapshot is unavailable")
    decoded = json.loads(serialized)
    if not isinstance(decoded, dict):
        raise GenUISnapshotStoreError("The custom visualization snapshot is invalid")
    return decoded


def delete_snapshot(*, key: str, team_id: int) -> None:
    if not key.startswith(_team_prefix(team_id)):
        raise GenUISnapshotStoreError("Snapshot key is outside the requesting project")
    object_storage.delete(key, bucket=settings.NOTEBOOKS_FRAME_STORE_S3_BUCKET)
