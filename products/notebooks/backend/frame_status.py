"""Status of a frame materialization job, kept in the app Redis.

A materialize job runs on a Temporal worker and writes its frame to the object store, so
its result never enters the query cache. This record is what the data-plane status
endpoint polls: running, failed with a message, or done with the object key to presign.
A second key maps a running job's query hash to its id so an identical concurrent
request joins the job instead of starting another scan.
"""

import json
from dataclasses import asdict

from posthog.dataclasses import frozen
from posthog.redis import get_client

# Longer than the kernel's object poll deadline, so a job that finishes late still has a
# record for the poll to find.
STATUS_TTL_SECONDS = 20 * 60


@frozen
class FrameStatus:
    query_id: str
    team_id: int
    complete: bool = False
    error: bool = False
    error_message: str | None = None
    # Where the frame landed. The bucket travels with the key: a status outlives the deploy
    # that changes NOTEBOOKS_FRAME_STORE_S3_BUCKET, and the key alone does not say where the
    # object went.
    object_key: str | None = None
    bucket: str | None = None


def _status_key(team_id: int, query_id: str) -> str:
    return f"notebook_frame:{team_id}:{query_id}:status"


def _running_key(team_id: int, query_hash: str) -> str:
    return f"notebook_frame:{team_id}:running:{query_hash}"


def store_frame_status(status: FrameStatus) -> None:
    get_client().set(_status_key(status.team_id, status.query_id), json.dumps(asdict(status)), ex=STATUS_TTL_SECONDS)


def get_frame_status(team_id: int, query_id: str) -> FrameStatus | None:
    raw = get_client().get(_status_key(team_id, query_id))
    if raw is None:
        return None
    payload = json.loads(raw)
    return FrameStatus(
        query_id=query_id,
        team_id=team_id,
        complete=bool(payload.get("complete")),
        error=bool(payload.get("error")),
        error_message=payload.get("error_message"),
        object_key=payload.get("object_key"),
        bucket=payload.get("bucket"),
    )


def delete_frame_status(team_id: int, query_id: str) -> None:
    get_client().delete(_status_key(team_id, query_id))


def register_running_frame(team_id: int, query_hash: str, query_id: str) -> None:
    get_client().set(_running_key(team_id, query_hash), query_id, ex=STATUS_TTL_SECONDS)


def get_running_frame(team_id: int, query_hash: str) -> str | None:
    query_id = get_client().get(_running_key(team_id, query_hash))
    return query_id.decode("utf-8") if query_id else None


def unregister_running_frame(team_id: int, query_hash: str) -> None:
    get_client().delete(_running_key(team_id, query_hash))
