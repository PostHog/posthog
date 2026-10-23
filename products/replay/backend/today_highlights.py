from functools import partial

from posthog.ph_client import feature_enabled_or_false
from posthog.session_recordings.models.session_recording_playlist import SessionRecordingPlaylist
from posthog.session_recordings.session_recording_playlist_api import count_saved_filters

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.today.backend.facade.contracts import HighlightCandidate, HighlightContext, HighlightFindings
from products.today.backend.facade.enums import HighlightLabel
from products.today.backend.facade.highlight_helpers import human, routine_days_for, short, viewed_days

SAVED_FILTERS_FLAG = "today-replay-saved-filters"
REPLAY_SCENES = ("Replay", "ReplayPlaylist", "ReplaySingle")
SAVED_FILTERS_TRIED = 5
SAVED_FILTERS_SHOWN = 2

UNWATCHED = "‘{name}’ has {count} you haven’t watched"
UNWATCHED_DETAIL = "Saved filter · You open Replay often"


def find_unwatched_saved_filters(context: HighlightContext) -> HighlightFindings:
    """The saved filters a habitual Replay viewer uses that hold recordings they have not watched yet."""
    if not _flag_on(context) or not routine_days_for(context, "scene", *REPLAY_SCENES):
        return HighlightFindings()
    items: list[HighlightCandidate] = []
    for playlist in _saved_filters(context):
        if len(items) >= SAVED_FILTERS_SHOWN:
            break
        item = context.guard(f"replay_saved_filter {playlist.short_id}", partial(_item, context, playlist), None)
        if item is not None:
            items.append(item)
    return HighlightFindings(items=tuple(items))


def _flag_on(context: HighlightContext) -> bool:
    return feature_enabled_or_false(
        SAVED_FILTERS_FLAG,
        str(context.user.distinct_id),
        groups={"organization": str(context.team.organization_id), "project": str(context.team.id)},
        group_properties={
            "organization": {"id": str(context.team.organization_id)},
            "project": {"id": str(context.team.id)},
        },
        person_properties={"email": context.user.email},
        send_feature_flag_events=False,
    )


def _saved_filters(context: HighlightContext) -> list[SessionRecordingPlaylist]:
    """Saved filters the viewer opened lately, most days first, then the ones they made."""
    opened = viewed_days(context, "session_recording_playlist")
    playlists = SessionRecordingPlaylist.objects.filter(
        team=context.team, deleted=False, type=SessionRecordingPlaylist.PlaylistType.FILTERS
    )
    visible = UserAccessControl(user=context.user, team=context.team).filter_queryset_by_access_level(playlists)
    used = sorted(
        visible.filter(short_id__in=list(opened)),
        key=lambda playlist: (len(opened[playlist.short_id]), playlist.last_modified_at),
        reverse=True,
    )
    made = visible.filter(created_by=context.user).exclude(short_id__in=list(opened)).order_by("-last_modified_at")
    return [*used, *made[:SAVED_FILTERS_TRIED]][:SAVED_FILTERS_TRIED]


def _item(context: HighlightContext, playlist: SessionRecordingPlaylist) -> HighlightCandidate | None:
    counts = count_saved_filters(playlist, context.user, context.team)
    unwatched = int(counts["count"] or 0) - int(counts["watched_count"] or 0)
    if unwatched <= 0:
        return None
    recordings = "1 recording" if unwatched == 1 else f"{human(unwatched)} recordings"
    if counts["has_more"]:
        recordings = f"{human(unwatched)}+ recordings"
    return HighlightCandidate(
        key=f"replay_saved_filter:{playlist.short_id}",
        label=HighlightLabel.OPPORTUNITY,
        family="replay",
        importance=0.5,
        relevance=1.0,
        title=UNWATCHED.format(name=short(playlist.name or playlist.derived_name or "Untitled", 40), count=recordings),
        detail=UNWATCHED_DETAIL,
        url=f"/replay/home?savedFilterId={playlist.short_id}",
        ref=f"session_recording_playlist:{playlist.short_id}",
    )
