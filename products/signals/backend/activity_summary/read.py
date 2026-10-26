"""Read a user's own activity summary and its versions, for the organizations the flag payload enrolls.

Every read returns `None` when the team is not enrolled, so the caller can answer as if the feature did
not exist. The stored JSON comes from older prompt versions too, so each field is read defensively.
"""

import datetime
from typing import Any

from django.db import models

from posthog.dataclasses import frozen
from posthog.models import Team

from products.signals.backend.activity_summary.computed import COMPUTED_SCHEMA_VERSION
from products.signals.backend.activity_summary.config import ActivitySummaryConfig, read_config
from products.signals.backend.activity_summary.logic import is_stale
from products.signals.backend.activity_summary.queue import is_team_enrolled_for_read
from products.signals.backend.models import UserActivitySummary, UserActivitySummaryVersion

DEFAULT_VERSIONS_LIMIT = 5


class ActivitySummaryStatus(models.TextChoices):
    READY = "ready"
    # No row, or no update succeeded yet.
    NOT_READY = "not_ready"


@frozen
class ActivitySummaryTheme:
    label: str
    # Null on themes from before prompt version 6.
    mode: str | None
    strength: str | None
    refs: tuple[str, ...]
    last_seen: str | None


@frozen
class ActivitySummaryView:
    status: ActivitySummaryStatus
    headline: str | None = None
    profile: str | None = None
    themes: tuple[ActivitySummaryTheme, ...] = ()
    modes: tuple[str, ...] = ()
    recent_shift: str | None = None
    computed: dict[str, Any] | None = None
    generated_at: datetime.datetime | None = None
    version: int = 0
    prompt_version: int | None = None
    stale: bool = False


@frozen
class ActivitySummaryVersionView:
    version: int
    generated_at: datetime.datetime
    prompt_version: int
    headline: str | None
    recent_shift: str | None
    themes: tuple[ActivitySummaryTheme, ...]
    modes: tuple[str, ...]
    # Only a read of one version carries the profile and the computed fields, so a list stays small.
    profile: str | None = None
    computed: dict[str, Any] | None = None


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _headline(summary: dict[str, Any]) -> str | None:
    # A summary stored before prompt version 3 has a `summary` and no `headline`.
    return _text(summary.get("headline")) or _text(summary.get("summary"))


def _strings(value: Any) -> tuple[str, ...]:
    return tuple(item for item in value if _text(item) is not None) if isinstance(value, list) else ()


def _themes(summary: dict[str, Any]) -> tuple[ActivitySummaryTheme, ...]:
    # A summary stored before prompt version 6 has `focus_areas` with a `topic`, and no mode or refs.
    themes = summary.get("themes")
    items: Any = themes if isinstance(themes, list) else summary.get("focus_areas")
    label_key = "label" if isinstance(themes, list) else "topic"
    if not isinstance(items, list):
        return ()
    return tuple(
        ActivitySummaryTheme(
            label=label,
            mode=_text(item.get("mode")),
            strength=_text(item.get("strength")),
            refs=_strings(item.get("refs")),
            last_seen=_text(item.get("last_seen")),
        )
        for item in items
        if isinstance(item, dict) and (label := _text(item.get(label_key))) is not None
    )


def _computed(value: Any) -> dict[str, Any] | None:
    # A row from before the field existed has none. A row from another schema version has another shape.
    return value if isinstance(value, dict) and value.get("schema_version") == COMPUTED_SCHEMA_VERSION else None


def _readable_config(team: Team) -> ActivitySummaryConfig | None:
    config = read_config()
    return config if is_team_enrolled_for_read(config, team) else None


def get_summary(team: Team, user_id: int) -> ActivitySummaryView | None:
    """The user's current summary. A failed later update keeps the last good summary, so it is still ready."""
    config = _readable_config(team)
    if config is None:
        return None
    row = UserActivitySummary.objects.for_team(team.id).filter(user_id=user_id).first()
    if row is None or not isinstance(row.summary, dict) or row.generated_at is None:
        return ActivitySummaryView(status=ActivitySummaryStatus.NOT_READY)
    return ActivitySummaryView(
        status=ActivitySummaryStatus.READY,
        headline=_headline(row.summary),
        profile=_text(row.summary.get("profile")),
        themes=_themes(row.summary),
        modes=_strings(row.summary.get("modes")),
        recent_shift=_text(row.summary.get("recent_shift")),
        computed=_computed(row.computed),
        generated_at=row.generated_at,
        version=row.version,
        prompt_version=row.prompt_version,
        stale=is_stale(row, config.rebuild_before),
    )


def _version_view(row: UserActivitySummaryVersion, *, with_profile: bool) -> ActivitySummaryVersionView:
    summary = row.summary if isinstance(row.summary, dict) else {}
    return ActivitySummaryVersionView(
        version=row.version,
        generated_at=row.generated_at,
        prompt_version=row.prompt_version,
        headline=_headline(summary),
        recent_shift=_text(summary.get("recent_shift")),
        themes=_themes(summary),
        modes=_strings(summary.get("modes")),
        profile=_text(summary.get("profile")) if with_profile else None,
        computed=_computed(row.computed) if with_profile else None,
    )


def list_versions(
    team: Team, user_id: int, *, limit: int = DEFAULT_VERSIONS_LIMIT, version: int | None = None
) -> list[ActivitySummaryVersionView] | None:
    """The user's summary versions, newest first, cut to `limit` and the configured `max_versions`.

    With `version`, the list holds only that version, with its profile, or nothing when it does not exist.
    """
    config = _readable_config(team)
    if config is None:
        return None
    rows = UserActivitySummaryVersion.objects.for_team(team.id).filter(summary_row__user_id=user_id)
    if version is not None:
        return [_version_view(row, with_profile=True) for row in rows.filter(version=version)[:1]]
    return [
        _version_view(row, with_profile=False)
        for row in rows.order_by("-version")[: max(1, min(limit, config.max_versions))]
    ]
