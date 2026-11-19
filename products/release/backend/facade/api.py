"""
Facade for release.

The ONLY module other products are allowed to import.
Accept frozen dataclasses, call logic/, return frozen
dataclasses. Never return ORM instances or import DRF.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, TypeVar
from uuid import UUID

from posthog.models.scoping import team_scope
from posthog.paging import Page, PageRequest
from posthog.queryset_paging import select_page

from .. import feature_flags
from ..logic import (
    imports,
    releases as logic,
    suggestions,
)
from ..models import Release
from . import contracts

if TYPE_CHECKING:
    from _typeshed import SupportsRichComparison

FlagNotFoundError = contracts.FlagNotFoundError
ReleaseNotFoundError = contracts.ReleaseNotFoundError
UnknownLinkedObjectsError = contracts.UnknownLinkedObjectsError
TooManyMetricsError = contracts.TooManyMetricsError
InvalidMergeError = contracts.InvalidMergeError
ImportFlag = contracts.ImportFlag


RESTRICTED_NAME = "Release of a restricted flag"

T = TypeVar("T", bound="SupportsRichComparison")


FlagVisibilityLookup = Callable[[list[int]], contracts.FlagVisibility]
BroadcastVisibilityLookup = Callable[[list[UUID]], contracts.BroadcastVisibility]
SurveyVisibilityLookup = Callable[[list[UUID]], contracts.SurveyVisibility]
InsightVisibilityLookup = Callable[[list[int]], contracts.InsightVisibility]
FlagLabelLookup = Callable[[list[int]], dict[int, contracts.FlagLabel]]
FlagSearchLookup = Callable[[list[str]], list[int]]


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
    insight_ids = sorted({insight_id for obj in releases for insight_id in [*obj.insight_ids, *obj.metric_insight_ids]})
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


def _shows_restricted_name(release: Release, hidden_flags: frozenset[int]) -> bool:
    return release.auto_named and not hidden_flags.isdisjoint(release.feature_flag_ids)


def _to_dto(obj: Release, hidden: _Hidden) -> contracts.ReleaseDTO:
    metric_insight_ids = [insight_id for insight_id in obj.metric_insight_ids if insight_id not in hidden.insights]
    has_hidden_flags = any(flag_id in hidden.flags for flag_id in obj.feature_flag_ids)
    return contracts.ReleaseDTO(
        id=obj.id,
        name=RESTRICTED_NAME if _shows_restricted_name(obj, hidden.flags) else obj.name,
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
        metric_insight_ids=metric_insight_ids,
        metric_goals=[
            contracts.MetricGoalDTO(**goal) for goal in obj.metric_goals if goal["insight_id"] in metric_insight_ids
        ],
        created_at=obj.created_at,
    )


def _visible_dto(obj: Release, lookups: LinkLookups) -> contracts.ReleaseDTO:
    return _to_dto(obj, _hidden(lookups, [obj]))


def _checked(field: str, noun: str, submitted: list[T], linked: list[T], lookup: Callable[[list[T]], Any]) -> list[T]:
    linked_set = set(linked)
    visibility = lookup(sorted(set(submitted) | linked_set, key=str))
    unknown = sorted(
        item
        for item in set(submitted)
        if item in visibility.hidden or (item not in visibility.linkable and item not in linked_set)
    )
    if unknown:
        raise contracts.UnknownLinkedObjectsError(field, noun, unknown)
    return [*submitted, *(item for item in linked if item in visibility.hidden)]


def _goal(goal: contracts.MetricGoalDTO | dict[str, Any]) -> dict[str, Any]:
    if isinstance(goal, contracts.MetricGoalDTO):
        goal = {"insight_id": goal.insight_id, "direction": goal.direction, "value": goal.value}
    return {"insight_id": goal["insight_id"], "direction": str(goal["direction"]), "value": goal["value"]}


def _checked_goals(
    submitted: list[Any], metric_ids: list[int], lookup: InsightVisibilityLookup
) -> tuple[list[dict[str, Any]], frozenset[int]]:
    hidden = lookup(sorted(set(metric_ids))).hidden
    goals = [_goal(goal) for goal in submitted]
    unknown = sorted(
        {goal["insight_id"] for goal in goals if goal["insight_id"] not in metric_ids or goal["insight_id"] in hidden}
    )
    if unknown:
        raise contracts.UnknownLinkedObjectsError("metric_goals", "metrics", unknown)
    return goals, frozenset(hidden)


_LINKED_FIELDS: tuple[tuple[str, str], ...] = (
    ("feature_flag_ids", "flags"),
    ("broadcast_ids", "broadcasts"),
    ("survey_ids", "surveys"),
    ("insight_ids", "insights"),
    ("metric_insight_ids", "insights"),
)


def get(team_id: int, release_id: UUID, lookups: LinkLookups) -> contracts.ReleaseDTO:
    return _visible_dto(logic.get_release(team_id, release_id), lookups)


def list_page(team_id: int, page: PageRequest, lookups: LinkLookups) -> Page[contracts.ReleaseDTO]:
    releases = select_page(logic.list_releases(team_id), page)
    hidden = _hidden(lookups, list(releases.results))
    return releases.map(lambda obj: _to_dto(obj, hidden))


CATALOG_SCAN_BATCH = 200


class InvalidCatalogCursorError(Exception):
    pass


def _parse_cursor(cursor: str) -> tuple[datetime, UUID]:
    created_at, _, release_id = cursor.partition("|")
    try:
        return datetime.fromisoformat(created_at), UUID(release_id)
    except ValueError:
        raise InvalidCatalogCursorError(cursor)


def list_catalog_page(
    team_id: int,
    flags: FlagVisibilityLookup,
    *,
    search: str,
    limit: int,
    cursor: str,
    owner_ids: list[int] | None = None,
    oldest_first: bool = False,
    feature_flag_id: int | None = None,
) -> tuple[list[contracts.CatalogReleaseDTO], str | None]:
    if feature_flag_id is not None and feature_flag_id not in flags([feature_flag_id]).visible:
        return [], None
    releases = logic.list_catalog_releases(
        team_id,
        search,
        _parse_cursor(cursor) if cursor else None,
        owner_ids=owner_ids,
        oldest_first=oldest_first,
        feature_flag_id=feature_flag_id,
    )
    results: list[contracts.CatalogReleaseDTO] = []
    position = 0
    while True:
        size = CATALOG_SCAN_BATCH if search else limit + 1
        batch = list(releases[position : position + size])
        position += len(batch)
        hidden = flags(sorted({flag_id for obj in batch if obj.auto_named for flag_id in obj.feature_flag_ids})).hidden
        for obj in batch:
            restricted = _shows_restricted_name(obj, hidden)
            if restricted and search:
                continue
            if len(results) == limit:
                last = results[-1]
                return results, f"{last.created_at.isoformat()}|{last.id}"
            results.append(
                contracts.CatalogReleaseDTO(
                    id=obj.id,
                    name=RESTRICTED_NAME if restricted else obj.name,
                    created_at=obj.created_at,
                    owner=contracts.CatalogOwnerDTO(
                        id=obj.owner.id,
                        uuid=obj.owner.uuid,
                        first_name=obj.owner.first_name,
                        last_name=obj.owner.last_name,
                        email=obj.owner.email,
                    )
                    if obj.owner
                    else None,
                )
            )
        if len(batch) < size:
            return results, None


SUGGESTION_LIMIT = 5
SUGGESTION_CANDIDATES = 300
SUGGESTION_FLAG_MATCHES = 500


def releases_for_flag(
    team_id: int,
    flag_id: int,
    flags: FlagVisibilityLookup,
    labels: FlagLabelLookup,
    search_flags: FlagSearchLookup,
    gets_own_release: Callable[[int], bool],
) -> contracts.FlagReleasesDTO:
    label = labels([flag_id]).get(flag_id)
    if label is None or flag_id not in flags([flag_id]).visible:
        raise contracts.FlagNotFoundError(flag_id)
    words = suggestions.search_terms(label.key, label.name)
    current = suggestions.releases_with_flag(team_id, flag_id)
    candidates: list[Release] = []
    if words:
        matching = search_flags(sorted(words))
        matching_visible = sorted(set(matching) & flags(matching).visible) if matching else []
        candidates = suggestions.candidate_releases(team_id, flag_id, words, matching_visible, SUGGESTION_CANDIDATES)
    linked = sorted({linked_id for release in [*current, *candidates] for linked_id in release.feature_flag_ids})
    hidden = flags(linked).hidden if linked else frozenset()
    linked_terms = {
        linked_id: suggestions.terms(label.key, label.name)
        for linked_id, label in labels([linked_id for linked_id in linked if linked_id not in hidden]).items()
    }
    ranked = suggestions.rank(
        [release for release in candidates if not _shows_restricted_name(release, hidden)], words, linked_terms
    )
    return contracts.FlagReleasesDTO(
        feature_flag_id=flag_id,
        auto_release=not current and imports.project_imported(team_id) and gets_own_release(flag_id),
        current=[
            contracts.ReleaseRefDTO(
                id=release.id, name=RESTRICTED_NAME if _shows_restricted_name(release, hidden) else release.name
            )
            for release in current
        ],
        suggestions=[
            contracts.ReleaseSuggestionDTO(id=release.id, name=release.name, matched_terms=matched)
            for release, matched in ranked[:SUGGESTION_LIMIT]
        ],
    )


def create(input: contracts.CreateReleaseInput, lookups: LinkLookups) -> contracts.ReleaseDTO:
    checked = {
        field: _checked(field, noun, list(getattr(input, field)), [], getattr(lookups, noun))
        for field, noun in _LINKED_FIELDS
    }
    obj = logic.create_release(
        team_id=input.team_id,
        name=input.name,
        description=input.description,
        owner_id=input.owner_id,
        metric_goals=_checked_goals(list(input.metric_goals), checked["metric_insight_ids"], lookups.insights)[0],
        **checked,
    )
    return _visible_dto(logic.get_release(input.team_id, obj.id), lookups)


def update(team_id: int, release_id: UUID, changes: dict[str, Any], lookups: LinkLookups) -> contracts.ReleaseDTO:
    if {"metric_goals", *(field for field, _ in _LINKED_FIELDS)} & changes.keys():
        current = logic.get_release(team_id, release_id)
        changes = dict(changes)
        for field, noun in _LINKED_FIELDS:
            if field in changes:
                changes[field] = _checked(
                    field, noun, list(changes[field]), list(getattr(current, field)), getattr(lookups, noun)
                )
        if len(changes.get("metric_insight_ids", [])) > contracts.MAX_METRICS:
            raise contracts.TooManyMetricsError()
        if "metric_goals" in changes:
            changes["metric_goals"], hidden_goals = _checked_goals(
                list(changes["metric_goals"]),
                list(changes.get("metric_insight_ids", current.metric_insight_ids)),
                lookups.insights,
            )
            return _visible_dto(logic.update_release(team_id, release_id, changes, hidden_goals), lookups)
    return _visible_dto(logic.update_release(team_id, release_id, changes), lookups)


def merge(
    team_id: int, target_id: UUID, source_ids: list[UUID], lookups: LinkLookups, name: str | None = None
) -> contracts.ReleaseDTO:
    sources = [release_id for release_id in dict.fromkeys(source_ids) if release_id != target_id]
    if not sources:
        raise contracts.InvalidMergeError("Pick at least one other release to merge into this one.")

    def no_hidden_flags(releases: list[Release]) -> None:
        flag_ids = sorted({flag_id for release in releases for flag_id in release.feature_flag_ids})
        if flag_ids and lookups.flags(flag_ids).hidden:
            raise contracts.InvalidMergeError("These releases link flags you cannot see, so they cannot be merged.")

    return _visible_dto(logic.merge_releases(team_id, target_id, sources, name, no_hidden_flags), lookups)


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
    only_evaluate_locally: bool = False,
    for_area: bool = False,
) -> bool:
    return feature_flags.is_releases_enabled(
        team_id=team_id,
        team_uuid=team_uuid,
        organization_id=organization_id,
        distinct_id=distinct_id,
        email=email,
        raise_on_error=raise_on_error,
        only_evaluate_locally=only_evaluate_locally,
        flag_key=feature_flags.RELEASES_AREA_FLAG if for_area else feature_flags.RELEASE_OBJECTS_FLAG,
    )


def get_summary(team_id: int, release_id: UUID) -> contracts.ReleaseSummary:
    root_id = imports.root_team_id(team_id)
    with team_scope(root_id):
        release = logic.get_release(root_id, release_id)
    return contracts.ReleaseSummary(
        id=release.id,
        name=release.name,
        description=release.description,
        auto_named=release.auto_named,
        owner_first_name=release.owner.first_name if release.owner else None,
        feature_flag_ids=list(release.feature_flag_ids),
        updated_at=release.updated_at,
    )


def delete(team_id: int, release_id: UUID) -> None:
    logic.delete_release(team_id, release_id)
