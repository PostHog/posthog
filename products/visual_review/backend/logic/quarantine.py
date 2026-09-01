"""Quarantined identifiers: list, add, lift, expire."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from ..db import WRITER_DB
from ..facade.enums import ActorType
from ..models import QuarantinedIdentifier, Run
from . import errors, repos


def list_quarantined_identifiers(
    repo_id: UUID, team_id: int, identifier: str | None = None, run_type: str | None = None
) -> list[QuarantinedIdentifier]:
    qs = (
        QuarantinedIdentifier.objects.using(WRITER_DB)
        .filter(repo_id=repo_id, team_id=team_id)
        # Preload `source_run` so the facade can render the "what was wrong"
        # link without an extra fetch per row. `Run.metadata` (JSONField) and
        # `Run.error_message` (TextField) can be large and aren't needed for
        # the summary — defer to keep response payloads tight.
        .select_related("source_run")
        .defer("source_run__metadata", "source_run__error_message")
    )
    if run_type:
        qs = qs.filter(run_type=run_type)
    if identifier:
        qs = qs.filter(identifier=identifier)
    else:
        now = timezone.now()
        qs = qs.filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now))
    return list(qs.order_by("-created_at"))


@transaction.atomic(using=WRITER_DB)
def quarantine_identifier(
    repo_id: UUID,
    identifier: str,
    run_type: str,
    reason: str,
    user_id: int,
    team_id: int,
    expires_at: datetime | None = None,
    source_run_id: UUID | None = None,
    source: ActorType = ActorType.HUMAN,
) -> QuarantinedIdentifier:
    repos.get_repo(repo_id, team_id)  # raises RepoNotFoundError if repo not owned by team
    now = timezone.now()
    # Resolve the source run inside the team scope so a malicious caller can't
    # attach a quarantine to an unrelated run. Silently drop on mismatch — the
    # quarantine itself still wins; we just lose the "what was wrong" pointer.
    # We fetch (not just .exists()) so the facade can serialize source_run
    # without a lazy-load on the freshly-created row.
    source_run: Run | None = None
    if source_run_id is not None:
        source_run = Run.objects.using(WRITER_DB).filter(id=source_run_id, repo_id=repo_id, team_id=team_id).first()
    QuarantinedIdentifier.objects.using(WRITER_DB).select_for_update().filter(
        repo_id=repo_id,
        identifier=identifier,
        run_type=run_type,
        team_id=team_id,
    ).filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now)).update(expires_at=now)
    return QuarantinedIdentifier.objects.using(WRITER_DB).create(
        repo_id=repo_id,
        identifier=identifier,
        run_type=run_type,
        team_id=team_id,
        reason=reason,
        expires_at=expires_at,
        created_by_id=user_id,
        source_run=source_run,
        source=source,
    )


def unquarantine_identifier(repo_id: UUID, identifier: str, run_type: str, team_id: int) -> None:
    repos.get_repo(repo_id, team_id)  # raises RepoNotFoundError if repo not owned by team
    QuarantinedIdentifier.objects.using(WRITER_DB).filter(
        repo_id=repo_id,
        identifier=identifier,
        run_type=run_type,
        team_id=team_id,
    ).filter(Q(expires_at__isnull=True) | Q(expires_at__gt=timezone.now())).update(expires_at=timezone.now())


def expire_quarantine_entry(entry_id: UUID, team_id: int) -> None:
    now = timezone.now()
    active = Q(expires_at__isnull=True) | Q(expires_at__gt=now)
    try:
        entry = QuarantinedIdentifier.objects.using(WRITER_DB).filter(active).get(id=entry_id, team_id=team_id)
    except QuarantinedIdentifier.DoesNotExist as e:
        raise errors.RunNotFoundError(f"Quarantine entry {entry_id} not found or already expired") from e

    # Expire all active entries for the same identifier/run_type, not just this one
    QuarantinedIdentifier.objects.using(WRITER_DB).filter(
        repo_id=entry.repo_id,
        identifier=entry.identifier,
        run_type=entry.run_type,
        team_id=team_id,
    ).filter(active).update(expires_at=now)
