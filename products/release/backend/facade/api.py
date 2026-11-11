"""
Facade for release.

The ONLY module other products are allowed to import.
Accept frozen dataclasses, call logic/, return frozen
dataclasses. Never return ORM instances or import DRF.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from .. import logic
from ..models import Release
from . import contracts


def _to_dto(obj: Release) -> contracts.ReleaseDTO:
    return contracts.ReleaseDTO(
        id=obj.id,
        name=obj.name,
        description=obj.description,
        owner=contracts.ReleaseOwnerDTO(id=obj.owner.id, first_name=obj.owner.first_name) if obj.owner else None,
        feature_flag_ids=list(obj.feature_flag_ids),
        created_at=obj.created_at,
    )


def list_all() -> list[contracts.ReleaseDTO]:
    return [_to_dto(obj) for obj in logic.list_releases()]


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
