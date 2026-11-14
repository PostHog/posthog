"""
Facade for release.

The ONLY module other products are allowed to import.
Accept frozen dataclasses, call logic/, return frozen
dataclasses. Never return ORM instances or import DRF.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TypeVar
from uuid import UUID

from posthog.paging import Page, PageRequest
from posthog.queryset_paging import select_page

from .. import feature_flags
from ..logic import (
    imports,
    releases as logic,
)
from ..models import Release
from . import contracts

ReleaseNotFoundError = contracts.ReleaseNotFoundError
UnknownLinkedObjectsError = contracts.UnknownLinkedObjectsError
ImportFlag = contracts.ImportFlag


RESTRICTED_NAME = "Release of a restricted flag"

T = TypeVar("T")


FlagVisibilityLookup = Callable[[list[int]], contracts.FlagVisibility]
BroadcastVisibilityLookup = Callable[[list[UUID]], contracts.BroadcastVisibility]
SurveyVisibilityLookup = Callable[[list[UUID]], contracts.SurveyVisibility]
InsightVisibilityLookup = Callable[[list[int]], contracts.InsightVisibility]


@dataclass(frozen=True)
class LinkLookups:
    flags: FlagVisibilityLookup
    broadcasts: BroadcastVisibilityLookup
    surveys: SurveyVisibilityLookup
    insights: InsightVisibilityLookup


@dataclass(frozen=True)
class _Hidden:
    flags: frozenset[int]
    broadcasts: frozenset[UUID]
    surveys: frozenset[UUID]
    insights: frozenset[int]
    survey_summaries: dict[UUID, contracts.LinkedSurveyDTO]
    insight_summaries: dict[int, contracts.LinkedInsightDTO]
    summaries: dict[UUID, contracts.LinkedBroadcastDTO]


def _hidden(lookups: LinkLookups, releases: list[Release]) -> _Hidden:
    flag_ids = sorted({flag_id for obj in releases for flag_id in obj.feature_flag_ids})
    broadcast_ids = sorted({broadcast_id for obj in releases for broadcast_id in obj.broadcast_ids}, key=str)
    survey_ids = sorted({survey_id for obj in releases for survey_id in obj.survey_ids}, key=str)
    insight_ids = sorted({insight_id for obj in releases for insight_id in obj.insight_ids})
    broadcasts = lookups.broadcasts(broadcast_ids)
    surveys = lookups.surveys(survey_ids)
    insights = lookups.insights(insight_ids)
    return _Hidden(
        flags=lookups.flags(flag_ids).hidden,
        broadcasts=broadcasts.hidden,
        surveys=frozenset(survey_ids) - surveys.visible,
        survey_summaries={summary.id: summary for summary in surveys.summaries},
        insights=frozenset(insight_ids) - insights.visible,
        insight_summaries={summary.id: summary for summary in insights.summaries},
        summaries={summary.id: summary for summary in broadcasts.summaries},
    )


def _to_dto(obj: Release, hidden: _Hidden) -> contracts.ReleaseDTO:
    has_hidden_flags = any(flag_id in hidden.flags for flag_id in obj.feature_flag_ids)
    return contracts.ReleaseDTO(
        id=obj.id,
        name=RESTRICTED_NAME if obj.auto_named and has_hidden_flags else obj.name,
        description=obj.description,
        owner=contracts.ReleaseOwnerDTO(id=obj.owner.id, first_name=obj.owner.first_name) if obj.owner else None,
        feature_flag_ids=[flag_id for flag_id in obj.feature_flag_ids if flag_id not in hidden.flags],
        has_hidden_flags=has_hidden_flags,
        broadcast_ids=[broadcast_id for broadcast_id in obj.broadcast_ids if broadcast_id not in hidden.broadcasts],
        broadcasts=[
            hidden.summaries[broadcast_id]
            for broadcast_id in obj.broadcast_ids
            if broadcast_id not in hidden.broadcasts and broadcast_id in hidden.summaries
        ],
        survey_ids=[survey_id for survey_id in obj.survey_ids if survey_id not in hidden.surveys],
        surveys=[
            hidden.survey_summaries[survey_id]
            for survey_id in obj.survey_ids
            if survey_id not in hidden.surveys and survey_id in hidden.survey_summaries
        ],
        insight_ids=[insight_id for insight_id in obj.insight_ids if insight_id not in hidden.insights],
        insights=[
            hidden.insight_summaries[insight_id]
            for insight_id in obj.insight_ids
            if insight_id not in hidden.insights and insight_id in hidden.insight_summaries
        ],
        created_at=obj.created_at,
    )


def _visible_dto(obj: Release, lookups: LinkLookups) -> contracts.ReleaseDTO:
    return _to_dto(obj, _hidden(lookups, [obj]))


def _checked(field: str, noun: str, submitted: list[T], linked: list[T], lookup: Callable[[list[T]], Any]) -> list[T]:
    linked_set = set(linked)
    visibility = lookup(sorted(set(submitted) | linked_set, key=str))
    unknown = sorted(
        (
            item
            for item in set(submitted)
            if item in visibility.hidden or (item not in visibility.linkable and item not in linked_set)
        ),
        key=str,
    )
    if unknown:
        raise contracts.UnknownLinkedObjectsError(field, noun, unknown)
    return [*submitted, *(item for item in linked if item in visibility.hidden)]


_LINKED_FIELDS: tuple[tuple[str, str, str], ...] = (
    ("feature_flag_ids", "flags", "flags"),
    ("broadcast_ids", "broadcasts", "broadcasts"),
    ("survey_ids", "surveys", "surveys"),
    ("insight_ids", "insights", "insights"),
)


def list_page(team_id: int, page: PageRequest, lookups: LinkLookups) -> Page[contracts.ReleaseDTO]:
    releases = select_page(logic.list_releases(team_id), page)
    hidden = _hidden(lookups, list(releases.results))
    return releases.map(lambda obj: _to_dto(obj, hidden))


def create(input: contracts.CreateReleaseInput, lookups: LinkLookups) -> contracts.ReleaseDTO:
    checked = {
        field: _checked(field, noun, list(getattr(input, field)), [], getattr(lookups, lookup))
        for field, noun, lookup in _LINKED_FIELDS
    }
    obj = logic.create_release(
        team_id=input.team_id,
        name=input.name,
        description=input.description,
        owner_id=input.owner_id,
        feature_flag_ids=checked["feature_flag_ids"],
        broadcast_ids=checked["broadcast_ids"],
        survey_ids=checked["survey_ids"],
        insight_ids=checked["insight_ids"],
    )
    return _visible_dto(logic.get_release(input.team_id, obj.id), lookups)


def update(team_id: int, release_id: UUID, changes: dict[str, Any], lookups: LinkLookups) -> contracts.ReleaseDTO:
    if {field for field, _, _ in _LINKED_FIELDS} & changes.keys():
        current = logic.get_release(team_id, release_id)
        changes = dict(changes)
        for field, noun, lookup in _LINKED_FIELDS:
            if field in changes:
                changes[field] = _checked(
                    field, noun, list(changes[field]), list(getattr(current, field)), getattr(lookups, lookup)
                )
    return _visible_dto(logic.update_release(team_id, release_id, changes), lookups)


def import_all(team_id: int, load_flags: Callable[[], list[contracts.ImportFlag]]) -> int:
    return imports.run_initial_import(team_id, load_flags)


def project_uses_releases(team_id: int) -> bool:
    return imports.project_imported(team_id)


def create_release_for_new_flag(flag_id: int, team_id: int) -> None:
    imports.create_release_for_new_flag(flag_id, team_id, releases_enabled)


def releases_enabled(
    *,
    team_id: int,
    team_uuid: UUID,
    organization_id: UUID,
    distinct_id: str,
    email: str | None,
    raise_on_error: bool = False,
) -> bool:
    return feature_flags.is_releases_enabled(
        team_id=team_id,
        team_uuid=team_uuid,
        organization_id=organization_id,
        distinct_id=distinct_id,
        email=email,
        raise_on_error=raise_on_error,
    )


def delete(team_id: int, release_id: UUID) -> None:
    logic.delete_release(team_id, release_id)
