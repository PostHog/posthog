from datetime import timedelta
from typing import Any
from uuid import uuid4

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils.timezone import now

import structlog
from asgiref.sync import sync_to_async
from temporalio import activity
from temporalio.exceptions import ApplicationError

from posthog.temporal.session_replay.rasterize_recording.storage_keys import content_location_from_s3_uri

from products.exports.backend.models.exported_asset import ExportedAsset
from products.replay_vision.backend.models.replay_observation import ReplayObservation
from products.replay_vision.backend.models.replay_observation_media import ReplayObservationMedia
from products.replay_vision.backend.temporal.decorators import track_activity
from products.replay_vision.backend.temporal.media_types import (
    ANALYSIS_FOOTER_HEIGHT_PX,
    FALLBACK_THUMBNAIL_FRACTION,
    THUMBNAIL_WIDTH_PX,
    ExtractThumbnailActivityInput,
    FinalizeObservationThumbnailInputs,
    ObservationMediaInputs,
    PrepareObservationThumbnailOutput,
)
from products.replay_vision.backend.temporal.video_clock import VideoClock, video_clock_from_export_context

logger = structlog.get_logger(__name__)

_MEDIA_EXPIRY = timedelta(days=90)
# The first and last seconds of an analysis video show the page before its CSS applies or while it unloads.
_EDGE_MARGIN_S = 3.0


def _media_key_prefix(team_id: int, observation_id: Any) -> str:
    # Not under `OBJECT_STORAGE_EXPORTS_FOLDER`: those rules drop an mp4 at 30 days and glacier the rest.
    return f"replay-vision/media/team-{team_id}/{observation_id}"


def _first_citation_video_s(model_output: dict[str, Any] | None, clock: VideoClock | None) -> float | None:
    """The first moment the model pointed at, mapped from session time back onto the video the thumbnail is cut from."""
    if not model_output:
        return None
    for field in ("summary_segments", "reasoning_segments"):
        for segment in model_output.get(field) or []:
            if isinstance(segment, dict) and segment.get("kind") == "chip":
                session_ms = int(segment.get("timestamp_ms") or 0)
                return clock.session_ms_to_video_s(session_ms) if clock else session_ms / 1000
    return None


def _pick_video_time_s(
    inputs: ObservationMediaInputs, model_output: dict[str, Any] | None, clock: VideoClock | None, duration_s: float
) -> float:
    picked = float(inputs.thumbnail_video_s) if inputs.thumbnail_video_s is not None else None
    if picked is None:
        picked = _first_citation_video_s(model_output, clock)
    if picked is None and inputs.signal_video_times:
        start, end = inputs.signal_video_times[0]
        picked = (start + end) / 2
    if picked is None:
        picked = duration_s * FALLBACK_THUMBNAIL_FRACTION
    if duration_s <= 2 * _EDGE_MARGIN_S:
        return duration_s / 2
    return min(max(picked, _EDGE_MARGIN_S), duration_s - _EDGE_MARGIN_S)


@activity.defn
@track_activity()
async def prepare_observation_thumbnail_activity(inputs: ObservationMediaInputs) -> PrepareObservationThumbnailOutput:
    """Pick the frame to cut and create the `is_system` PNG asset the Node activity uploads into."""
    media_inputs = inputs
    try:
        asset = await ExportedAsset.objects.aget(pk=media_inputs.analysis_asset_id, team_id=media_inputs.team_id)
    except ExportedAsset.DoesNotExist as error:
        raise ApplicationError(
            f"Analysis asset {media_inputs.analysis_asset_id} is gone", non_retryable=True
        ) from error
    if not asset.content_location:
        # The analysis render is long finished by now, so an empty location is a lost object, not a race.
        raise ApplicationError(f"Analysis asset {asset.id} has no rendered object", non_retryable=True)

    context = asset.export_context or {}
    duration_s = float(context.get("video_duration_s") or 0)
    if duration_s <= 0:
        raise ApplicationError(f"Analysis asset {asset.id} has no video duration", non_retryable=True)

    # Read before the asset is created, so a deleted observation leaves no asset behind.
    observation = (
        await ReplayObservation.objects.filter(pk=media_inputs.observation_id, team_id=media_inputs.team_id)
        .values_list("scanner_result", flat=True)
        .afirst()
    )
    if observation is None:
        raise ApplicationError(f"Observation {media_inputs.observation_id} is gone", non_retryable=True)
    scanner_result = observation or {}
    clock = video_clock_from_export_context(context)
    video_time_s = _pick_video_time_s(media_inputs, scanner_result.get("model_output"), clock, duration_s)
    rec_start_ms = clock.video_s_to_session_ms(video_time_s) if clock else None

    export_context = {
        # The recording id serves the recording-delete cascade, the observation id every other expiry.
        "session_recording_id": media_inputs.session_id,
        "observation_id": str(media_inputs.observation_id),
        "media_kind": ReplayObservationMedia.Kind.THUMBNAIL.value,
    }
    # Get-or-create: a retried activity would otherwise leave a second asset and object behind.
    media_asset = (
        await ExportedAsset.objects.filter(
            team_id=media_inputs.team_id,
            export_format=ExportedAsset.ExportFormat.PNG,
            export_context__session_recording_id=media_inputs.session_id,
            export_context__observation_id=str(media_inputs.observation_id),
            export_context__media_kind=ReplayObservationMedia.Kind.THUMBNAIL.value,
            is_system=True,
        )
        .order_by("id")
        .afirst()
    )
    if media_asset is None:
        media_asset = await ExportedAsset.objects.acreate(
            team_id=media_inputs.team_id,
            export_format=ExportedAsset.ExportFormat.PNG,
            export_context=export_context,
            # Explicit because the PNG default is six months.
            expires_after=now() + _MEDIA_EXPIRY,
            is_system=True,
        )

    return PrepareObservationThumbnailOutput(
        media_asset_id=media_asset.id,
        activity_input=ExtractThumbnailActivityInput(
            source_s3_uri=f"s3://{settings.OBJECT_STORAGE_BUCKET}/{asset.content_location}",
            video_time_s=video_time_s,
            footer_crop_px=ANALYSIS_FOOTER_HEIGHT_PX if context.get("show_metadata_footer") else 0,
            width=THUMBNAIL_WIDTH_PX,
            s3_bucket=settings.OBJECT_STORAGE_BUCKET,
            s3_key_prefix=_media_key_prefix(media_inputs.team_id, media_inputs.observation_id),
            id=str(uuid4()),
        ),
        video_start_ms=int(video_time_s * 1000),
        rec_start_ms=rec_start_ms,
    )


def _link_media(inputs: FinalizeObservationThumbnailInputs, content_location: str) -> None:
    """Point the asset at the rendered object and link it, as one write.

    One transaction, media row first: an observation deleted before the row exists would leave the asset
    with nothing pointing at it, and one deleted after cascades the row away, which expires the asset.
    """
    with transaction.atomic():
        media, _ = ReplayObservationMedia.objects.for_team(inputs.team_id, canonical=True).update_or_create(
            observation_id=inputs.observation_id,
            kind=ReplayObservationMedia.Kind.THUMBNAIL,
            position=0,
            defaults={
                "team_id": inputs.team_id,
                "asset_id": inputs.media_asset_id,
                "video_start_ms": inputs.video_start_ms,
                "rec_start_ms": inputs.rec_start_ms,
            },
        )
        ExportedAsset.objects.filter(pk=media.asset_id, team_id=inputs.team_id).update(
            content_location=content_location
        )


@activity.defn
@track_activity()
async def finalize_observation_thumbnail_activity(inputs: FinalizeObservationThumbnailInputs) -> None:
    """Point the asset at the uploaded PNG and link it to the observation."""
    try:
        content_location = content_location_from_s3_uri(inputs.result.s3_uri)
    except ValueError as error:
        raise ApplicationError(str(error), non_retryable=True) from error

    try:
        # `for_team` resolves the canonical team with a synchronous query of its own.
        await sync_to_async(_link_media)(inputs, content_location)
    except (IntegrityError, ReplayObservation.DoesNotExist):
        # The observation went away between the render and this write, so nothing will point at the object.
        # The sweep deletes the stored object only for a row that carries a location.
        await ExportedAsset.objects.filter(pk=inputs.media_asset_id, team_id=inputs.team_id).aupdate(
            content_location=content_location, expires_after=now()
        )
        return

    logger.info(
        "replay_vision.thumbnail_ready",
        observation_id=str(inputs.observation_id),
        asset_id=inputs.media_asset_id,
        file_size_bytes=inputs.result.file_size_bytes,
    )
