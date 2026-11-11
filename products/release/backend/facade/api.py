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

from .. import logic
from ..models import Release
from . import contracts

ReleaseNotFoundError = contracts.ReleaseNotFoundError


def _to_dto(obj: Release) -> contracts.ReleaseDTO:
    return contracts.ReleaseDTO(
        id=obj.id,
        name=obj.name,
        description=obj.description,
        owner=contracts.ReleaseOwnerDTO(id=obj.owner.id, first_name=obj.owner.first_name) if obj.owner else None,
        feature_flag_ids=list(obj.feature_flag_ids),
        created_at=obj.created_at,
    )


def list_page(page: PageRequest) -> Page[contracts.ReleaseDTO]:
    return select_page(logic.list_releases(), page).map(_to_dto)


def create(input: contracts.CreateReleaseInput) -> contracts.ReleaseDTO:
    obj = logic.create_release(
        team_id=input.team_id,
        name=input.name,
        description=input.description,
        owner_id=input.owner_id,
        feature_flag_ids=list(input.feature_flag_ids),
    )
    return _to_dto(logic.get_release(obj.id))


def update(release_id: UUID, changes: dict[str, Any]) -> contracts.ReleaseDTO:
    return _to_dto(logic.update_release(release_id, changes))


def delete(release_id: UUID) -> None:
    logic.delete_release(release_id)
