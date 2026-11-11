"""The edits of a feature flag, read from its activity log.

An edit keeps only the values that decide who gets which variant: the variant split, the release conditions, the
flag-level aggregation, and the bucketing settings. Pass them to ``facade.edits`` to learn what the edit did.
"""

from collections.abc import Collection
from datetime import datetime
from enum import StrEnum
from typing import Any

from django.db.models import F, Func, JSONField, Q, Value
from django.db.models.fields.json import KT

from posthog.dataclasses import frozen
from posthog.models.activity_logging.activity_log import AGENT_TRIGGER_JOB_TYPE, ActivityLog

from products.feature_flags.backend.facade.config import holdout_variant
from products.feature_flags.backend.facade.edits import BucketingSetting
from products.feature_flags.backend.facade.enums import SCHEDULED_CHANGE_JOB_TYPE

# The activity log fields of a flag save that can change who gets which value.
_FILTERS = "filters"
_SETTING_FIELDS = {
    BucketingSetting.KEY: "key",
    BucketingSetting.BUCKETING_IDENTIFIER: "bucketing_identifier",
    BucketingSetting.EXPERIENCE_CONTINUITY: "ensure_experience_continuity",
}
_SERVED_STRING_PATHS = (
    "multivariate.variants[*].key",
    "rules[*].value",
    "rules[*].variants[*].value",
    "default_value",
)
_PROJECTED = (
    "before_variants",
    "after_variants",
    "before_groups",
    "after_groups",
    "before_aggregation",
    "after_aggregation",
    *(f"{side}_{setting}" for side in ("before", "after") for setting in _SETTING_FIELDS),
)


@frozen
class FlagEditSide:
    """
    The JSON values on one side of an edit. A value is None when the edit does not change its field, or when that
    side has no value for it.
    """

    variants: object
    groups: object
    aggregation: object
    key: object
    bucketing_identifier: object
    experience_continuity: object

    @property
    def bucketing_settings(self) -> dict[BucketingSetting, object]:
        return {
            BucketingSetting.KEY: self.key,
            BucketingSetting.AGGREGATION: self.aggregation,
            BucketingSetting.BUCKETING_IDENTIFIER: self.bucketing_identifier,
            BucketingSetting.EXPERIENCE_CONTINUITY: self.experience_continuity,
        }


class FlagEditAuthor(StrEnum):
    """
    Who made a flag edit. An edit that another product triggers, such as an experiment exposure freeze, keeps the
    author of the action that caused it. Read `FlagEdit.job_type` to find those edits. When an agent causes such an
    edit, the author is PERSON, because `log_activity` adds the agent trigger only when the product sets no trigger.
    """

    # A user saved the flag, and no agent or scheduled change acted for them. A save outside a request that sets no
    # trigger also reads as PERSON, because the row records the flag's last modifier.
    PERSON = "person"
    # An agent saved the flag for a user. The agent trigger comes from a server-set task id or from the intent
    # header that agent clients such as the MCP server send, so the caller can claim it.
    AGENT = "agent"
    # A scheduled change applied the edit.
    SCHEDULED_CHANGE = "scheduled_change"
    # PostHog saved the flag outside a user request.
    SYSTEM = "system"


@frozen
class FlagEdit:
    changed_at: datetime
    # The `job_type` of the activity log trigger, or None when the trigger has no job type.
    job_type: str | None
    author: FlagEditAuthor
    # The user on the activity log row, which is the flag's last modifier at save time. An agent and a scheduled
    # change carry one too, so read `author` to learn who made the edit. None when that user was deleted.
    user_id: int | None
    # True when a staff member made the edit while impersonating the user in `user_id`.
    was_impersonated: bool
    before: FlagEditSide
    after: FlagEditSide


def flag_edits_since(*, team_id: int, feature_flag_id: int, since: datetime, limit: int) -> tuple[FlagEdit, ...]:
    """
    The edits of the flag after `since` that change a value in `FlagEditSide`, oldest first, at most `limit`. Pass
    one more than the cap you need, to know when the flag has more edits than the cap.
    """
    rows = (
        ActivityLog.objects.filter(
            _changes_any_field(_FILTERS, *_SETTING_FIELDS.values()),
            team_id=team_id,
            scope="FeatureFlag",
            item_id=str(feature_flag_id),
            created_at__gt=since,
        )
        .order_by("created_at")
        # Only these values decide who gets which variant, and the whole `detail` of a flag edit can be large.
        .annotate(
            job_type=KT("detail__trigger__job_type"),
            before_variants=_changed(_FILTERS, "before.multivariate.variants"),
            after_variants=_changed(_FILTERS, "after.multivariate.variants"),
            before_groups=_changed(_FILTERS, "before.groups"),
            after_groups=_changed(_FILTERS, "after.groups"),
            before_aggregation=_changed(_FILTERS, "before.aggregation_group_type_index"),
            after_aggregation=_changed(_FILTERS, "after.aggregation_group_type_index"),
            **{f"before_{setting}": _changed(field, "before") for setting, field in _SETTING_FIELDS.items()},
            **{f"after_{setting}": _changed(field, "after") for setting, field in _SETTING_FIELDS.items()},
        )
        .values("created_at", "job_type", "is_system", "user_id", "was_impersonated", *_PROJECTED)[:limit]
    )
    return tuple(
        FlagEdit(
            changed_at=row["created_at"],
            job_type=row["job_type"],
            author=_author(job_type=row["job_type"], is_system=row["is_system"], user_id=row["user_id"]),
            user_id=row["user_id"],
            was_impersonated=bool(row["was_impersonated"]),
            before=_side(row, "before"),
            after=_side(row, "after"),
        )
        for row in rows
    )


def served_strings_in_edits(*, team_id: int, flag_key: str, excluded_flag_ids: Collection[str]) -> list[str]:
    columns = {
        f"served_{index}": _changed(_FILTERS, f'*.{path} ? (@.type() == "string")', function="jsonb_path_query_array")
        for index, path in enumerate(_SERVED_STRING_PATHS)
    }
    rows = (
        ActivityLog.objects.filter(
            team_id=team_id,
            scope="FeatureFlag",
            detail__contains={"name": flag_key, "changes": [{"field": _FILTERS}]},
        )
        .exclude(item_id__in=excluded_flag_ids)
        .annotate(
            holdout_ids=_changed(_FILTERS, '*.holdout.id ? (@.type() == "number")', function="jsonb_path_query_array"),
            **columns,
        )
        .order_by()
        .values_list("holdout_ids", *columns)
        .distinct()
    )
    served: list[str] = []
    for holdout_ids, *strings in rows:
        served.extend(holdout_variant(holdout_id) for holdout_id in holdout_ids)
        served.extend(value for values in strings for value in values)
    return list(dict.fromkeys(value for value in served if value))


def _author(*, job_type: str | None, is_system: bool | None, user_id: int | None) -> FlagEditAuthor:
    # Check the trigger before the user, because an agent and a scheduled change save the flag as a user.
    if job_type == AGENT_TRIGGER_JOB_TYPE:
        return FlagEditAuthor.AGENT
    if job_type == SCHEDULED_CHANGE_JOB_TYPE:
        return FlagEditAuthor.SCHEDULED_CHANGE
    # Deleting a user sets the user column to NULL on their rows, so the user column decides only when `is_system`
    # is unset.
    if is_system or (is_system is None and user_id is None):
        return FlagEditAuthor.SYSTEM
    return FlagEditAuthor.PERSON


def _side(row: dict[str, Any], side: str) -> FlagEditSide:
    return FlagEditSide(
        variants=row[f"{side}_variants"],
        groups=row[f"{side}_groups"],
        aggregation=row[f"{side}_aggregation"],
        key=row[f"{side}_{BucketingSetting.KEY}"],
        bucketing_identifier=row[f"{side}_{BucketingSetting.BUCKETING_IDENTIFIER}"],
        experience_continuity=row[f"{side}_{BucketingSetting.EXPERIENCE_CONTINUITY}"],
    )


def _changes_any_field(*fields: str) -> Q:
    query = Q()
    for field in fields:
        query |= Q(detail__contains={"changes": [{"field": field}]})
    return query


def _changed(field: str, path: str, *, function: str = "jsonb_path_query_first") -> Func:
    return Func(
        F("detail"),
        Value(f'$.changes[*] ? (@.field == "{field}").{path}'),
        function=function,
        output_field=JSONField(),
    )
