"""Batch audience sizing and paging: the preview counts the editor shows, and the pages the Node
batch resolver walks when it sends."""

from django.conf import settings
from django.core.cache import cache

from posthog.models.property import GroupTypeIndex
from posthog.models.team.team import Team

from products.feature_flags.backend.person_sampling import bounded_memory_settings
from products.feature_flags.backend.user_blast_radius import get_user_blast_radius
from products.workflows.backend.facade.contracts import AudiencePage, AudienceSize, RealtimeAudienceCohort
from products.workflows.backend.services.account_audience import (
    ACCOUNT_BATCH_SIZE,
    get_account_audience_count,
    get_account_audience_page,
    get_account_group_type_name as _get_account_group_type_name,
)
from products.workflows.backend.services.audience_v2 import get_dedupe_audience_count_v2, get_person_audience_count_v2
from products.workflows.backend.services.batch_audience import audience_page_size, get_batch_audience_person_ids
from products.workflows.backend.services.batch_audience_cohorts import (
    find_realtime_behavioral_cohort,
    realtime_audience_cohort,
    realtime_cohort_can_finish,
    realtime_cohort_is_ready,
    realtime_cohort_status,
)
from products.workflows.backend.utils.batch_trigger_limit import get_hogflow_batch_trigger_limit

# An open send screen re-sizes a realtime cohort audience every few seconds while the cohort calculates. The
# project's person total only gives the count context, so it is counted once per window, not on every check.
REALTIME_AUDIENCE_TOTAL_CACHE_SECONDS = 600


def _realtime_audience_total(team: Team) -> int:
    cache_key = f"workflows:realtime_audience_person_total:{team.pk}"
    total = cache.get(cache_key)
    if not isinstance(total, int):
        total = get_person_audience_count_v2(team, {"properties": []}).total
        cache.set(cache_key, total, REALTIME_AUDIENCE_TOTAL_CACHE_SECONDS)
    return total


def _top_level_cohort_ids(filters: dict) -> list[int | str]:
    """Cohort ids of the audience's top-level conditions, the only ones the pickers can show and clear."""
    properties = filters.get("properties")
    if not isinstance(properties, list):
        return []
    return [
        condition["value"]
        for condition in properties
        if isinstance(condition, dict)
        and condition.get("type") == "cohort"
        and isinstance(condition.get("value"), int | str)
    ]


def get_audience_size(
    *,
    team_id: int,
    filters: dict,
    group_type_index: GroupTypeIndex | None,
    dedupe_key: str | None,
    sends_email: bool,
) -> AudienceSize:
    team = Team.objects.get(id=team_id)
    # Preview matches the actual send: with dedup active, "affected" is the number of
    # sends (unique emails + email-less persons), not the number of matching persons.
    # The applied key is echoed back so the frontend labels the count from the response
    # instead of guessing whether the dedup actually ran.
    applied_dedupe_key = None
    realtime_cohort = realtime_audience_cohort(team.project_id, filters) if group_type_index is None else None
    if realtime_cohort is not None:
        # The send reads the realtime pipeline's Postgres table, which this process can't query. The
        # cohort's count from its periodic calculation stands in as an estimate, and the send skips the
        # email dedupe.
        return AudienceSize(
            affected=realtime_cohort.count or 0,
            total=_realtime_audience_total(team),
            limit=get_hogflow_batch_trigger_limit(team_id, sends_email=sends_email),
            dedupe_key=None,
            realtime_cohort=realtime_cohort_status(realtime_cohort),
        )
    if group_type_index is not None:
        blast_radius = get_user_blast_radius(team, filters, group_type_index)
    elif dedupe_key is not None:
        blast_radius = get_dedupe_audience_count_v2(team, filters, dedupe_key)
        applied_dedupe_key = dedupe_key
    else:
        blast_radius = get_person_audience_count_v2(team, filters)

    mixed_realtime_cohort = (
        find_realtime_behavioral_cohort(team.project_id, _top_level_cohort_ids(filters))
        if group_type_index is None
        else None
    )
    return AudienceSize(
        affected=blast_radius.affected,
        total=blast_radius.total,
        limit=get_hogflow_batch_trigger_limit(team_id, sends_email=sends_email),
        dedupe_key=applied_dedupe_key,
        realtime_cohort_with_other_conditions=(
            RealtimeAudienceCohort(
                id=mixed_realtime_cohort.pk,
                name=str(mixed_realtime_cohort.name),
                ready=realtime_cohort_is_ready(mixed_realtime_cohort),
                can_finish=realtime_cohort_can_finish(mixed_realtime_cohort),
            )
            if mixed_realtime_cohort is not None
            else None
        ),
    )


def get_account_audience_size(*, team_id: int, filters: dict, sends_email: bool) -> AudienceSize:
    team = Team.objects.get(id=team_id)
    return AudienceSize(
        affected=get_account_audience_count(team, filters),
        total=get_account_audience_count(team, {"audience_type": "accounts"}),
        limit=get_hogflow_batch_trigger_limit(team_id, sends_email=sends_email),
        dedupe_key=None,
    )


def get_audience_person_page(
    *,
    team_id: int,
    filters: dict,
    group_type_index: GroupTypeIndex | None,
    cursor: str | None,
    dedupe_key: str | None,
) -> AudiencePage:
    team = Team.objects.get(id=team_id)
    enumeration_settings = None
    if group_type_index is None:
        enumeration_settings = bounded_memory_settings()
        enumeration_settings.max_execution_time = settings.WORKFLOWS_BATCH_AUDIENCE_QUERY_TIMEOUT_SECONDS
    ids = get_batch_audience_person_ids(
        team, filters, group_type_index, cursor, dedupe_key=dedupe_key, settings=enumeration_settings
    )
    return AudiencePage(ids=ids, has_more=len(ids) == audience_page_size(group_type_index))


def get_account_audience_ids_page(*, team_id: int, filters: dict, cursor: str | None) -> AudiencePage:
    ids = get_account_audience_page(Team.objects.get(id=team_id), filters, cursor)
    return AudiencePage(ids=ids, has_more=len(ids) == ACCOUNT_BATCH_SIZE)


def get_account_group_type_name(team_id: int) -> str | None:
    return _get_account_group_type_name(Team.objects.get(id=team_id))
