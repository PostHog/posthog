"""Keep `SignalReportSuggestedReviewer` in step with the reviewer artefact log, and read it.

The artefact log is canonical and stays that way. This module owns the derived, indexed copy of
one question it answers slowly — "which reports name this person as a reviewer?" — plus the two
matching rules the inbox reads it with.
"""

from __future__ import annotations

import uuid as uuid_module

from django.db import transaction
from django.db.models import Q, QuerySet

import structlog
from pydantic import ValidationError

from products.signals.backend.artefact_schemas import SuggestedReviewers
from products.signals.backend.models import SignalReportArtefact, SignalReportSuggestedReviewer

logger = structlog.get_logger(__name__)


# A tie needs at most a handful of rows, and a report's reviewer history is short, so reading the
# newest few and grouping in Python costs one query where a timestamp lookup would cost two.
_TIE_SCAN_LIMIT = 20


def _current_reviewer_artefacts(team_id: int, report_id: str) -> list[SignalReportArtefact]:
    """The report's live reviewer artefacts: the newest row, plus any row written at the same
    instant. The predicate this replaces ("no newer row of this type exists") also kept every row
    at the maximum timestamp, so a tie must stay a union rather than become a pick.
    """
    newest_first = list(
        SignalReportArtefact.objects.filter(
            team_id=team_id,
            report_id=report_id,
            type=SignalReportArtefact.ArtefactType.SUGGESTED_REVIEWERS,
        ).order_by("-created_at")[:_TIE_SCAN_LIMIT]
    )
    if not newest_first:
        return []
    latest = newest_first[0].created_at
    return [artefact for artefact in newest_first if artefact.created_at == latest]


def _rows_for_artefact(artefact: SignalReportArtefact) -> list[SignalReportSuggestedReviewer]:
    try:
        entries = SuggestedReviewers.model_validate_json(artefact.content).root
    except ValidationError:
        # A row the current schema cannot read names nobody. The artefact still holds the truth,
        # so a later edit that parses restores the index.
        logger.warning(
            "signals_suggested_reviewer_index_unparseable_artefact",
            team_id=artefact.team_id,
            report_id=str(artefact.report_id),
            artefact_id=str(artefact.id),
        )
        return []
    rows: list[SignalReportSuggestedReviewer] = []
    seen: set[tuple[str | None, str | None]] = set()
    for entry in entries:
        login = entry.github_login.lower() if entry.github_login else None
        identity = (entry.user_uuid, login)
        if identity in seen:
            continue
        seen.add(identity)
        rows.append(
            SignalReportSuggestedReviewer(
                team_id=artefact.team_id,
                report_id=artefact.report_id,
                artefact_id=artefact.id,
                user_uuid=uuid_module.UUID(entry.user_uuid) if entry.user_uuid else None,
                github_login=login,
            )
        )
    return rows


def sync_suggested_reviewer_index(*, team_id: int, report_id: str) -> None:
    """Rewrite a report's index rows from its current reviewer artefacts.

    Called from every path that can change which artefact is current — an append, an edit in
    place, a delete — so the index never needs a reader to fall back to the log.
    """
    rows: list[SignalReportSuggestedReviewer] = []
    for artefact in _current_reviewer_artefacts(team_id, report_id):
        rows.extend(_rows_for_artefact(artefact))
    with transaction.atomic():
        SignalReportSuggestedReviewer.objects.for_team(team_id).filter(report_id=report_id).delete()
        if rows:
            SignalReportSuggestedReviewer.objects.for_team(team_id).bulk_create(rows)


def _identity_filter(user_uuids: list[str], github_logins: list[str], *, logins_match_unidentified_only: bool) -> Q:
    identity = Q(user_uuid__in=user_uuids) if user_uuids else Q(pk__in=[])
    if github_logins:
        login_match = Q(github_login__in=[login.lower() for login in github_logins])
        if logins_match_unidentified_only:
            login_match &= Q(user_uuid__isnull=True)
        identity |= login_match
    return identity


def report_ids_naming_reviewers(
    *,
    team_id: int,
    user_uuids: list[str],
    github_logins: list[str],
    logins_match_unidentified_only: bool,
) -> QuerySet:
    """Report ids whose current reviewer set names any of these identities.

    `logins_match_unidentified_only` keeps the two callers' rules apart. The list filter resolves
    a login from the requested uuid, so a login may only stand in for an entry that carries no
    uuid of its own — otherwise a login GitHub has since reassigned would route another person's
    reports. The "is this me?" annotation has the user's own login in hand and matches it either
    way.
    """
    identity = _identity_filter(
        user_uuids, github_logins, logins_match_unidentified_only=logins_match_unidentified_only
    )
    return SignalReportSuggestedReviewer.objects.for_team(team_id).filter(identity).values("report_id")
