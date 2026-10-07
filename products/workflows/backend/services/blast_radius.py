"""Batch audience sizing and paging: the preview counts the editor shows, and the pages the Node
batch resolver walks when it sends."""

from posthog.models.property import GroupTypeIndex
from posthog.models.team.team import Team

from products.feature_flags.backend.person_sampling import bounded_memory_settings
from products.feature_flags.backend.user_blast_radius import BlastRadiusResult, get_user_blast_radius
from products.workflows.backend.facade.contracts import AudiencePage, AudienceSize
from products.workflows.backend.services.account_audience import (
    ACCOUNT_BATCH_SIZE,
    get_account_audience_count,
    get_account_audience_page,
    get_account_group_type_name as _get_account_group_type_name,
)
from products.workflows.backend.services.audience_v2 import (
    get_dedupe_audience_count_v2,
    get_person_audience_count_v2,
    use_audience_query_v2,
)
from products.workflows.backend.services.batch_audience import (
    audience_page_size,
    get_batch_audience_count,
    get_batch_audience_person_ids,
)
from products.workflows.backend.utils.batch_trigger_limit import get_hogflow_batch_trigger_limit


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
    # sends (unique emails + email-less persons), not the number of matching persons -
    # the legacy person-count query is skipped entirely, "total" comes straight from
    # the cached team-wide count it would have returned anyway. The applied key is
    # echoed back so the frontend labels the count from the response instead of
    # guessing whether the dedup actually ran.
    applied_dedupe_key = None
    audience_v2 = group_type_index is None and use_audience_query_v2(team)
    if dedupe_key is not None and group_type_index is None:
        if audience_v2:
            blast_radius = get_dedupe_audience_count_v2(team, filters, dedupe_key)
        else:
            total = team.persons_seen_so_far
            affected = min(get_batch_audience_count(team, filters, dedupe_key), total)
            blast_radius = BlastRadiusResult(affected=affected, total=total)
        applied_dedupe_key = dedupe_key
    elif audience_v2:
        blast_radius = get_person_audience_count_v2(team, filters)
    else:
        blast_radius = get_user_blast_radius(team, filters, group_type_index)

    return AudienceSize(
        affected=blast_radius.affected,
        total=blast_radius.total,
        limit=get_hogflow_batch_trigger_limit(team_id, sends_email=sends_email),
        dedupe_key=applied_dedupe_key,
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
    enumeration_settings = (
        bounded_memory_settings() if group_type_index is None and use_audience_query_v2(team) else None
    )
    ids = get_batch_audience_person_ids(
        team, filters, group_type_index, cursor, dedupe_key=dedupe_key, settings=enumeration_settings
    )
    return AudiencePage(ids=ids, has_more=len(ids) == audience_page_size(group_type_index))


def get_account_audience_ids_page(*, team_id: int, filters: dict, cursor: str | None) -> AudiencePage:
    ids = get_account_audience_page(Team.objects.get(id=team_id), filters, cursor)
    return AudiencePage(ids=ids, has_more=len(ids) == ACCOUNT_BATCH_SIZE)


def get_account_group_type_name(team_id: int) -> str | None:
    return _get_account_group_type_name(Team.objects.get(id=team_id))
