"""The tick of the observation windows of one team: reads the flag edits since the previous tick, and stores the windows
that `life_cycle.plan_tick` opens and closes."""

import json
import uuid
import dataclasses
from collections.abc import Iterable
from datetime import datetime, timedelta
from typing import Any

from django.db import transaction

import structlog
import posthoganalytics

from posthog.dataclasses import frozen
from posthog.models import Team
from posthog.utils import get_instance_region

from products.feature_flags.backend.exposure_change import FlagExposureConfig
from products.feature_flags.backend.flag_windows.history import exposure_config, flag_histories, owned_flag_ids
from products.feature_flags.backend.flag_windows.life_cycle import (
    ClosedWindow,
    TickPlan,
    TrackedWindow,
    observation_window,
    plan_tick,
)
from products.feature_flags.backend.flag_windows.window import WEB_WINDOW_PARAMETERS, WindowState
from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.feature_flags.backend.models.observation_window import (
    FlagObservationWindow,
    FlagWindowsCursor,
    FlagWindowState,
)

logger = structlog.get_logger(__name__)

# The payload lists the teams to watch for each region, as `{"US": {"team_ids": [2]}}`. Team ids repeat across regions.
# A disabled or missing flag watches no team.
WATCH_FLAG = "flag-rollback-windows"
_WATCH_FLAG_DISTINCT_ID = "flag_rollback_windows"

# An activity log entry gets its time when the request writes it, which can come before the commit. So each tick reads
# again the end of the previous range, and the windows dedupe the entries that it read before.
READ_OVERLAP = timedelta(minutes=10)


@frozen
class TeamTick:
    opened: int
    closed: int


def parse_watched_team_ids(payload: object, region: str | None) -> frozenset[int]:
    """The team ids in the entry of `region`. Anything missing or malformed watches no team."""
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except ValueError:
            return frozenset()
    if not isinstance(payload, dict) or region is None:
        return frozenset()
    entry = payload.get(region)
    team_ids = entry.get("team_ids") if isinstance(entry, dict) else None
    if not isinstance(team_ids, list) or not all(
        isinstance(team_id, int) and not isinstance(team_id, bool) for team_id in team_ids
    ):
        return frozenset()
    return frozenset(team_ids)


def watched_team_ids() -> list[int]:
    """The teams of the watch flag whose organization approved AI data processing, since the scout that judges a
    suspicious window sends its data to an LLM."""
    try:
        payload = posthoganalytics.get_feature_flag_payload(
            WATCH_FLAG, _WATCH_FLAG_DISTINCT_ID, send_feature_flag_events=False
        )
    except Exception:
        logger.exception("flag_windows.watch_flag_failed")
        return []
    team_ids = parse_watched_team_ids(payload, get_instance_region())
    return sorted(
        Team.objects.filter(id__in=team_ids, organization__is_ai_data_processing_approved=True).values_list(
            "id", flat=True
        )
    )


def tick_team(team_id: int, now: datetime) -> TeamTick:
    """Opens the windows of the edits since the previous tick, and closes the windows that those edits or the time
    close. The first tick of a team only starts the cursor, so the edits before the watch started open no window."""
    cursor = FlagWindowsCursor.objects.for_team(team_id).first()
    if cursor is None:
        FlagWindowsCursor.objects.for_team(team_id).get_or_create(team_id=team_id, defaults={"read_until": now})
        return TeamTick(opened=0, closed=0)

    histories = flag_histories(team_id, cursor.read_until - READ_OVERLAP)
    rows = list(FlagObservationWindow.objects.for_team(team_id).exclude(state=FlagWindowState.CLOSED))
    flag_ids = {history.flag_id for history in histories} | {row.feature_flag_id for row in rows}
    edit_ids = [
        uuid.UUID(version.activity_log_id)
        for history in histories
        for version in history.versions
        if version.activity_log_id is not None
    ]
    plan = plan_tick(
        histories,
        [_tracked(row) for row in rows],
        current=_current_configs(team_id, {row.feature_flag_id for row in rows}),
        known_edits=frozenset(
            str(edit_id)
            for edit_id in FlagObservationWindow.objects.for_team(team_id)
            .filter(activity_log_id__in=edit_ids)
            .values_list("activity_log_id", flat=True)
        ),
        excluded_flag_ids=_excluded_flag_ids(team_id, flag_ids),
        now=now,
        max_duration=WEB_WINDOW_PARAMETERS.max_duration,
    )
    with transaction.atomic():
        _store(team_id, plan)
        cursor.read_until = now
        cursor.save(update_fields=["read_until"])
    return TeamTick(opened=len(plan.opened), closed=len(plan.closed))


def _store(team_id: int, plan: TickPlan) -> None:
    # The closes go first, so that a flag never holds two windows that are not closed.
    opened = {window.activity_log_id for window in plan.opened}
    closes_of_new: dict[str, ClosedWindow] = {}
    for closed in plan.closed:
        if closed.activity_log_id in opened:
            closes_of_new[closed.activity_log_id] = closed
            continue
        FlagObservationWindow.objects.for_team(team_id).filter(activity_log_id=closed.activity_log_id).update(
            state=FlagWindowState.CLOSED, close_reason=closed.reason, closed_at=closed.closed_at
        )
    previous_ids = [window.previous_activity_log_id for window in plan.opened if window.previous_activity_log_id]
    ids = {
        str(activity_log_id): window_id
        for activity_log_id, window_id in FlagObservationWindow.objects.for_team(team_id)
        .filter(activity_log_id__in=previous_ids)
        .values_list("activity_log_id", "id")
    }
    for window in plan.opened:
        close = closes_of_new.get(window.activity_log_id)
        row = FlagObservationWindow.objects.for_team(team_id).create(
            team_id=team_id,
            feature_flag_id=window.flag_id,
            activity_log_id=uuid.UUID(window.activity_log_id),
            edited_at=window.edited_at,
            config_before=_dump(window.config_before),
            config_after=_dump(window.config_after),
            previous_window_id=ids.get(window.previous_activity_log_id or ""),
            state=FlagWindowState.CLOSED if close else FlagWindowState.OPEN,
            close_reason=close.reason if close else None,
            closed_at=close.closed_at if close else None,
        )
        ids[window.activity_log_id] = row.id


def _tracked(row: FlagObservationWindow) -> TrackedWindow:
    return TrackedWindow(
        flag_id=row.feature_flag_id,
        activity_log_id=str(row.activity_log_id),
        window=observation_window(
            activity_log_id=str(row.activity_log_id),
            edited_at=row.edited_at,
            config_before=_load(row.config_before),
            config_after=_load(row.config_after),
            state=WindowState(row.state),
        ),
    )


def _current_configs(team_id: int, flag_ids: Iterable[int]) -> dict[int, FlagExposureConfig]:
    flags = FeatureFlag.objects_including_soft_deleted.filter(team_id=team_id, id__in=list(flag_ids))
    return {flag.id: exposure_config(flag) for flag in flags}


def _excluded_flag_ids(team_id: int, flag_ids: set[int]) -> frozenset[int]:
    opted_out = FeatureFlag.objects_including_soft_deleted.filter(
        team_id=team_id, id__in=list(flag_ids), rollback_suggestions_disabled=True
    ).values_list("id", flat=True)
    return owned_flag_ids(team_id, flag_ids) | frozenset(opted_out)


def _dump(config: FlagExposureConfig) -> dict[str, Any]:
    return dataclasses.asdict(config)


def _load(data: dict[str, Any]) -> FlagExposureConfig:
    return FlagExposureConfig(**data)
