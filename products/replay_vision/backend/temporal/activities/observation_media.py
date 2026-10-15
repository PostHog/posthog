from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils.timezone import now

import structlog
from asgiref.sync import sync_to_async
from temporalio import activity
from temporalio.exceptions import ApplicationError

from posthog.dataclasses import frozen
from posthog.temporal.session_replay.rasterize_recording.storage_keys import content_location_from_s3_uri

from products.exports.backend.models.exported_asset import ExportedAsset
from products.replay_vision.backend.models.replay_observation import ReplayObservation
from products.replay_vision.backend.models.replay_observation_media import ReplayObservationMedia
from products.replay_vision.backend.temporal.decorators import track_activity
from products.replay_vision.backend.temporal.media_types import (
    FALLBACK_THUMBNAIL_FRACTION,
    LEGACY_ANALYSIS_FOOTER_HEIGHT_PX,
    THUMBNAIL_WIDTH_PX,
    ExtractThumbnailsActivityInput,
    ExtractThumbnailsFrame,
    FinalizeObservationMediaInputs,
    ObservationMediaInputs,
    PreparedFrame,
    PrepareObservationMediaOutput,
)
from products.replay_vision.backend.temporal.video_clock import VideoClock, video_clock_from_export_context

logger = structlog.get_logger(__name__)

_MEDIA_EXPIRY = timedelta(days=90)
# The first and last seconds of an analysis video show the page before its CSS applies or while it unloads.
_EDGE_MARGIN_S = 3.0
_END_MARGIN_S = 1.0


def _footer_crop_px(context: dict[str, Any]) -> int:
    """Rows to crop off the analysis video, which carry the metadata footer rather than the page."""
    if not context.get("show_metadata_footer"):
        return 0
    return int(context.get("footer_height_px") or LEGACY_ANALYSIS_FOOTER_HEIGHT_PX)


def _media_key_prefix(team_id: int, observation_id: Any) -> str:
    # Not under `OBJECT_STORAGE_EXPORTS_FOLDER`: those rules drop an mp4 at 30 days and glacier the rest.
    return f"replay-vision/media/team-{team_id}/{observation_id}"


def _session_ms_to_video_s(clock: VideoClock | None, session_ms: int) -> float:
    return clock.session_ms_to_video_s(session_ms) if clock else session_ms / 1000


def _first_citation_video_s(model_output: dict[str, Any] | None, clock: VideoClock | None) -> float | None:
    """The first moment the model pointed at, mapped from session time back onto the video the thumbnail is cut from."""
    if not model_output:
        return None
    for field in ("summary_segments", "reasoning_segments"):
        for segment in model_output.get(field) or []:
            if isinstance(segment, dict) and segment.get("kind") == "chip":
                session_ms = int(segment.get("timestamp_ms") or 0)
                return _session_ms_to_video_s(clock, session_ms)
    return None


def _clamp_to_video(picked_s: float, duration_s: float) -> float:
    if duration_s <= 2 * _EDGE_MARGIN_S:
        return duration_s / 2
    return min(max(picked_s, _EDGE_MARGIN_S), duration_s - _EDGE_MARGIN_S)


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
    return _clamp_to_video(picked, duration_s)


def _chapter_frame_times_s(
    model_output: dict[str, Any] | None, clock: VideoClock | None, duration_s: float
) -> list[tuple[int, float]]:
    """Each chapter's thumbnail moment as (chapter index, video seconds), mapped back from the session clock."""
    chapters = (model_output or {}).get("chapters") or []
    times: list[tuple[int, float]] = []
    for position, chapter in enumerate(chapters):
        if not isinstance(chapter, dict) or not isinstance(chapter.get("thumbnail_ms"), int):
            continue
        session_ms = chapter["thumbnail_ms"]
        # No start margin, which would move a short first chapter's frame into the next one. The end keeps a second,
        # because a moment in trailing idle maps to the video's last instant and a seek there cuts no frame.
        video_s = _session_ms_to_video_s(clock, session_ms)
        times.append((position, min(max(video_s, 0.0), max(0.0, duration_s - _END_MARGIN_S))))
    return times


@frozen
class _RenderSource:
    """The analysis video a frame is cut from, and the observation that frame illustrates."""

    source_s3_uri: str
    context: dict[str, Any]
    duration_s: float
    clock: VideoClock | None
    model_output: dict[str, Any] | None


async def _load_render_source(inputs: ObservationMediaInputs) -> _RenderSource:
    try:
        asset = await ExportedAsset.objects.aget(pk=inputs.analysis_asset_id, team_id=inputs.team_id)
    except ExportedAsset.DoesNotExist as error:
        raise ApplicationError(f"Analysis asset {inputs.analysis_asset_id} is gone", non_retryable=True) from error
    if not asset.content_location:
        # The analysis render is long finished by now, so an empty location is a lost object, not a race.
        raise ApplicationError(f"Analysis asset {asset.id} has no rendered object", non_retryable=True)

    context = asset.export_context or {}
    duration_s = float(context.get("video_duration_s") or 0)
    if duration_s <= 0:
        raise ApplicationError(f"Analysis asset {asset.id} has no video duration", non_retryable=True)

    # Read before any media asset is created, so a deleted observation leaves no asset behind.
    observation = (
        await ReplayObservation.objects.filter(pk=inputs.observation_id, team_id=inputs.team_id)
        .values_list("scanner_result", flat=True)
        .afirst()
    )
    if observation is None:
        raise ApplicationError(f"Observation {inputs.observation_id} is gone", non_retryable=True)
    scanner_result = observation or {}
    return _RenderSource(
        source_s3_uri=f"s3://{settings.OBJECT_STORAGE_BUCKET}/{asset.content_location}",
        context=context,
        duration_s=duration_s,
        clock=video_clock_from_export_context(context),
        model_output=scanner_result.get("model_output"),
    )


async def _media_asset(
    inputs: ObservationMediaInputs, kind: ReplayObservationMedia.Kind, position: int
) -> ExportedAsset:
    """Get or create the `is_system` PNG asset for one media slot, so a retried activity leaves no second asset."""
    export_context: dict[str, Any] = {
        # The recording id serves the recording-delete cascade, the observation id every other expiry.
        "session_recording_id": inputs.session_id,
        "observation_id": str(inputs.observation_id),
        "media_kind": kind.value,
    }
    lookup: dict[str, Any] = {
        "export_context__session_recording_id": inputs.session_id,
        "export_context__observation_id": str(inputs.observation_id),
        "export_context__media_kind": kind.value,
    }
    # The observation has one thumbnail, and its assets predate the position key, so only other kinds carry one.
    if kind != ReplayObservationMedia.Kind.THUMBNAIL:
        export_context["media_position"] = position
        lookup["export_context__media_position"] = position
    media_asset = (
        await ExportedAsset.objects.filter(
            team_id=inputs.team_id, export_format=ExportedAsset.ExportFormat.PNG, is_system=True, **lookup
        )
        .order_by("id")
        .afirst()
    )
    if media_asset is None:
        media_asset = await ExportedAsset.objects.acreate(
            team_id=inputs.team_id,
            export_format=ExportedAsset.ExportFormat.PNG,
            export_context=export_context,
            # Explicit because the PNG default is six months.
            expires_after=now() + _MEDIA_EXPIRY,
            is_system=True,
        )
    return media_asset


@activity.defn
@track_activity()
async def prepare_observation_media_activity(inputs: ObservationMediaInputs) -> PrepareObservationMediaOutput:
    """Pick every frame to cut, the thumbnail and one per summary chapter, and create the PNG asset each uploads into."""
    source = await _load_render_source(inputs)
    slots = [
        (
            ReplayObservationMedia.Kind.THUMBNAIL,
            0,
            _pick_video_time_s(inputs, source.model_output, source.clock, source.duration_s),
        ),
        *(
            (ReplayObservationMedia.Kind.CHAPTER, position, video_time_s)
            for position, video_time_s in _chapter_frame_times_s(source.model_output, source.clock, source.duration_s)
        ),
    ]
    frames: list[PreparedFrame] = []
    extract_frames: list[ExtractThumbnailsFrame] = []
    for kind, position, video_time_s in slots:
        media_asset = await _media_asset(inputs, kind, position)
        object_id = str(uuid4())
        extract_frames.append(
            ExtractThumbnailsFrame(
                video_time_s=video_time_s, id=object_id, required=kind == ReplayObservationMedia.Kind.THUMBNAIL
            )
        )
        frames.append(
            PreparedFrame(
                kind=kind.value,
                position=position,
                media_asset_id=media_asset.id,
                object_id=object_id,
                video_start_ms=int(video_time_s * 1000),
                rec_start_ms=source.clock.video_s_to_session_ms(video_time_s) if source.clock else None,
            )
        )

    return PrepareObservationMediaOutput(
        frames=frames,
        activity_input=ExtractThumbnailsActivityInput(
            source_s3_uri=source.source_s3_uri,
            frames=extract_frames,
            footer_crop_px=_footer_crop_px(source.context),
            width=THUMBNAIL_WIDTH_PX,
            s3_bucket=settings.OBJECT_STORAGE_BUCKET,
            s3_key_prefix=_media_key_prefix(inputs.team_id, inputs.observation_id),
        ),
    )


@frozen
class _MediaLink:
    kind: ReplayObservationMedia.Kind
    position: int
    asset_id: int
    video_start_ms: int
    rec_start_ms: int | None
    content_location: str


def _link_media(team_id: int, observation_id: UUID, links: list[_MediaLink]) -> None:
    """Point each asset at its rendered object and link it, as one write.

    One transaction, media rows first: an observation deleted before the rows exist would leave the assets
    with nothing pointing at them, and one deleted after cascades the rows away, which expires the assets.
    """
    with transaction.atomic():
        for link in links:
            media, _ = ReplayObservationMedia.objects.for_team(team_id, canonical=True).update_or_create(
                observation_id=observation_id,
                kind=link.kind,
                position=link.position,
                defaults={
                    "team_id": team_id,
                    "asset_id": link.asset_id,
                    "video_start_ms": link.video_start_ms,
                    "rec_start_ms": link.rec_start_ms,
                },
            )
            ExportedAsset.objects.filter(pk=media.asset_id, team_id=team_id).update(
                content_location=link.content_location
            )


async def _link_or_expire(team_id: int, observation_id: UUID, links: list[_MediaLink]) -> bool:
    """Link the rendered media, or expire it when its observation is gone. Returns whether it was linked."""
    try:
        # `for_team` resolves the canonical team with a synchronous query of its own.
        await sync_to_async(_link_media)(team_id, observation_id, links)
    except (IntegrityError, ReplayObservation.DoesNotExist):
        # The observation went away between the render and this write, so nothing will point at the objects.
        # The sweep deletes the stored object only for a row that carries a location.
        for link in links:
            await ExportedAsset.objects.filter(pk=link.asset_id, team_id=team_id).aupdate(
                content_location=link.content_location, expires_after=now()
            )
        return False
    return True


def _content_location(s3_uri: str) -> str:
    try:
        return content_location_from_s3_uri(s3_uri)
    except ValueError as error:
        raise ApplicationError(str(error), non_retryable=True) from error


@activity.defn
@track_activity()
async def finalize_observation_media_activity(inputs: FinalizeObservationMediaInputs) -> None:
    """Link every frame the video had to its slot, and expire the assets of the frames it did not have."""
    extracted = {frame.id: frame for frame in inputs.result.frames}
    links = [
        _MediaLink(
            kind=ReplayObservationMedia.Kind(frame.kind),
            position=frame.position,
            asset_id=frame.media_asset_id,
            video_start_ms=frame.video_start_ms,
            rec_start_ms=frame.rec_start_ms,
            content_location=_content_location(extracted[frame.object_id].s3_uri),
        )
        for frame in inputs.frames
        if frame.object_id in extracted
    ]
    missing = [frame.media_asset_id for frame in inputs.frames if frame.object_id not in extracted]
    if missing:
        await ExportedAsset.objects.filter(pk__in=missing, team_id=inputs.team_id).aupdate(expires_after=now())
    if links and await _link_or_expire(inputs.team_id, inputs.observation_id, links):
        logger.info(
            "replay_vision.media_ready",
            observation_id=str(inputs.observation_id),
            frames=len(links),
            missing=len(missing),
            file_size_bytes=sum(frame.file_size_bytes for frame in inputs.result.frames),
        )
