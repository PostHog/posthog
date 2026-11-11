"""
Facade for release.

The ONLY module other products are allowed to import.
Accept frozen dataclasses, call logic/, return frozen
dataclasses. Never return ORM instances or import DRF.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from posthog.paging import Page, PageRequest
from posthog.queryset_paging import select_page

from .. import feature_flags
from ..logic import releases as logic
from ..models import Release
from . import contracts

ReleaseNotFoundError = contracts.ReleaseNotFoundError
UnknownFeatureFlagsError = contracts.UnknownFeatureFlagsError
UnknownBroadcastsError = contracts.UnknownBroadcastsError


FlagVisibilityLookup = Callable[[list[int]], contracts.FlagVisibility]
BroadcastVisibilityLookup = Callable[[list[UUID]], contracts.BroadcastVisibility]


@dataclass(frozen=True)
class LinkLookups:
    flags: FlagVisibilityLookup
    broadcasts: BroadcastVisibilityLookup


@dataclass(frozen=True)
class _Hidden:
    flags: frozenset[int]
    broadcasts: frozenset[UUID]
    summaries: dict[UUID, contracts.LinkedBroadcastDTO]


def _hidden(lookups: LinkLookups, releases: list[Release]) -> _Hidden:
    flag_ids = sorted({flag_id for obj in releases for flag_id in obj.feature_flag_ids})
    broadcast_ids = sorted({broadcast_id for obj in releases for broadcast_id in obj.broadcast_ids}, key=str)
    broadcasts = lookups.broadcasts(broadcast_ids)
    return _Hidden(
        flags=lookups.flags(flag_ids).hidden,
        broadcasts=broadcasts.hidden,
        summaries={summary.id: summary for summary in broadcasts.summaries},
    )


def _to_dto(obj: Release, hidden: _Hidden) -> contracts.ReleaseDTO:
    return contracts.ReleaseDTO(
        id=obj.id,
        name=obj.name,
        description=obj.description,
        owner=contracts.ReleaseOwnerDTO(id=obj.owner.id, first_name=obj.owner.first_name) if obj.owner else None,
        feature_flag_ids=[flag_id for flag_id in obj.feature_flag_ids if flag_id not in hidden.flags],
        has_hidden_flags=any(flag_id in hidden.flags for flag_id in obj.feature_flag_ids),
        broadcast_ids=[broadcast_id for broadcast_id in obj.broadcast_ids if broadcast_id not in hidden.broadcasts],
        broadcasts=[
            hidden.summaries[broadcast_id]
            for broadcast_id in obj.broadcast_ids
            if broadcast_id not in hidden.broadcasts and broadcast_id in hidden.summaries
        ],
        created_at=obj.created_at,
    )


def _visible_dto(obj: Release, lookups: LinkLookups) -> contracts.ReleaseDTO:
    return _to_dto(obj, _hidden(lookups, [obj]))


def _checked_flags(submitted: list[int], linked: list[int], lookup: FlagVisibilityLookup) -> list[int]:
    linked_set = set(linked)
    visibility = lookup(sorted(set(submitted) | linked_set))
    unknown = sorted(
        flag_id
        for flag_id in set(submitted)
        if flag_id in visibility.hidden or (flag_id not in visibility.linkable and flag_id not in linked_set)
    )
    if unknown:
        raise contracts.UnknownFeatureFlagsError(unknown)
    return [*submitted, *(flag_id for flag_id in linked if flag_id in visibility.hidden)]


def _checked_broadcasts(submitted: list[UUID], linked: list[UUID], lookup: BroadcastVisibilityLookup) -> list[UUID]:
    linked_set = set(linked)
    visibility = lookup(sorted(set(submitted) | linked_set, key=str))
    unknown = sorted(
        (
            broadcast_id
            for broadcast_id in set(submitted)
            if broadcast_id in visibility.hidden
            or (broadcast_id not in visibility.linkable and broadcast_id not in linked_set)
        ),
        key=str,
    )
    if unknown:
        raise contracts.UnknownBroadcastsError(unknown)
    return [*submitted, *(broadcast_id for broadcast_id in linked if broadcast_id in visibility.hidden)]


def list_page(team_id: int, page: PageRequest, lookups: LinkLookups) -> Page[contracts.ReleaseDTO]:
    releases = select_page(logic.list_releases(team_id), page)
    hidden = _hidden(lookups, list(releases.results))
    return releases.map(lambda obj: _to_dto(obj, hidden))


def create(input: contracts.CreateReleaseInput, lookups: LinkLookups) -> contracts.ReleaseDTO:
    feature_flag_ids = _checked_flags(list(input.feature_flag_ids), [], lookups.flags)
    broadcast_ids = _checked_broadcasts(list(input.broadcast_ids), [], lookups.broadcasts)
    obj = logic.create_release(
        team_id=input.team_id,
        name=input.name,
        description=input.description,
        owner_id=input.owner_id,
        feature_flag_ids=feature_flag_ids,
        broadcast_ids=broadcast_ids,
    )
    return _visible_dto(logic.get_release(input.team_id, obj.id), lookups)


def update(team_id: int, release_id: UUID, changes: dict[str, Any], lookups: LinkLookups) -> contracts.ReleaseDTO:
    if "feature_flag_ids" in changes or "broadcast_ids" in changes:
        current = logic.get_release(team_id, release_id)
        changes = dict(changes)
        if "feature_flag_ids" in changes:
            changes["feature_flag_ids"] = _checked_flags(
                list(changes["feature_flag_ids"]), list(current.feature_flag_ids), lookups.flags
            )
        if "broadcast_ids" in changes:
            changes["broadcast_ids"] = _checked_broadcasts(
                list(changes["broadcast_ids"]), list(current.broadcast_ids), lookups.broadcasts
            )
    return _visible_dto(logic.update_release(team_id, release_id, changes), lookups)


def releases_enabled(
    *, team_id: int, team_uuid: UUID, organization_id: UUID, distinct_id: str, email: str | None
) -> bool:
    return feature_flags.is_releases_enabled(
        team_id=team_id, team_uuid=team_uuid, organization_id=organization_id, distinct_id=distinct_id, email=email
    )


def delete(team_id: int, release_id: UUID) -> None:
    logic.delete_release(team_id, release_id)
