"""
Facade for release.

The ONLY module other products are allowed to import.
Accept frozen dataclasses, call logic/, return frozen
dataclasses. Never return ORM instances or import DRF.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from posthog.paging import Page, PageRequest
from posthog.queryset_paging import select_page

from products.feature_flags.backend.facade.api import existing_flag_ids

from .. import logic
from ..models import Release
from . import contracts

ReleaseNotFoundError = contracts.ReleaseNotFoundError
UnknownFeatureFlagsError = contracts.UnknownFeatureFlagsError


def _check_flags(team_id: int, flag_ids: list[int]) -> None:
    unknown = sorted(set(flag_ids) - existing_flag_ids(flag_ids, team_id=team_id))
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


def create(input: contracts.CreateReleaseInput) -> contracts.ReleaseDTO:
    _check_flags(input.team_id, list(input.feature_flag_ids))
    obj = logic.create_release(
        team_id=input.team_id,
        name=input.name,
        description=input.description,
        owner_id=input.owner_id,
        feature_flag_ids=list(input.feature_flag_ids),
    )
    return _to_dto(logic.get_release(input.team_id, obj.id))


def update(team_id: int, release_id: UUID, changes: dict[str, Any]) -> contracts.ReleaseDTO:
    if "feature_flag_ids" in changes:
        linked = set(logic.get_release(team_id, release_id).feature_flag_ids)
        _check_flags(team_id, [flag_id for flag_id in changes["feature_flag_ids"] if flag_id not in linked])
    return _to_dto(logic.update_release(team_id, release_id, changes))


def delete(team_id: int, release_id: UUID) -> None:
    logic.delete_release(team_id, release_id)
