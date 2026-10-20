"""Find active flags whose release conditions target a deleted cohort, and build one in-app notice per team.

The flag evaluator loads only the non-deleted cohorts of the flag's project. A release condition
on any other cohort id fails the flag for every user that the condition is evaluated for. The
flag API rejects these conditions on new writes. This module finds the flags that already hold one.

It checks only the cohorts a flag names directly. A live cohort that includes a deleted cohort also
fails the flag, but cohort saves reject that reference and the cohort delete guard blocks deleting
an included cohort, so no new case can arise.
"""

from collections import defaultdict
from collections.abc import Collection, Iterator, Mapping, Sequence
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any, Literal

from django.db.models import Model, QuerySet

import posthoganalytics

from posthog.dataclasses import frozen
from posthog.models import Team, User
from posthog.scopes import APIScopeObject
from posthog.utils import human_list

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.cohorts.backend.models.cohort import Cohort
from products.feature_flags.backend.facade.config import ConfigFormatError, decode_config
from products.feature_flags.backend.facade.references import references
from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.notifications.backend.facade.api import (
    NotificationData,
    NotificationType,
    RecipientsResolver,
    SourceType,
    TargetType,
)
from products.product_tours.backend.models import ProductTour
from products.surveys.backend.models import Survey

# A fixed key gives each team at most one notice. create_notification returns the existing event on a re-run.
IDEMPOTENCY_KEY = "flags-deleted-cohort-notice"
TITLE_MAX_LENGTH = 255
MAX_LISTED_FLAGS = 5
PAGE_SIZE = 500

OwnerKind = Literal["survey", "product_tour"]


@frozen
class DeletedCohort:
    id: int
    name: str | None
    # True when the id names no cohort in the flag's project. False when the cohort is soft-deleted.
    missing: bool


@frozen
class FlagOwner:
    """The survey or product tour that manages a flag. The flag list hides these flags."""

    kind: OwnerKind
    id: str
    name: str


@frozen
class AffectedFlag:
    flag_id: int
    team_id: int
    key: str
    last_called_at: datetime | None
    cohorts: tuple[DeletedCohort, ...]
    owner: FlagOwner | None


@frozen
class DeliveryPreview:
    notifications_enabled: bool
    # An upper bound, because create_notification also drops recipients who muted this notification type.
    recipient_count: int


@frozen
class _FlagRow:
    id: int
    team_id: int
    project_id: int
    key: str
    filters: Any
    last_called_at: datetime | None


@frozen
class _StoredCohort:
    project_id: int
    deleted: bool
    name: str | None


def find_flags_on_deleted_cohorts(team_ids: Collection[int] | None = None) -> dict[int, list[AffectedFlag]]:
    """Active flags whose release conditions target a deleted or missing cohort, keyed by team id."""
    # The default manager excludes deleted flags. There is no SQL pre-filter on `filters`, because every
    # read of the stored document goes through the config facade, which checks its format first.
    flags = FeatureFlag.objects.filter(active=True)
    if team_ids is not None:
        flags = flags.filter(team_id__in=team_ids)
    affected: dict[int, list[AffectedFlag]] = defaultdict(list)
    for page in _flag_pages(flags):
        for flag in _affected_flags(page):
            affected[flag.team_id].append(flag)
    return dict(affected)


def _flag_pages(flags: QuerySet[FeatureFlag]) -> Iterator[list[_FlagRow]]:
    # The first query returns ids only. Each page then loads its rows by primary key. Production
    # connects through PgBouncer with server-side cursors disabled, so a single query over `filters`
    # would hold every row in memory.
    flag_ids = list(flags.order_by("id").values_list("id", flat=True))
    for start in range(0, len(flag_ids), PAGE_SIZE):
        rows = (
            # nosemgrep: idor-lookup-without-team -- operator-run scan across every team. The ids come from the query above.
            FeatureFlag.objects.filter(pk__in=flag_ids[start : start + PAGE_SIZE])
            .order_by("id")
            .values_list("id", "team_id", "team__project_id", "key", "filters", "last_called_at")
        )
        yield [
            _FlagRow(
                id=flag_id,
                team_id=team_id,
                project_id=project_id,
                key=key,
                filters=filters,
                last_called_at=last_called_at,
            )
            for flag_id, team_id, project_id, key, filters, last_called_at in rows
        ]


def _affected_flags(page: Sequence[_FlagRow]) -> Iterator[AffectedFlag]:
    cohort_ids_by_flag = {row.id: _direct_cohort_ids(row.filters) for row in page}
    stored_cohorts = {
        cohort_id: _StoredCohort(project_id=project_id, deleted=deleted, name=name)
        # nosemgrep: idor-lookup-without-team -- operator-run scan across every team. _deleted_cohort compares each cohort's project with its flag's project.
        for cohort_id, project_id, deleted, name in Cohort.objects.filter(
            pk__in={cohort_id for ids in cohort_ids_by_flag.values() for cohort_id in ids}
        ).values_list("id", "team__project_id", "deleted", "name")
    }
    broken: list[tuple[_FlagRow, tuple[DeletedCohort, ...]]] = []
    for row in page:
        deleted = tuple(
            cohort
            for cohort_id in cohort_ids_by_flag[row.id]
            if (cohort := _deleted_cohort(cohort_id, row.project_id, stored_cohorts)) is not None
        )
        if deleted:
            broken.append((row, deleted))
    owners = _owners([row.id for row, _ in broken])
    for row, deleted in broken:
        yield AffectedFlag(
            flag_id=row.id,
            team_id=row.team_id,
            key=row.key,
            last_called_at=row.last_called_at,
            cohorts=deleted,
            owner=owners.get(row.id),
        )


def _direct_cohort_ids(filters: Any) -> tuple[int, ...]:
    try:
        return references(decode_config(filters)).cohort_ids
    except (ConfigFormatError, AttributeError, TypeError):
        # The evaluator cannot read a malformed document either. That failure is out of scope here.
        return ()


def _deleted_cohort(cohort_id: int, project_id: int, stored: Mapping[int, _StoredCohort]) -> DeletedCohort | None:
    cohort = stored.get(cohort_id)
    if cohort is None or cohort.project_id != project_id:
        return DeletedCohort(id=cohort_id, name=None, missing=True)
    if cohort.deleted:
        return DeletedCohort(id=cohort_id, name=cohort.name, missing=False)
    return None


def _owners(flag_ids: Collection[int]) -> dict[int, FlagOwner]:
    # The same owning relations as `_OWNING_ACCESSORS` in ownership.py, limited to the owners whose
    # flags the flag list hides. A batch query needs the forward field names, not the reverse accessors.
    owners: dict[int, FlagOwner] = {}
    if not flag_ids:
        return owners
    for field in ("targeting_flag_id", "internal_targeting_flag_id", "internal_response_sampling_flag_id"):
        for flag_id, survey_id, name in Survey.objects.filter(**{f"{field}__in": flag_ids}).values_list(
            field, "id", "name"
        ):
            owners[flag_id] = FlagOwner(kind="survey", id=str(survey_id), name=name)
    for flag_id, tour_id, name in ProductTour.all_objects.filter(internal_targeting_flag_id__in=flag_ids).values_list(
        "internal_targeting_flag_id", "id", "name"
    ):
        owners[flag_id] = FlagOwner(kind="product_tour", id=str(tour_id), name=name)
    return owners


class _ViewersOfListedObjects(RecipientsResolver):
    """Narrow team recipients to the members who can view every object the notice names.

    create_notification checks access to the notice's one resource type and ignores per-object
    rules. A notice can name surveys and flags together. A member can be denied one flag.
    This resolver narrows the recipients first. create_notification then applies its own check.
    """

    def __init__(self, flags: Sequence[AffectedFlag]) -> None:
        self._flags = tuple(flags)

    def resolve(self, target_type: TargetType, target_id: str, team_id: int | None) -> list[int]:
        user_ids = super().resolve(target_type, target_id, team_id)
        team = Team.objects.filter(id=team_id).first() if team_id is not None else None
        if not user_ids or team is None:
            return []
        # The body names the survey for a survey's flag, and the flag for a plain or product tour flag.
        survey_ids = [flag.owner.id for flag in self._flags if flag.owner and flag.owner.kind == "survey"]
        flag_ids = [flag.flag_id for flag in self._flags if not (flag.owner and flag.owner.kind == "survey")]
        named: list[Model] = [
            *Survey.objects.filter(team__project_id=team.project_id, id__in=survey_ids),
            *FeatureFlag.objects.filter(team__project_id=team.project_id, id__in=flag_ids),
        ]
        if survey_ids:
            user_ids = self.filter_by_access_control(user_ids, "survey", team)
        if flag_ids:
            user_ids = self.filter_by_access_control(user_ids, "feature_flag", team)
        viewers = []
        for user in User.objects.filter(id__in=user_ids):
            access = UserAccessControl(user, team)
            if access.is_organization_admin or all(
                access.check_access_level_for_object(obj, required_level="viewer") for obj in named
            ):
                viewers.append(user.id)
        return viewers


def build_notice(team_id: int, flags: Sequence[AffectedFlag]) -> NotificationData:
    notice = _single_flag_notice(team_id, flags[0]) if len(flags) == 1 else _several_flags_notice(team_id, flags)
    return replace(notice, resolver=_ViewersOfListedObjects(flags))


def _single_flag_notice(team_id: int, flag: AffectedFlag) -> NotificationData:
    cohorts = _cohorts_phrase(flag.cohorts)
    those = "those cohorts" if len(flag.cohorts) > 1 else "that cohort"
    match flag.owner:
        case FlagOwner(kind="survey", id=survey_id, name=name):
            return _notice(
                team_id,
                title=f"Survey targets a deleted cohort: {name}",
                body=(
                    f"Survey '{name}' targets {cohorts}. Its targeting fails to evaluate until you edit the "
                    f"survey's targeting to remove {those}."
                ),
                resource_type="survey",
                source_type=SourceType.SURVEY,
                source_id=survey_id,
            )
        case FlagOwner(kind="product_tour", id=tour_id, name=name):
            return _notice(
                team_id,
                title=f"Product tour targets a deleted cohort: {name}",
                body=(
                    f"Product tour '{name}' targets {cohorts}. Its targeting fails to evaluate until you edit the "
                    f"tour's targeting to remove {those}."
                ),
                # Product tours are not an access-control resource, so the notice filters recipients on flag access.
                resource_type="feature_flag",
                source_url=f"/product_tours/{tour_id}",
            )
        case _:
            fix = (
                "remove those conditions or choose other cohorts"
                if len(flag.cohorts) > 1
                else "remove that condition or choose another cohort"
            )
            return _notice(
                team_id,
                title=f"Feature flag targets a deleted cohort: {flag.key}",
                body=f"Flag '{flag.key}' targets {cohorts}. The flag fails to evaluate until you {fix}.",
                resource_type="feature_flag",
                resource_id=str(flag.flag_id),
                source_type=SourceType.FEATURE_FLAG,
                source_id=str(flag.flag_id),
            )


def _several_flags_notice(team_id: int, flags: Sequence[AffectedFlag]) -> NotificationData:
    kinds = {flag.owner.kind if flag.owner else None for flag in flags}
    resource_type: APIScopeObject = "feature_flag"
    noun, source_url = "feature flags", "/feature_flags"
    if kinds == {"survey"}:
        noun, source_url, resource_type = "surveys", "/surveys", "survey"
    elif kinds == {"product_tour"}:
        noun, source_url = "product tours", "/product_tours"
    # The most recently evaluated flags matter most to the team, so they come first in the capped list.
    listed = sorted(flags, key=lambda flag: flag.last_called_at or datetime.min.replace(tzinfo=UTC), reverse=True)
    items = [_item_label(flag) for flag in listed[:MAX_LISTED_FLAGS]]
    if len(flags) > MAX_LISTED_FLAGS:
        items.append(f"and {len(flags) - MAX_LISTED_FLAGS} more")
    body = (
        "Each of these targets a deleted cohort and fails to evaluate until you remove that cohort or choose "
        f"another: {', '.join(items)}."
    )
    owner_nouns = [kind.replace("_", " ") for kind in ("survey", "product_tour") if kind in kinds]
    if owner_nouns:
        body += f" Change a {' or '.join(owner_nouns)} in its own targeting settings."
    return _notice(
        team_id,
        title=f"{len(flags)} {noun} target deleted cohorts",
        body=body,
        resource_type=resource_type,
        source_url=source_url,
    )


def _notice(
    team_id: int,
    *,
    title: str,
    body: str,
    resource_type: APIScopeObject,
    resource_id: str = "",
    source_type: SourceType | None = None,
    source_id: str | None = None,
    source_url: str = "",
) -> NotificationData:
    return NotificationData(
        team_id=team_id,
        notification_type=NotificationType.FEATURE_FLAG_FAILURE,
        title=title[:TITLE_MAX_LENGTH],
        body=body,
        target_type=TargetType.TEAM,
        target_id=str(team_id),
        resource_type=resource_type,
        resource_id=resource_id,
        source_type=source_type,
        source_id=source_id,
        source_url=source_url,
        idempotency_key=IDEMPOTENCY_KEY,
    )


def _item_label(flag: AffectedFlag) -> str:
    noun, name = (flag.owner.kind.replace("_", " "), flag.owner.name) if flag.owner else ("flag", flag.key)
    return f"{noun} '{name}' ({_cohort_list(flag.cohorts)})"


def _cohorts_phrase(cohorts: Sequence[DeletedCohort]) -> str:
    if len(cohorts) == 1 and cohorts[0].missing:
        return f"a cohort that no longer exists (ID {cohorts[0].id})"
    return f"the deleted {_cohort_list(cohorts)}"


def _cohort_list(cohorts: Sequence[DeletedCohort]) -> str:
    noun = "cohorts" if len(cohorts) > 1 else "cohort"
    return f"{noun} {human_list([_cohort_label(cohort) for cohort in cohorts])}"


def _cohort_label(cohort: DeletedCohort) -> str:
    return f"'{cohort.name}'" if cohort.name else f"ID {cohort.id}"


def preview_delivery(team: Team, notice: NotificationData) -> DeliveryPreview:
    """Whether create_notification would deliver this notice, and to how many people at most."""
    organization_id = str(team.organization_id)
    # create_notification runs the same check and returns None when the flag is off.
    if not posthoganalytics.feature_enabled(
        "real-time-notifications",
        organization_id,
        groups={"organization": organization_id},
        only_evaluate_locally=False,
        send_feature_flag_events=False,
    ):
        return DeliveryPreview(notifications_enabled=False, recipient_count=0)
    resolver = notice.resolver or RecipientsResolver()
    user_ids = resolver.resolve(notice.target_type, notice.target_id, team.id)
    if notice.resource_type:
        user_ids = resolver.filter_by_access_control(user_ids, str(notice.resource_type), team)
    return DeliveryPreview(notifications_enabled=True, recipient_count=len(user_ids))
