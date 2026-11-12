from collections.abc import Collection
from datetime import timedelta
from typing import TYPE_CHECKING
from uuid import UUID

import structlog

from posthog.utils import absolute_uri

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.data_modeling.backend.facade.api import all_saved_query_names, humanize_cadence

from ..facade.contracts import (
    MaterializePayload,
    SubjectKinds,
    SuggestionPayload,
    UnmaterializePayload,
    UnsupportedPayloadVersionError,
    WarehouseSuggestionNote,
)
from ..facade.enums import (
    WarehouseSuggestionKind,
    WarehouseSuggestionMainSaving,
    WarehouseSuggestionStatus,
    WarehouseSuggestionSubjectKind,
)
from ..models import WarehouseSuggestion
from .access import shown_suggestions, visible_suggestions
from .flags import is_warehouse_suggestions_enabled
from .payloads import payload_from_json

if TYPE_CHECKING:
    from posthog.models import Team, User

logger = structlog.get_logger(__name__)

NOTE_KINDS = frozenset({WarehouseSuggestionKind.MATERIALIZE, WarehouseSuggestionKind.UNMATERIALIZE})
MAX_NOTES = 3
MAX_VIEW_NAME_CHARS = 60
MIN_SECONDS_WORTH_NAMING = 60
MIN_BYTES_WORTH_NAMING = 10**9
ACCEPT_TOOL = "warehouse-suggestions-accept"
DISMISS_TOOL = "warehouse-suggestions-dismiss"
CONFIRMED_ACTION_PREPARE_SUFFIX = "-prepare"
VIEWS = frozenset({WarehouseSuggestionSubjectKind.SAVED_QUERY})
VIEW_SUBJECT_KINDS = SubjectKinds(readable=VIEWS, actionable=VIEWS)
READ_ONLY_VIEW_SUBJECT_KINDS = SubjectKinds(readable=VIEWS, actionable=frozenset())
SECONDS_UNITS = ((86400, "day"), (3600, "hour"), (60, "minute"), (1, "second"))
BYTE_UNITS = ((10**12, "TB"), (10**9, "GB"), (10**6, "MB"))
MCP_SHARE_STEP = (
    "Accepting or dismissing it needs edit access to the view and an API key with write scope, "
    "so share it with someone who has both."
)


def suggestions_for_read_views(
    team: "Team", user: "User", saved_query_ids: Collection[str], *, is_mcp_run: bool, can_write: bool
) -> list[WarehouseSuggestionNote] | None:
    if not is_warehouse_suggestions_enabled(team, only_evaluate_locally=True):
        return None
    view_ids = _parse_ids(saved_query_ids)
    if not view_ids:
        return []
    open_suggestions = shown_suggestions(
        team.pk, subject_kinds=VIEW_SUBJECT_KINDS, status=WarehouseSuggestionStatus.PROPOSED, subject_ids=view_ids
    )
    if not open_suggestions.filter(kind__in=NOTE_KINDS).exists():
        return []
    visible, access = visible_suggestions(
        team.pk,
        UserAccessControl(user, team),
        status=WarehouseSuggestionStatus.PROPOSED,
        subject_ids=view_ids,
        subject_kinds=VIEW_SUBJECT_KINDS if can_write else READ_ONLY_VIEW_SUBJECT_KINDS,
    )
    rows = list(visible.filter(kind__in=NOTE_KINDS)[:MAX_NOTES])
    names = all_saved_query_names(team.pk, ids=[row.subject_id for row in rows])
    notes = []
    for row in rows:
        view_name = names.get(str(row.subject_id))
        payload = _payload(row)
        if view_name is None or payload is None:
            continue
        notes.append(_note(team.pk, row, payload, view_name, can_act=access.can_act_on(row), is_mcp_run=is_mcp_run))
    return notes


def _parse_ids(saved_query_ids: Collection[str]) -> set[UUID]:
    view_ids = set()
    for saved_query_id in saved_query_ids:
        try:
            view_ids.add(UUID(saved_query_id))
        except ValueError:
            continue
    return view_ids


def _payload(row: WarehouseSuggestion) -> SuggestionPayload | None:
    try:
        return payload_from_json(WarehouseSuggestionKind(row.kind), row.payload_version, row.payload)
    except (UnsupportedPayloadVersionError, KeyError, TypeError, ValueError) as error:
        logger.warning(
            "warehouse_suggestion_query_note_payload_unreadable",
            suggestion_id=str(row.id),
            kind=row.kind,
            payload_version=row.payload_version,
            error=type(error).__name__,
        )
        return None


def _note(
    team_id: int,
    row: WarehouseSuggestion,
    payload: SuggestionPayload,
    view_name: str,
    *,
    can_act: bool,
    is_mcp_run: bool,
) -> WarehouseSuggestionNote:
    url = absolute_uri(f"/project/{team_id}/models/{row.subject_id}?lookup=saved_query")
    summary = _summary(payload, _shortened(view_name))
    message = f"{summary} {_next_step(row.id, url, can_act=can_act, is_mcp_run=is_mcp_run)}"
    return WarehouseSuggestionNote(
        id=row.id,
        kind=WarehouseSuggestionKind(row.kind),
        view_name=view_name,
        message=message,
        url=url,
        can_act=can_act,
    )


def _summary(payload: SuggestionPayload, view_name: str) -> str:
    if isinstance(payload, MaterializePayload):
        return materialize_summary(payload, view_name)
    if isinstance(payload, UnmaterializePayload):
        return unmaterialize_summary(payload, view_name)
    raise ValueError(f"No query note for {type(payload).__name__}")


def materialize_summary(payload: MaterializePayload, view_name: str) -> str:
    cadence = humanize_cadence(timedelta(seconds=payload.refresh_interval_seconds))
    sentences = [
        f"Materializing `{view_name}` would save {_materialize_saving(payload)} a month (estimated).",
        _freshness(payload, cadence),
    ]
    if -payload.saves_bytes_per_month >= MIN_BYTES_WORTH_NAMING:
        sentences.append(f"It would also scan about {_about_bytes(-payload.saves_bytes_per_month)} more a month.")
    if payload.read_seconds is not None:
        sentences.append(f"Reading it takes about {_about_duration(payload.read_seconds)} today.")
    return " ".join(sentences)


def unmaterialize_summary(payload: UnmaterializePayload, view_name: str) -> str:
    return (
        f"Stopping the refreshes of `{view_name}` would save {_unmaterialize_saving(payload)} a month "
        f"(estimated). Each read would then take about {_about_duration(payload.read_seconds)}."
    )


def _unmaterialize_saving(payload: UnmaterializePayload) -> str:
    seconds_saved = payload.refresh_seconds_per_month - payload.live_seconds_per_month
    if seconds_saved < MIN_SECONDS_WORTH_NAMING:
        bytes_saved = max(0.0, payload.refresh_bytes_per_month - payload.live_bytes_per_month)
        return f"about {_about_bytes(bytes_saved)} of scanning"
    return f"about {_about_duration(payload.refresh_seconds_per_month)} of background work"


def _materialize_saving(payload: MaterializePayload) -> str:
    estimate_word = "at least" if payload.measurement_capped else "about"
    if payload.main_saving == WarehouseSuggestionMainSaving.WAITING and payload.waiting_seconds_saved_per_month:
        return f"people {estimate_word} {_about_duration(payload.waiting_seconds_saved_per_month)} of waiting"
    if payload.main_saving == WarehouseSuggestionMainSaving.BACKGROUND and payload.background_seconds_saved_per_month:
        return f"{estimate_word} {_about_duration(payload.background_seconds_saved_per_month)} of background work"
    if payload.main_saving == WarehouseSuggestionMainSaving.SCANNED:
        return f"{estimate_word} {_about_bytes(payload.saves_bytes_per_month)} of scanning"
    return f"{estimate_word} {_about_duration(payload.saves_seconds_per_month)} of query time"


def _freshness(payload: MaterializePayload, cadence: str) -> str:
    if payload.unknown_sources:
        return f"It would refresh every {cadence}, which adds up to {cadence} to the age of its source data."
    age = _about_duration(payload.refresh_interval_seconds + (payload.freshness_today_seconds or 0))
    return f"It would refresh every {cadence}, so its data would be up to {age} old."


def _next_step(suggestion_id: UUID, url: str, *, can_act: bool, is_mcp_run: bool) -> str:
    if not is_mcp_run:
        return _app_step(url, can_act=can_act)
    if not can_act:
        return MCP_SHARE_STEP
    accept_tool = f"{ACCEPT_TOOL}{CONFIRMED_ACTION_PREPARE_SUFFIX}"
    return (
        f"If the person wants it, accept it with {accept_tool} (id {suggestion_id}) "
        f"or dismiss it with {DISMISS_TOOL}. Both need warehouse write scopes."
    )


def _app_step(url: str, *, can_act: bool) -> str:
    if can_act:
        return f"Review it at {url}"
    return f"Accepting it needs edit access to the view, so share {url} with someone who has it."


def _about_duration(seconds: float) -> str:
    for unit_seconds, unit in SECONDS_UNITS:
        if seconds >= unit_seconds:
            count = round(seconds / unit_seconds)
            return f"{count} {unit}" if count == 1 else f"{count} {unit}s"
    return "under a second"


def _about_bytes(byte_count: float) -> str:
    for unit_bytes, unit in BYTE_UNITS:
        if byte_count >= unit_bytes:
            return f"{byte_count / unit_bytes:.1f} {unit}"
    return "under 1 MB"


def _shortened(view_name: str) -> str:
    if len(view_name) <= MAX_VIEW_NAME_CHARS:
        return view_name
    return view_name[: MAX_VIEW_NAME_CHARS - 3] + "..."
