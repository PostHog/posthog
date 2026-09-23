"""Keep `SignalReportSuggestedReviewer` in step with the reviewer artefact log, and read it.

The artefact log is canonical and stays that way. This module owns the derived, indexed copy of
one question it answers slowly — "which reports name this person as a reviewer?" — plus the two
matching rules the inbox reads it with.
"""

from __future__ import annotations

import uuid as uuid_module
from collections import defaultdict
from collections.abc import Iterable, Iterator
from typing import TypeVar

from django.db import transaction
from django.db.models import Model, Q, QuerySet

import structlog
from pydantic import ValidationError

from products.signals.backend.artefact_schemas import SuggestedReviewers
from products.signals.backend.models import SignalReportArtefact, SignalReportSuggestedReviewer

logger = structlog.get_logger(__name__)

_IndexRow = TypeVar("_IndexRow", bound=Model)


# A tie needs at most a handful of rows, and a report's reviewer history is short, so reading the
# newest few and grouping in Python costs one query where a timestamp lookup would cost two.
_TIE_SCAN_LIMIT = 20

# Reports per batch of the rebuild walk. A batch reads its reports' artefacts in one query and
# rewrites their rows in one transaction, so this bounds both.
_REBUILD_BATCH_SIZE = 100


def _live_artefacts(artefacts: Iterable[SignalReportArtefact]) -> list[SignalReportArtefact]:
    """One report's live reviewer artefacts, picked out of any set of that report's reviewer
    artefacts: the newest row, plus any row written at the same instant. The predicate this
    replaces ("no newer row of this type exists") also kept every row at the maximum timestamp,
    so a tie must stay a union rather than become a pick.
    """
    rows = list(artefacts)
    if not rows:
        return []
    latest = max(artefact.created_at for artefact in rows)
    return [artefact for artefact in rows if artefact.created_at == latest]


def _rows_for_artefact(artefact: SignalReportArtefact, index_model: type[_IndexRow]) -> list[_IndexRow]:
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
    rows: list[_IndexRow] = []
    seen: set[tuple[str | None, str | None]] = set()
    for entry in entries:
        login = entry.github_login.lower() if entry.github_login else None
        identity = (entry.user_uuid, login)
        if identity in seen:
            continue
        seen.add(identity)
        rows.append(
            index_model(
                team_id=artefact.team_id,
                report_id=artefact.report_id,
                artefact_id=artefact.id,
                user_uuid=uuid_module.UUID(entry.user_uuid) if entry.user_uuid else None,
                github_login=login,
            )
        )
    return rows


def _rows_for_report(artefacts: Iterable[SignalReportArtefact], index_model: type[_IndexRow]) -> list[_IndexRow]:
    rows: list[_IndexRow] = []
    for artefact in _live_artefacts(artefacts):
        rows.extend(_rows_for_artefact(artefact, index_model))
    return rows


def sync_suggested_reviewer_index(*, team_id: int, report_id: str) -> None:
    """Rewrite a report's index rows from its current reviewer artefacts.

    Called from every path that can change which artefact is current — an append, an edit in
    place, a delete — so the index never needs a reader to fall back to the log.
    """
    rows = _rows_for_report(
        SignalReportArtefact.objects.filter(
            team_id=team_id,
            report_id=report_id,
            type=SignalReportArtefact.ArtefactType.SUGGESTED_REVIEWERS,
        ).order_by("-created_at")[:_TIE_SCAN_LIMIT],
        SignalReportSuggestedReviewer,
    )
    index_rows = SignalReportSuggestedReviewer.objects.for_team(team_id)
    with transaction.atomic():
        index_rows.filter(report_id=report_id).delete()
        if rows:
            index_rows.bulk_create(rows)


def rebuild_suggested_reviewer_index(
    *,
    reviewer_artefacts: QuerySet,
    index_rows: QuerySet,
    after: str | None = None,
    batch_size: int = _REBUILD_BATCH_SIZE,
    only_missing: bool = False,
) -> Iterator[tuple[int, str]]:
    """Rebuild index rows from the reviewer artefact log, a batch of reports at a time.

    Yields `(reports in the batch, resume cursor)` once per batch, so a caller can report progress
    and resume a stopped walk. Each batch commits on its own, which keeps a long run off a single
    transaction.

    The caller passes the two querysets rather than a team id, because the two callers reach the
    rows differently: the management command scopes both to one project, and the data migration
    hands over the historical models its own state knows. The index model comes from `index_rows`
    for the same reason.

    `only_missing` restricts the walk to reports that have no index rows, and inserts without
    deleting. A backfill runs that way, because a report the live code has already indexed needs
    no repair.
    """
    index_model = index_rows.model
    while True:
        batch = reviewer_artefacts if after is None else reviewer_artefacts.filter(report_id__gt=after)
        report_ids = list(batch.order_by("report_id").values_list("report_id", flat=True).distinct()[:batch_size])
        if not report_ids:
            return
        after = str(report_ids[-1])
        targets = report_ids
        if only_missing:
            indexed = set(index_rows.filter(report_id__in=report_ids).values_list("report_id", flat=True))
            targets = [report_id for report_id in report_ids if report_id not in indexed]
        if targets:
            by_report: dict[uuid_module.UUID, list[SignalReportArtefact]] = defaultdict(list)
            for artefact in reviewer_artefacts.filter(report_id__in=targets):
                by_report[artefact.report_id].append(artefact)
            rows = [row for artefacts in by_report.values() for row in _rows_for_report(artefacts, index_model)]
            with transaction.atomic():
                if only_missing:
                    # The artefact read sits outside this transaction, so a live sync can commit
                    # between the two. Reading the index again here keeps the walk from replacing
                    # a newer row set with rows built from an older artefact. The window narrows
                    # rather than closes: a sync that commits after this read leaves the report
                    # with a second copy of its identities, which both readers match by report id
                    # and so count once, and the next reviewer write rewrites all of them.
                    indexed = set(index_rows.filter(report_id__in=targets).values_list("report_id", flat=True))
                    rows = [row for row in rows if row.report_id not in indexed]
                else:
                    index_rows.filter(report_id__in=targets).delete()
                if rows:
                    index_rows.bulk_create(rows)
        yield len(targets), after


def rebuild_suggested_reviewer_index_for_team(
    *,
    team_id: int,
    after: str | None = None,
    batch_size: int = _REBUILD_BATCH_SIZE,
    only_missing: bool = False,
) -> Iterator[tuple[int, str]]:
    """`rebuild_suggested_reviewer_index` over one project's reports.

    Which artefact type carries reviewers, and which manager scopes the index rows to a team, are
    this module's knowledge, so a caller that has only a team id does not repeat them.
    """
    return rebuild_suggested_reviewer_index(
        reviewer_artefacts=SignalReportArtefact.objects.filter(
            team_id=team_id, type=SignalReportArtefact.ArtefactType.SUGGESTED_REVIEWERS
        ),
        index_rows=SignalReportSuggestedReviewer.objects.for_team(team_id),
        after=after,
        batch_size=batch_size,
        only_missing=only_missing,
    )


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
