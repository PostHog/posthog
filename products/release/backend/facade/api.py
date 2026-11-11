"""
Facade for release.

The ONLY module other products are allowed to import.
Accept frozen dataclasses, call logic/, return frozen
dataclasses. Never return ORM instances or import DRF.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import UUID

from posthog.paging import Page, PageRequest
from posthog.queryset_paging import select_page

from ..logic import releases as logic
from ..models import Release
from . import contracts

ReleaseNotFoundError = contracts.ReleaseNotFoundError
UnknownFeatureFlagsError = contracts.UnknownFeatureFlagsError


FlagVisibilityLookup = Callable[[list[int]], contracts.FlagVisibility]


def _check_flags(flag_ids: list[int], flag_visibility: FlagVisibilityLookup) -> None:
    unknown = sorted(set(flag_ids) - flag_visibility(flag_ids).linkable)
    if unknown:
        raise contracts.UnknownFeatureFlagsError(unknown)


def _to_dto(obj: Release, hidden: frozenset[int]) -> contracts.ReleaseDTO:
    return contracts.ReleaseDTO(
        id=obj.id,
        name=obj.name,
        description=obj.description,
        owner=contracts.ReleaseOwnerDTO(id=obj.owner.id, first_name=obj.owner.first_name) if obj.owner else None,
        feature_flag_ids=[flag_id for flag_id in obj.feature_flag_ids if flag_id not in hidden],
        created_at=obj.created_at,
    )


def _visible_dto(obj: Release, flag_visibility: FlagVisibilityLookup) -> contracts.ReleaseDTO:
    return _to_dto(obj, flag_visibility(list(obj.feature_flag_ids)).hidden)


def list_page(team_id: int, page: PageRequest, flag_visibility: FlagVisibilityLookup) -> Page[contracts.ReleaseDTO]:
    releases = select_page(logic.list_releases(team_id), page)
    hidden = flag_visibility(sorted({flag_id for obj in releases.results for flag_id in obj.feature_flag_ids})).hidden
    return releases.map(lambda obj: _to_dto(obj, hidden))


def create(input: contracts.CreateReleaseInput, flag_visibility: FlagVisibilityLookup) -> contracts.ReleaseDTO:
    _check_flags(list(input.feature_flag_ids), flag_visibility)
    obj = logic.create_release(
        team_id=input.team_id,
        name=input.name,
        description=input.description,
        owner_id=input.owner_id,
        feature_flag_ids=list(input.feature_flag_ids),
    )
    return _visible_dto(logic.get_release(input.team_id, obj.id), flag_visibility)


def update(
    team_id: int, release_id: UUID, changes: dict[str, Any], flag_visibility: FlagVisibilityLookup
) -> contracts.ReleaseDTO:
    if "feature_flag_ids" in changes:
        linked = list(logic.get_release(team_id, release_id).feature_flag_ids)
        linked_set = set(linked)
        submitted = set(changes["feature_flag_ids"])
        _check_flags(sorted(submitted - linked_set), flag_visibility)
        hidden = flag_visibility(linked).hidden
        kept = [flag_id for flag_id in linked if flag_id in hidden and flag_id not in submitted]
        changes = {**changes, "feature_flag_ids": [*changes["feature_flag_ids"], *kept]}
    return _visible_dto(logic.update_release(team_id, release_id, changes), flag_visibility)


def delete(team_id: int, release_id: UUID) -> None:
    logic.delete_release(team_id, release_id)
