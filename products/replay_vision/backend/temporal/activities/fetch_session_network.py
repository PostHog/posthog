"""Fetch a session's captured network requests from the recording blocks and stash them in Redis."""

import asyncio

import structlog
from asgiref.sync import sync_to_async
from temporalio import activity

from posthog.session_recordings.models.session_recording import SessionRecording
from posthog.session_recordings.recordings.recording_api_client import recording_api_client
from posthog.session_recordings.session_recording_v2_service import RecordingBlock, list_blocks_async

from products.replay_vision.backend.temporal.decorators import track_activity
from products.replay_vision.backend.temporal.network_capture import NetworkCollector, SessionNetworkPayload
from products.replay_vision.backend.temporal.state import (
    StateActivitiesEnum,
    get_redis_state_client,
    store_data_in_redis,
)
from products.replay_vision.backend.temporal.types import FetchSessionNetworkInputs

logger = structlog.get_logger(__name__)

# The rasterizer is reading the same blocks for the video render, so keep one scan from adding a burst of
# load to the recording API.
_BLOCK_CONCURRENCY = 4

# Gate on the listing's compressed bytes the way the rasterizer does
# (`maxRecordingCompressedBytes` in nodejs/src/session-replay/recording-rasterizer/config.ts), because a
# block count bounds neither the read nor the memory it needs. Set well below the rasterizer's 512 MiB:
# this is a side input, so an outlier is worth skipping rather than straining the worker for.
_MAX_COMPRESSED_BYTES = 64 * 1024 * 1024


@activity.defn
@track_activity()
async def fetch_session_network_activity(inputs: FetchSessionNetworkInputs) -> None:
    """Decode the session's network requests into Redis; idempotent, and never fails the scan.

    Network data is a side input: it sharpens a finding when it is there, and the scan is still valid
    without it. So every failure path stores an empty payload instead of raising, which also stops a
    retry loop from re-reading a large recording.
    """
    try:
        redis_client, redis_key = get_redis_state_client(
            label=StateActivitiesEnum.SESSION_NETWORK,
            state_id=str(inputs.observation_id),
        )
        if await redis_client.exists(redis_key):
            return
        payload = await _load_payload(inputs.team_id, inputs.session_id)
    except Exception:
        logger.warning(
            "replay_vision.fetch_network.failed",
            session_id=inputs.session_id,
            team_id=inputs.team_id,
            exc_info=True,
        )
        return

    try:
        await store_data_in_redis(redis_client, redis_key, payload.model_dump_json())
    except Exception:
        # Raising here would retry, and on the last attempt fail the scan. A missing key reads as
        # "no network data", which the scan already handles.
        logger.warning(
            "replay_vision.fetch_network.store_failed",
            session_id=inputs.session_id,
            team_id=inputs.team_id,
            exc_info=True,
        )


async def _load_payload(team_id: int, session_id: str) -> SessionNetworkPayload:
    recording = await sync_to_async(_build_recording)(team_id, session_id)
    blocks = await list_blocks_async(recording)
    if not blocks:
        return SessionNetworkPayload()

    compressed_bytes = sum(max(0, block.end_byte - block.start_byte) for block in blocks)
    if compressed_bytes > _MAX_COMPRESSED_BYTES:
        logger.info(
            "replay_vision.fetch_network.skipped_large_recording",
            session_id=session_id,
            team_id=team_id,
            block_count=len(blocks),
            compressed_bytes=compressed_bytes,
        )
        # Partial rather than empty: the scan must not read "nothing failed" from a recording never read.
        return SessionNetworkPayload(partial=True)

    return await _collect(blocks, session_id=session_id, team_id=team_id)


def _build_recording(team_id: int, session_id: str) -> SessionRecording:
    """The block listing keys off `session_id` and `team_id` only, so an unsaved instance is enough."""
    return SessionRecording(session_id=session_id, team_id=team_id)


async def _collect(blocks: list[RecordingBlock], *, session_id: str, team_id: int) -> SessionNetworkPayload:
    """Fetch the blocks a batch at a time and decode each batch before fetching the next.

    Peak memory stays at one batch rather than the whole decompressed session, whose size the block
    count does not bound. Fetching stops early once enough requests are kept.

    The recording API decrypts transparently, so an encrypted session needs no handling here. A block
    that fails to fetch contributes nothing rather than losing the whole session.
    """
    collector = NetworkCollector()
    partial = False

    async with recording_api_client() as client:

        async def fetch(block: RecordingBlock) -> list[str] | None:
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
                return None
            return content.decode("utf-8", errors="replace").splitlines()

        for start in range(0, len(blocks), _BLOCK_CONCURRENCY):
            batch = blocks[start : start + _BLOCK_CONCURRENCY]
            for block_lines in await asyncio.gather(*(fetch(block) for block in batch)):
                if block_lines is None:
                    partial = True
                    continue
                collector.feed(block_lines)
            if collector.full:
                break

    return collector.finish(partial=partial)
