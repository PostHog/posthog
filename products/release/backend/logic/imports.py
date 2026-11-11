from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Callable, Iterable
from datetime import timedelta

from django.db import connection, transaction

from posthog.models import Team, User
from posthog.models.scoping import team_scope

from products.feature_flags.backend.facade.release_candidates import list_release_import_flags, release_flag_creator_id

from ..facade.contracts import ImportCandidateDTO, ImportFlag, ImportReason
from ..models import Release

RELATED_WINDOW = timedelta(days=14)
MIN_PREFIX_LENGTH = 3
MAX_NAME_LENGTH = 255
REASON_ORDER = [ImportReason.EXPERIMENT, ImportReason.EARLY_ACCESS, ImportReason.RELATED_FLAGS, ImportReason.FLAG]

_SEPARATORS = re.compile(r"[-_.:/\s]+")


def linked_flag_ids(team_id: int) -> set[int]:
    return {
        flag_id
        for flag_ids in Release.objects.filter(team_id=team_id).values_list("feature_flag_ids", flat=True)
        for flag_id in flag_ids
    }


def create_unlinked_releases(team_id: int, releases: list[tuple[str, list[int]]]) -> list[Release]:
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", [f"release-import:{team_id}"])
        linked = linked_flag_ids(team_id)
        rows: list[Release] = []
        for name, flag_ids in releases:
            unlinked = [flag_id for flag_id in dict.fromkeys(flag_ids) if flag_id not in linked]
            if unlinked:
                rows.append(Release(team_id=team_id, name=name, feature_flag_ids=unlinked, auto_named=True))
                linked.update(unlinked)
        created = Release.objects.bulk_create(rows)
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


def _common_prefix(keys: list[list[str]]) -> list[str]:
    prefix = keys[0]
    for tokens in keys[1:]:
        length = 0
        while length < min(len(prefix), len(tokens)) and prefix[length] == tokens[length]:
            length += 1
        prefix = prefix[:length]
    return prefix


def _candidate(reason: ImportReason, name: str, flags: list[ImportFlag]) -> ImportCandidateDTO:
    return ImportCandidateDTO(
        key=f"{reason.value}:{flags[0].id}",
        name=name[:MAX_NAME_LENGTH],
        reason=reason,
        feature_flag_ids=[flag.id for flag in flags],
        flag_keys=[flag.key for flag in flags],
        created_at=max(flag.created_at for flag in flags),
    )


def _related_groups(flags: list[ImportFlag]) -> list[list[ImportFlag]]:
    buckets: dict[tuple[str, int | None], list[ImportFlag]] = defaultdict(list)
    singles: list[list[ImportFlag]] = []
    for flag in flags:
        tokens = _tokens(flag.key)
        if len(tokens) > 1 and len(tokens[0]) >= MIN_PREFIX_LENGTH:
            buckets[(tokens[0], flag.created_by_id)].append(flag)
        else:
            singles.append([flag])
    groups: list[list[ImportFlag]] = []
    for bucket in buckets.values():
        current: list[ImportFlag] = []
        for flag in sorted(bucket, key=lambda item: (item.created_at, item.id)):
            if current and flag.created_at - current[0].created_at > RELATED_WINDOW:
                groups.append(current)
                current = []
            current.append(flag)
        groups.append(current)
    return groups + singles


def group_import_candidates(flags: Iterable[ImportFlag], linked: set[int]) -> list[ImportCandidateDTO]:
    candidates: list[ImportCandidateDTO] = []
    loose: list[ImportFlag] = []
    for flag in flags:
        if flag.id in linked:
            continue
        if flag.early_access_names:
            candidates.append(_candidate(ImportReason.EARLY_ACCESS, flag.early_access_names[0], [flag]))
        elif flag.experiment_names:
            candidates.append(_candidate(ImportReason.EXPERIMENT, flag.experiment_names[0], [flag]))
        else:
            loose.append(flag)
    for group in _related_groups(loose):
        if len(group) == 1:
            candidates.append(_candidate(ImportReason.FLAG, humanize(group[0].key), group))
        else:
            prefix = _common_prefix([_tokens(flag.key) for flag in group])
            candidates.append(_candidate(ImportReason.RELATED_FLAGS, humanize(" ".join(prefix)), group))
    candidates.sort(key=lambda item: item.created_at, reverse=True)
    candidates.sort(key=lambda item: REASON_ORDER.index(item.reason))
    return candidates


def create_release_for_new_flag(flag_id: int, team_id: int, releases_enabled: Callable[..., bool]) -> None:
    team = Team.objects.filter(id=team_id).first()
    if team is None:
        return
    creator_id = release_flag_creator_id(flag_id=flag_id, team_id=team_id)
    creator = User.objects.filter(id=creator_id).first() if creator_id else None
    enabled = releases_enabled(
        team_id=team.id,
        team_uuid=team.uuid,
        organization_id=team.organization_id,
        distinct_id=str(creator.distinct_id) if creator else str(team.uuid),
        email=creator.email if creator and not creator.anonymize_data else None,
    )
    if not enabled:
        return
    flags = list_release_import_flags(
        team_id=team_id, project_id=team.project_id, access_control=None, flag_ids=[flag_id]
    )
    if flags:
        with team_scope(team_id):
            create_unlinked_releases(team_id, [(humanize(flags[0].key), [flags[0].id])])
