from __future__ import annotations

import re
from collections.abc import Callable

from django.db import connection, transaction

from posthog.models import Team, User
from posthog.models.scoping import team_scope

from products.feature_flags.backend.facade.release_candidates import list_release_import_flags, release_flag_creator_id

from ..facade.contracts import ImportFlag
from ..models import Release, ReleaseAutoLinkedFlag, ReleaseImportState

MAX_NAME_LENGTH = 255

_SEPARATORS = re.compile(r"[-_.:/\s]+")


def linked_flag_ids(team_id: int, flag_ids: list[int] | None = None) -> set[int]:
    releases = Release.objects.filter(team_id=team_id)
    if flag_ids is not None:
        releases = releases.filter(feature_flag_ids__overlap=flag_ids)
    return {
        flag_id
        for linked in releases.values_list("feature_flag_ids", flat=True)
        for flag_id in linked
        if flag_ids is None or flag_id in flag_ids
    }


def root_team_id(team_id: int) -> int:
    parent_id = Team.objects.filter(id=team_id).values_list("parent_team_id", flat=True).first()
    return parent_id or team_id


def _lock_team(team_id: int) -> None:
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", [f"release-import:{team_id}"])


def _insert_unlinked(team_id: int, releases: list[tuple[str, list[int]]]) -> list[Release]:
    requested = sorted({flag_id for _, flag_ids in releases for flag_id in flag_ids})
    linked = linked_flag_ids(team_id, requested) | set(
        ReleaseAutoLinkedFlag.objects.filter(team_id=team_id, feature_flag_id__in=requested).values_list(
            "feature_flag_id", flat=True
        )
    )
    rows: list[Release] = []
    for name, flag_ids in releases:
        unlinked = [flag_id for flag_id in dict.fromkeys(flag_ids) if flag_id not in linked]
        if unlinked:
            rows.append(Release(team_id=team_id, name=name, feature_flag_ids=unlinked, auto_named=True))
            linked.update(unlinked)
    created = Release.objects.bulk_create(rows)
    ReleaseAutoLinkedFlag.objects.bulk_create(
        [
            ReleaseAutoLinkedFlag(team_id=team_id, feature_flag_id=flag_id)
            for row in rows
            for flag_id in row.feature_flag_ids
        ],
        ignore_conflicts=True,
    )
    return created


def run_initial_import(team_id: int, load_flags: Callable[[], list[ImportFlag]]) -> int:
    team_id = root_team_id(team_id)
    with team_scope(team_id):
        ReleaseImportState.objects.get_or_create(team_id=team_id)
        with transaction.atomic():
            _lock_team(team_id)
            state = ReleaseImportState.objects.select_for_update().get(team_id=team_id)
            if state.completed:
                return 0
            created = _insert_unlinked(team_id, [(humanize(flag.key), [flag.id]) for flag in load_flags()])
            state.completed = True
            state.save(update_fields=["completed"])
    return len(created)


def create_unlinked_releases(team_id: int, releases: list[tuple[str, list[int]]]) -> list[Release]:
    team_id = root_team_id(team_id)
    with team_scope(team_id):
        with transaction.atomic():
            _lock_team(team_id)
            created = _insert_unlinked(team_id, releases)
        return list(
            Release.objects.filter(team_id=team_id, id__in=[release.id for release in created])
            .select_related("owner")
            .order_by("created_at", "id")
        )


def _tokens(key: str) -> list[str]:
    return [token for token in _SEPARATORS.split(key.lower()) if token]


def humanize(key: str) -> str:
    text = " ".join(_tokens(key)) or key
    return (text[:1].upper() + text[1:])[:MAX_NAME_LENGTH]


def project_imported(team_id: int) -> bool:
    return ReleaseImportState.objects.unscoped().filter(team_id=team_id).exists()


def _already_handled(team_id: int, flag_id: int) -> bool:
    return (
        ReleaseAutoLinkedFlag.objects.unscoped().filter(team_id=team_id, feature_flag_id=flag_id).exists()
        or Release.objects.unscoped().filter(team_id=team_id, feature_flag_ids__contains=[flag_id]).exists()
    )


def create_release_for_new_flag(flag_id: int, team_id: int, releases_enabled: Callable[..., bool]) -> None:
    team = Team.objects.filter(id=team_id).first()
    if team is None or _already_handled(root_team_id(team_id), flag_id):
        return
    creator_id = release_flag_creator_id(flag_id=flag_id, team_id=team_id)
    creator = User.objects.filter(id=creator_id).first() if creator_id else None
    enabled = releases_enabled(
        team_id=team.id,
        team_uuid=team.uuid,
        organization_id=team.organization_id,
        distinct_id=str(creator.distinct_id) if creator else str(team.uuid),
        email=creator.email if creator and not creator.anonymize_data else None,
        raise_on_error=True,
    )
    if not enabled:
        return
    flags = list_release_import_flags(
        team_id=team_id, project_id=team.project_id, access_control=None, flag_ids=[flag_id]
    )
    if flags:
        create_unlinked_releases(team_id, [(humanize(flags[0].key), [flags[0].id])])
