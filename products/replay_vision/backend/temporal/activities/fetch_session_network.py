"""Fetch a session's captured network requests from the recording blocks and stash them in Redis."""

import asyncio

import structlog
from asgiref.sync import sync_to_async
from temporalio import activity

from posthog.session_recordings.models.session_recording import SessionRecording
from posthog.session_recordings.recordings.recording_api_client import recording_api_client
from posthog.session_recordings.session_recording_v2_service import RecordingBlock, list_blocks_async

from products.replay_vision.backend.temporal.decorators import track_activity
from products.replay_vision.backend.temporal.network_capture import SessionNetworkPayload, parse_network_payload
from products.replay_vision.backend.temporal.state import (
    StateActivitiesEnum,
    get_redis_state_client,
    store_data_in_redis,
)
from products.replay_vision.backend.temporal.types import FetchSessionNetworkInputs

logger = structlog.get_logger(__name__)

# Blocks fetched at once. The rasterizer is reading the same blocks for the video render, so this stays
# modest to keep one scan from adding a burst of load to the recording API.
_BLOCK_CONCURRENCY = 4

# A session with more blocks than this is one of the outliers that has previously exhausted memory in the
# rasterizer. Reading its whole blob set a second time is not worth a best-effort side input, so the scan
# runs without network data rather than risking the read.
_MAX_BLOCKS = 250


@activity.defn
@track_activity()
async def fetch_session_network_activity(inputs: FetchSessionNetworkInputs) -> None:
    """Decode the session's network requests into Redis; idempotent, and never fails the scan.

    Network data is a side input: it sharpens a finding when it is there, and the scan is still valid
    without it. So every failure path stores an empty payload instead of raising, which also stops a
    retry loop from re-reading a large recording.
    """
    redis_client, redis_key = get_redis_state_client(
        label=StateActivitiesEnum.SESSION_NETWORK,
        state_id=str(inputs.observation_id),
    )
    if await redis_client.exists(redis_key):
        return

    try:
        payload = await _load_payload(inputs.team_id, inputs.session_id)
    except Exception:
        logger.warning(
            "replay_vision.fetch_network.failed",
            session_id=inputs.session_id,
            team_id=inputs.team_id,
            exc_info=True,
        )
        payload = SessionNetworkPayload()

    await store_data_in_redis(redis_client, redis_key, payload.model_dump_json())


async def _load_payload(team_id: int, session_id: str) -> SessionNetworkPayload:
    recording = await sync_to_async(_build_recording)(team_id, session_id)
    blocks = await list_blocks_async(recording)
    if not blocks:
        return SessionNetworkPayload()
    if len(blocks) > _MAX_BLOCKS:
        logger.info(
            "replay_vision.fetch_network.skipped_large_recording",
            session_id=session_id,
            team_id=team_id,
            block_count=len(blocks),
        )
        return SessionNetworkPayload()

    lines = await _fetch_lines(blocks, session_id=session_id, team_id=team_id)
    return parse_network_payload(lines)


def _build_recording(team_id: int, session_id: str) -> SessionRecording:
    """The block listing keys off `session_id` and `team_id` only, so an unsaved instance is enough."""
    return SessionRecording(session_id=session_id, team_id=team_id)


async def _fetch_lines(blocks: list[RecordingBlock], *, session_id: str, team_id: int) -> list[str]:
    """Fetch every block decompressed and return their JSONL lines in block order.

    The recording API decrypts transparently, so an encrypted session needs no handling here. A block
    that fails to fetch contributes nothing rather than losing the whole session.
    """
    semaphore = asyncio.Semaphore(_BLOCK_CONCURRENCY)

    async with recording_api_client() as client:

        async def fetch(block: RecordingBlock) -> list[str]:
            async with semaphore:
                try:
                    content = await client.fetch_block(
                        block.key,
                        block.start_byte,
                        block.end_byte,
                        session_id,
                        team_id,
                        decompress=True,
                    )
                except Exception:
                    logger.warning(
                        "replay_vision.fetch_network.block_failed",
                        session_id=session_id,
                        team_id=team_id,
                        exc_info=True,
                    )
                    return []
            return content.decode("utf-8", errors="replace").splitlines()

        results = await asyncio.gather(*(fetch(block) for block in blocks))

    return [line for block_lines in results for line in block_lines]
