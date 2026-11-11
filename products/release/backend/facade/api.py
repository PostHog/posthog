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


VisibleFlagIds = Callable[[list[int]], set[int]]


def _check_flags(flag_ids: list[int], visible_flag_ids: VisibleFlagIds) -> None:
    unknown = sorted(set(flag_ids) - visible_flag_ids(flag_ids))
    if unknown:
        raise contracts.UnknownFeatureFlagsError(unknown)


def _to_dto(obj: Release) -> contracts.ReleaseDTO:
    return contracts.ReleaseDTO(
        id=obj.id,
        name=obj.name,
        description=obj.description,
        owner=contracts.ReleaseOwnerDTO(id=obj.owner.id, first_name=obj.owner.first_name) if obj.owner else None,
        feature_flag_ids=list(obj.feature_flag_ids),
        created_at=obj.created_at,
    )


def list_page(team_id: int, page: PageRequest) -> Page[contracts.ReleaseDTO]:
    return select_page(logic.list_releases(team_id), page).map(_to_dto)


def create(input: contracts.CreateReleaseInput, visible_flag_ids: VisibleFlagIds) -> contracts.ReleaseDTO:
    _check_flags(list(input.feature_flag_ids), visible_flag_ids)
    obj = logic.create_release(
        team_id=input.team_id,
        name=input.name,
        description=input.description,
        owner_id=input.owner_id,
        feature_flag_ids=list(input.feature_flag_ids),
    )
    return _to_dto(logic.get_release(input.team_id, obj.id))


def update(
    team_id: int, release_id: UUID, changes: dict[str, Any], visible_flag_ids: VisibleFlagIds
) -> contracts.ReleaseDTO:
    if "feature_flag_ids" in changes:
        linked = set(logic.get_release(team_id, release_id).feature_flag_ids)
        _check_flags([flag_id for flag_id in changes["feature_flag_ids"] if flag_id not in linked], visible_flag_ids)
    return _to_dto(logic.update_release(team_id, release_id, changes))


def delete(team_id: int, release_id: UUID) -> None:
    logic.delete_release(team_id, release_id)
