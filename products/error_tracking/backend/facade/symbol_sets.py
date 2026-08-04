"""Facade for error tracking symbol set operations.

Kept separate from ``facade/api.py`` so the object-storage and upload-analytics imports
stay off the django.setup() path of the read-oriented main facade.
"""

from typing import Any

from ..logic import symbol_sets as _logic
from . import contracts

SymbolSetNotFoundError = _logic.SymbolSetNotFoundError


def _to_release(release) -> contracts.ErrorTrackingRelease:
    return contracts.ErrorTrackingRelease(
        id=release.id,
        hash_id=release.hash_id,
        team_id=release.team_id,
        created_at=release.created_at,
        metadata=release.metadata,
        version=release.version,
        project=release.project,
    )


def _to_symbol_set(symbol_set) -> contracts.ErrorTrackingSymbolSet:
    return contracts.ErrorTrackingSymbolSet(
        id=symbol_set.id,
        ref=symbol_set.ref,
        team_id=symbol_set.team_id,
        created_at=symbol_set.created_at,
        last_used=symbol_set.last_used,
        failure_reason=symbol_set.failure_reason,
        has_uploaded_file=bool(symbol_set.storage_ptr),
        release=_to_release(symbol_set.release) if symbol_set.release else None,
    )


def list_symbol_sets(
    team_id: int,
    *,
    ref: str | None,
    search: str | None,
    symbol_set_status: str | None,
    order_by: str | None,
    limit: int | None,
    offset: int,
) -> tuple[list[contracts.ErrorTrackingSymbolSet], int]:
    rows, total = _logic.list_symbol_sets(
        team_id,
        ref=ref,
        search=search,
        symbol_set_status=symbol_set_status,
        order_by=order_by,
        limit=limit,
        offset=offset,
    )
    return [_to_symbol_set(row) for row in rows], total


def get_symbol_set(team_id: int, symbol_set_id: str) -> contracts.ErrorTrackingSymbolSet | None:
    symbol_set = _logic.get_symbol_set(team_id, symbol_set_id)
    return _to_symbol_set(symbol_set) if symbol_set is not None else None


def delete_symbol_set(team_id: int, symbol_set_id: str) -> bool:
    return _logic.delete_symbol_set(team_id, symbol_set_id)


def bulk_delete_symbol_sets(team_id: int, ids: list[str]) -> int:
    return _logic.bulk_delete_symbol_sets(team_id, ids)


def get_download(team_id: int, symbol_set_id: str) -> contracts.ErrorTrackingSymbolSetDownload:
    has_file, url = _logic.get_download_url(team_id, symbol_set_id)
    return contracts.ErrorTrackingSymbolSetDownload(has_file=has_file, url=url)


def create_deprecated_symbol_set(team: Any, chunk_id: str, release_id: str | None, data: bytearray) -> None:
    _logic.create_deprecated_symbol_set(team, chunk_id, release_id, data)


def start_deprecated_upload(team: Any, chunk_id: str, release_id: str | None) -> tuple[object, str]:
    return _logic.start_deprecated_upload(team, chunk_id, release_id)


def finish_upload(team_id: int, symbol_set_id: str, content_hash: str) -> None:
    _logic.finish_upload(team_id, symbol_set_id, content_hash)


def bulk_start_upload(
    team: Any,
    *,
    symbol_sets: list[dict],
    chunk_ids: list[str],
    release_id: str | None,
    force: bool,
    skip_on_conflict: bool,
) -> dict[str, dict[str, str]]:
    return _logic.bulk_start_upload(
        team,
        symbol_sets=symbol_sets,
        chunk_ids=chunk_ids,
        release_id=release_id,
        force=force,
        skip_on_conflict=skip_on_conflict,
    )


def bulk_finish_upload(team: Any, content_hashes: dict[str, str]) -> None:
    _logic.bulk_finish_upload(team, content_hashes)
