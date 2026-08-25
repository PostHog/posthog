import re
from collections.abc import Callable, Sequence
from typing import Any, Literal

from django.db.models import Q

import structlog

from posthog.schema import RecordingsQuery

from posthog.clickhouse.client.connection import ClickHouseUser
from posthog.dataclasses import frozen
from posthog.models import EventDefinition, Team, User
from posthog.rbac.user_access_control import UserAccessControl
from posthog.session_recordings.models.session_recording_playlist import SessionRecordingPlaylist
from posthog.session_recordings.playlist_filters import convert_playlist_to_recordings_query
from posthog.settings import EE_AVAILABLE

from products.actions.backend.models.action import Action
from products.replay_vision.backend.queries.scanner_volume_estimate import (
    PREVIEW_ESTIMATE_BUDGET,
    EstimateBudget,
    estimate_scanner_session_volume,
)
from products.replay_vision.backend.queries.top_visited_paths import fetch_top_visited_paths

logger = structlog.get_logger(__name__)

SurfaceKind = Literal["page", "playlist", "action", "event"]

# Words that describe wanting to look at something rather than what to look at. Without these removed,
# "checkout flow" matches every surface whose name contains "flow".
_STOPWORDS = frozenset(
    """the a an and or for of on in to my our all new page pages screen screens flow flows funnel
    journey user users session sessions""".split()
)
# Below this, a prefix match is coincidence rather than a shared stem ("id" vs "identity").
_MIN_PREFIX_MATCH_CHARS = 4

# Saying one of these is how a caller asks for a saved playlist by name. Absent them, the scope
# describes the product, not the caller's saved views, and a playlist that happens to share a word
# with it is a coincidence — see `_playlist_requested`.
_PLAYLIST_MARKERS = ("playlist", "saved filter", "saved search", "saved view", "collection")

# How many rows each source offers the matcher. Bounded so a large team cannot turn a resolve into a
# full table read; the matcher only ever keeps a handful.
_MAX_PLAYLIST_CANDIDATES = 200
_MAX_ACTION_CANDIDATES = 300
_MAX_EVENT_CANDIDATES = 300

_MAX_SURFACES_PER_KIND = 8
_MAX_SURFACES_TOTAL = 20

# More than this and the filter stops describing one flow.
_MAX_FILTER_PAGES = 5
# `icontains` on "/" or "/en" matches nearly every URL, so a short path reads as a narrowing filter
# while narrowing nothing.
_MIN_PAGE_FILTER_CHARS = 3

# A scanner's window comes from the sweep, and paging belongs to whoever reads the results.
_PLAYLIST_QUERY_FIELDS_TO_STRIP = ("date_from", "date_to", "limit", "offset", "after", "response")

_MAX_DETAIL_CHARS = 300


@frozen
class SurfaceMatch:
    kind: SurfaceKind
    # pathname, playlist short_id, action id, or event name — whatever identifies the surface to a caller.
    key: str
    name: str
    detail: str
    score: float
    # Pages only; the other sources carry no volume of their own.
    sessions: int | None = None


@frozen
class ScopeResolution:
    scope: str
    surfaces: tuple[SurfaceMatch, ...]
    query: dict[str, Any] | None
    matched_sessions: int | None
    window_days: int | None
    sampled: bool
    # Sources that errored and contributed nothing, so a caller can say the answer is partial.
    degraded_sources: tuple[str, ...]


@frozen
class _PlaylistMatch:
    surface: SurfaceMatch
    playlist: SessionRecordingPlaylist


def resolve_scope(
    *,
    team: Team,
    scope: str,
    user: User | None = None,
    user_access_control: UserAccessControl | None = None,
    estimate: bool = True,
    budget: EstimateBudget = PREVIEW_ESTIMATE_BUDGET,
    ch_user: ClickHouseUser = ClickHouseUser.APP,
) -> ScopeResolution:
    """Turn a free-text scope phrase into the product surfaces it names, one recording filter, and a count.

    Matching is lexical and deterministic — no model call. Page paths, actions, and custom events are
    matched as grounding, but only pages build the filter: `RecordingsQuery` ANDs its events together,
    so filtering on several matched events narrows to nothing.

    Saved playlists are consulted only when the scope asks for one by saying so ("the billing
    playlist"). A playlist sharing a word with a description of the product is a coincidence, not a
    request, and adopting its filters would answer a question the caller did not ask. When one is
    asked for, its filters are used as saved, however wide — that is what was asked for.

    Each source is isolated, so one erroring source degrades the answer rather than failing it.
    """
    playlist_requested = _playlist_requested(scope)
    scope_tokens = _tokens(scope, drop_playlist_markers=playlist_requested)
    phrase = _normalize(scope)
    if not scope_tokens:
        # A phrase with no content words would match everything, and an everything-filter is worse
        # than none: it reads as narrowing while narrowing nothing.
        return ScopeResolution(
            scope=scope,
            surfaces=(),
            query=None,
            matched_sessions=None,
            window_days=None,
            sampled=False,
            degraded_sources=(),
        )

    degraded: list[str] = []
    # Not queried at all unless asked for, so an unasked-for playlist cannot reach the response.
    playlist_matches = (
        _isolated(
            "playlists", lambda: _playlist_matches(team, scope_tokens, phrase, user_access_control), degraded, team
        )
        if playlist_requested
        else ()
    )
    pages = _isolated("pages", lambda: _page_surfaces(team, scope_tokens, phrase, ch_user), degraded, team)
    actions = _isolated(
        "actions", lambda: _action_surfaces(team, scope_tokens, phrase, user_access_control), degraded, team
    )
    events = _isolated("events", lambda: _event_surfaces(team, scope_tokens, phrase), degraded, team)

    # Pages lead because they build the filter in the ordinary case. A requested playlist outranks
    # them, since then it is the thing the caller named. Actions and events are evidence only.
    surfaces = (tuple(m.surface for m in playlist_matches) + pages + actions + events)[:_MAX_SURFACES_TOTAL]
    requested_playlist = playlist_matches[0].playlist if playlist_matches else None
    query = _build_query(requested_playlist, [p.key for p in pages])

    matched_sessions: int | None = None
    window_days: int | None = None
    sampled = False
    if estimate and query is not None:
        try:
            volume = estimate_scanner_session_volume(
                team=team,
                query=RecordingsQuery.model_validate(query),
                user=user,
                budget=budget,
                ch_user=ch_user,
            )
            matched_sessions = volume.matched_sessions
            window_days = volume.effective_window_days
            sampled = volume.sampled
        except Exception:
            # A slow count must not throw away a filter that is otherwise good.
            logger.warning("replay_vision.scope_resolution.estimate_failed", team_id=team.id, exc_info=True)
            degraded.append("estimate")

    return ScopeResolution(
        scope=scope,
        surfaces=surfaces,
        query=query,
        matched_sessions=matched_sessions,
        window_days=window_days,
        sampled=sampled,
        degraded_sources=tuple(degraded),
    )


def _isolated[T](source: str, fetch: Callable[[], tuple[T, ...]], degraded: list[str], team: Team) -> tuple[T, ...]:
    try:
        return fetch()
    except Exception:
        logger.warning("replay_vision.scope_resolution.source_failed", source=source, team_id=team.id, exc_info=True)
        degraded.append(source)
        return ()


def _normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.casefold()).strip()


def _playlist_requested(scope: str) -> bool:
    """Whether the caller asked for a saved playlist rather than describing the product."""
    normalized = _normalize(scope)
    return any(marker in normalized for marker in _PLAYLIST_MARKERS)


def _tokens(text: str, *, drop_playlist_markers: bool = False) -> tuple[str, ...]:
    tokens = tuple(
        token
        for token in _normalize(text).split()
        if len(token) > 1 and not token.isdigit() and token not in _STOPWORDS
    )
    if not drop_playlist_markers:
        return tokens
    # "billing playlist" names a playlist called "Billing"; leaving the marker in would score every
    # candidate whose own name happens to contain it.
    marker_words = {word for marker in _PLAYLIST_MARKERS for word in marker.split()}
    return tuple(token for token in tokens if token not in marker_words)


def _tokens_match(left: str, right: str) -> bool:
    if left == right:
        return True
    shorter, longer = (left, right) if len(left) <= len(right) else (right, left)
    return len(shorter) >= _MIN_PREFIX_MATCH_CHARS and longer.startswith(shorter)


def _score(scope_tokens: Sequence[str], phrase: str, candidate: str) -> float:
    """How well a candidate surface answers the scope phrase. 0.0 means no match at all."""
    candidate_tokens = _tokens(candidate)
    if not candidate_tokens:
        return 0.0
    matched = sum(1 for token in scope_tokens if any(_tokens_match(token, other) for other in candidate_tokens))
    if not matched:
        return 0.0
    # A candidate containing the whole phrase outranks one that merely shares its words.
    phrase_bonus = 1.0 if phrase and phrase in _normalize(candidate) else 0.0
    return phrase_bonus + matched / len(scope_tokens)


def _score_named(scope_tokens: Sequence[str], phrase: str, name: str, description: str) -> float:
    """A description hit is real evidence but weaker than a name hit, so it is worth half."""
    return max(_score(scope_tokens, phrase, name), 0.5 * _score(scope_tokens, phrase, description))


def _detail(text: str | None) -> str:
    return (text or "").strip()[:_MAX_DETAIL_CHARS]


def _page_surfaces(
    team: Team, scope_tokens: Sequence[str], phrase: str, ch_user: ClickHouseUser
) -> tuple[SurfaceMatch, ...]:
    matches = [
        SurfaceMatch(kind="page", key=path.pathname, name=path.pathname, detail="", score=score, sessions=path.sessions)
        for path in fetch_top_visited_paths(team=team, ch_user=ch_user)
        if (score := _score(scope_tokens, phrase, path.pathname))
    ]
    # Volume breaks ties: between two equally-named pages, the busier one is the one users mean.
    matches.sort(key=lambda m: (-m.score, -(m.sessions or 0), m.key))
    return tuple(matches[:_MAX_SURFACES_PER_KIND])


def _playlist_matches(
    team: Team, scope_tokens: Sequence[str], phrase: str, user_access_control: UserAccessControl | None
) -> tuple[_PlaylistMatch, ...]:
    queryset = (
        SessionRecordingPlaylist.objects.filter(team_id=team.id, deleted=False)
        # A collection is a pinned list of sessions, so it holds no filters to reuse.
        .exclude(type=SessionRecordingPlaylist.PlaylistType.COLLECTION)
        .order_by("-last_modified_at")
    )
    if user_access_control is not None:
        # Filter before scoring: a scope phrase must not confirm a private playlist's name.
        queryset = user_access_control.filter_queryset_by_access_level(queryset, resource="session_recording_playlist")

    matches: list[_PlaylistMatch] = []
    for playlist in queryset[:_MAX_PLAYLIST_CANDIDATES]:
        label = (playlist.name or playlist.derived_name or "").strip()
        if not label:
            continue
        score = _score_named(scope_tokens, phrase, label, playlist.description)
        if not score:
            continue
        matches.append(
            _PlaylistMatch(
                surface=SurfaceMatch(
                    kind="playlist",
                    key=playlist.short_id,
                    name=label,
                    detail=_detail(playlist.description),
                    score=score,
                ),
                playlist=playlist,
            )
        )
    matches.sort(key=lambda m: (-m.surface.score, m.surface.key))
    return tuple(matches[:_MAX_SURFACES_PER_KIND])


def _action_surfaces(
    team: Team, scope_tokens: Sequence[str], phrase: str, user_access_control: UserAccessControl | None
) -> tuple[SurfaceMatch, ...]:
    # `team_id=` rather than `team=`: only the kwarg form makes RootTeamManager resolve the parent
    # team, so `team=team` silently returns nothing on a child environment.
    # Ordered by recency, not name: the candidate cap would otherwise cut a fixed alphabetical tail
    # that no scope phrase could ever reach.
    queryset = Action.objects.filter(team_id=team.id, deleted=False).order_by("-updated_at")
    if user_access_control is not None:
        # Actions are access-controlled, so a scope phrase must not confirm the name of one the
        # caller cannot read. The resource check is not redundant: filter_queryset_by_access_level
        # returns the queryset untouched when there is neither resource access nor an object grant,
        # because in a viewset it is has_permission that refuses the request.
        if not user_access_control.check_access_level_for_resource(
            "action", required_level="viewer"
        ) and not user_access_control.has_any_specific_access_for_resource("action", required_level="viewer"):
            return ()
        queryset = user_access_control.filter_queryset_by_access_level(queryset, resource="action")
    matches: list[SurfaceMatch] = []
    for action in queryset[:_MAX_ACTION_CANDIDATES]:
        label = (action.name or "").strip()
        if not label:
            continue
        # `summary` is model-written prose; it makes a useful detail but would blur the ranking.
        score = _score_named(scope_tokens, phrase, label, action.description)
        if not score:
            continue
        matches.append(
            SurfaceMatch(
                kind="action",
                key=str(action.id),
                name=label,
                detail=_detail(action.description or action.summary),
                score=score,
            )
        )
    matches.sort(key=lambda m: (-m.score, m.name))
    return tuple(matches[:_MAX_SURFACES_PER_KIND])


def _event_surfaces(team: Team, scope_tokens: Sequence[str], phrase: str) -> tuple[SurfaceMatch, ...]:
    names = list(
        # Project-scoped with a team-scoped fallback, the same predicate core's event-definition
        # reads use and the one `_event_descriptions` below already used. A literal team_id filter
        # misses every definition recorded against the project rather than this environment.
        EventDefinition.objects.filter(
            Q(project_id=team.project_id) | Q(project_id__isnull=True, team_id=team.project_id),
            last_seen_at__isnull=False,
        )
        # PostHog internals ($pageview and friends) are never product surfaces.
        .exclude(name__startswith="$")
        .order_by("-last_seen_at")
        .values_list("name", flat=True)[:_MAX_EVENT_CANDIDATES]
    )
    descriptions = _event_descriptions(team, names)
    matches: list[SurfaceMatch] = []
    for name in names:
        description = descriptions.get(name, "")
        score = _score_named(scope_tokens, phrase, name, description)
        if not score:
            continue
        matches.append(SurfaceMatch(kind="event", key=name, name=name, detail=_detail(description), score=score))
    matches.sort(key=lambda m: (-m.score, m.name))
    return tuple(matches[:_MAX_SURFACES_PER_KIND])


def _event_descriptions(team: Team, names: Sequence[str]) -> dict[str, str]:
    if not EE_AVAILABLE or not names:
        return {}
    from ee.models.event_definition import EnterpriseEventDefinition  # noqa: PLC0415 — absent from OSS builds

    # Project-scoped with a team-scoped fallback, mirroring posthog/api/event_definition.py.
    rows = (
        EnterpriseEventDefinition.objects.filter(
            Q(project_id=team.project_id) | Q(project_id__isnull=True, team_id=team.project_id),
            name__in=list(names),
        )
        .exclude(description__isnull=True)
        .exclude(description="")
        .values_list("name", "description")
    )
    return {name: description for name, description in rows if description}


def _playlist_query(playlist: SessionRecordingPlaylist) -> dict[str, Any] | None:
    """The playlist's saved filters as a query, or None when they can't be converted.

    Playlist filters accumulated several shapes over the years and some saved rows no longer convert.
    That is the playlist's problem, not the caller's: fall through to the matched pages rather than
    failing a resolve that has a perfectly good answer without it.
    """
    try:
        # `persist_legacy_conversion=False` because this is a read path: the default writes the
        # converted filters back onto the shared playlist row.
        recordings_query = convert_playlist_to_recordings_query(playlist, persist_legacy_conversion=False)
    except Exception:
        logger.warning(
            "replay_vision.scope_resolution.playlist_conversion_failed",
            team_id=playlist.team_id,
            playlist_id=playlist.short_id,
            exc_info=True,
        )
        return None
    query = recordings_query.model_dump(mode="json", exclude_none=True)
    for field in _PLAYLIST_QUERY_FIELDS_TO_STRIP:
        query.pop(field, None)
    query["kind"] = "RecordingsQuery"
    return query


def _page_can_ground(pathname: str) -> bool:
    return len(pathname.replace("/", "").strip()) >= _MIN_PAGE_FILTER_CHARS


def _build_query(playlist: SessionRecordingPlaylist | None, pathnames: Sequence[str]) -> dict[str, Any] | None:
    if playlist is not None and (query := _playlist_query(playlist)) is not None:
        return query

    # Matched pages ANDed as separate properties match almost nothing. One property holding every
    # value compiles to arrayExists(... multiSearchAny ...), which is the "touched any of these" the
    # caller means.
    values = list(dict.fromkeys(p for p in pathnames if _page_can_ground(p)))[:_MAX_FILTER_PAGES]
    if not values:
        return None
    return {
        "kind": "RecordingsQuery",
        "properties": [{"type": "recording", "key": "visited_page", "value": values, "operator": "icontains"}],
    }
