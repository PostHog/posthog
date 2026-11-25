"""A cheap fingerprint of the rows behind a person's input hash, so the tick can skip the full gather.

The full check reads every candidate with its text, scores and pull requests, then hashes them. The fingerprint
reads only the facts that can move that hash: the person's open reports and their row facts, the artefacts, pull
requests and claims of those reports, the summary version, the inbox activity counts, the flags that change the
pools, and the config. It reads no ranking content and does not order the pools.

A full check that finds no change stores the fingerprint for the latest row. A later fingerprint that is the same, for
the same row, confirms the row without the gather. The fingerprint is read before the gather, so a write during the
gather changes the next fingerprint and the next check is a full one.

Pull request states that only the tasks product holds are not in the fingerprint. The stored fingerprint expires
`precheck_hours` after the full check that stored it, so every pair gets a full check at least that often.
"""

import json
import hashlib
import datetime
import dataclasses
from typing import Any

from django.core.cache import cache
from django.db.models import BooleanField, Count, Exists, ExpressionWrapper, Max, OuterRef, Q, Sum, TextField, Value
from django.db.models.functions import MD5, Coalesce

import structlog

from posthog.models import Team, User

from products.signals.backend.activity_summary.render import INBOX_ARTEFACT_TYPES
from products.signals.backend.models import (
    PersonalInboxRanking,
    SignalReport,
    SignalReportAction,
    SignalReportArtefact,
    SignalReportAssignment,
    SignalReportPullRequest,
    SignalReviewerExclusion,
)
from products.signals.backend.personal_ranking.candidates import EXCLUDED_STATUSES
from products.signals.backend.personal_ranking.config import TICK_DISABLED, PersonalRankingConfig
from products.signals.backend.personal_ranking.prompt import PROMPT_VERSION, system_prompt
from products.signals.backend.ranking.access import can_view_inbox_ranking
from products.signals.backend.report_content_gates import team_report_monitoring_enabled
from products.signals.backend.suggested_reviewer_index import report_ids_naming_reviewers

logger = structlog.get_logger(__name__)


def _key(team_id: int, user_id: int) -> str:
    return f"signals_personal_ranking_precheck/{team_id}/{user_id}"


def _person_reports(
    team: Team, user: User, github_login: str | None, config: PersonalRankingConfig, now: datetime.datetime
) -> list[Any]:
    """Every open report that names the person or has a claim of theirs, with the row facts that the pools read.

    The pools only hold reports from this set, so a report that joins or leaves a pool changes this list.
    """
    naming = report_ids_naming_reviewers(
        team_id=team.id,
        user_uuids=[str(user.uuid)],
        github_logins=[github_login.lower()] if github_login else [],
        logins_match_unidentified_only=False,
    )
    claims = SignalReportArtefact.objects.filter(
        team_id=team.id, type=SignalReportArtefact.ArtefactType.WORK_CLAIM, created_by_id=user.id
    ).values("report_id")
    legacy = SignalReportAssignment.objects.for_team(team.id).filter(actor_user_id=user.id).values("report_id")
    window_start = now - datetime.timedelta(days=config.window_days)
    rows = (
        SignalReport.objects.filter(team_id=team.id)
        .filter(Q(id__in=naming) | Q(id__in=claims) | Q(id__in=legacy))
        .exclude(status__in=EXCLUDED_STATUSES)
        .annotate(
            names_person=Exists(naming.filter(report_id=OuterRef("id"))),
            # A report leaves the `for_you_recommended` window with time and no write.
            in_window=ExpressionWrapper(Q(created_at__gte=window_start), output_field=BooleanField()),
            # Some writers change the text with `update()`, which leaves `updated_at` as it was.
            title_md5=MD5(Coalesce("title", Value(""), output_field=TextField())),
            summary_md5=MD5(Coalesce("summary", Value(""), output_field=TextField())),
        )
        .order_by("id")
        .values_list(
            "id",
            "status",
            "updated_at",
            "latest_actionability",
            "latest_already_addressed",
            "names_person",
            "in_window",
            "title_md5",
            "summary_md5",
        )
    )
    return [list(row) for row in rows]


def _inbox_activity(team: Team, user: User, config: PersonalRankingConfig, now: datetime.datetime) -> dict[str, Any]:
    # The counts inside the window change when a fact ages out of the block, with no write.
    start = now - datetime.timedelta(days=config.inbox_activity_days)
    actions = (
        SignalReportAction.objects.for_team(team.id)
        .filter(user_id=user.id)
        .exclude(report__status=SignalReport.Status.DELETED)
        .aggregate(in_window=Count("id", filter=Q(last_at__gte=start)), last_at=Max("last_at"), repeats=Sum("count"))
    )
    artefacts = (
        SignalReportArtefact.objects.filter(
            team_id=team.id, created_by_id=user.id, type__in=INBOX_ARTEFACT_TYPES, created_at__gte=start
        )
        .exclude(report__status=SignalReport.Status.DELETED)
        .aggregate(count=Count("id"), created_at=Max("created_at"))
    )
    exclusions = sorted(
        list(row)
        for row in SignalReviewerExclusion.objects.for_team(team.id)
        .filter(subject_user_uuid=user.uuid)
        .values_list("id", "status", "repository", "path_prefix", "updated_at")
    )
    return {"actions": actions, "artefacts": artefacts, "exclusions": exclusions}


def input_fingerprint(
    team: Team,
    user: User,
    config: PersonalRankingConfig,
    *,
    now: datetime.datetime,
    limit: int,
    summary_version: int | None,
) -> str:
    github_login = user.get_github_login()
    reports = _person_reports(team, user, github_login, config, now)
    report_ids = [row[0] for row in reports]
    # Artefacts are appended, so the count catches a new row whatever its `created_at`.
    artefacts = SignalReportArtefact.objects.filter(team_id=team.id, report_id__in=report_ids).aggregate(
        count=Count("id"), created_at=Max("created_at"), updated_at=Max("updated_at")
    )
    pull_requests = sorted(
        list(row)
        for row in SignalReportPullRequest.objects.for_team(team.id)
        .filter(report_links__report_id__in=report_ids)
        .values_list("id", "state", "updated_at")
        .distinct()
    )
    assignments = sorted(
        list(row)
        for row in SignalReportAssignment.objects.for_team(team.id)
        .filter(report_id__in=report_ids)
        .values_list("id", "actor_kind", "actor_user_id", "pr_url", "pr_state", "pr_merged", "updated_at")
    )
    payload = {
        "reports": reports,
        "artefacts": artefacts,
        "pull_requests": pull_requests,
        "assignments": assignments,
        "summary_version": summary_version,
        "inbox_activity": _inbox_activity(team, user, config, now) if config.inbox_activity_lines > 0 else None,
        "can_view_ranking": can_view_inbox_ranking(user, team),
        "monitoring": team_report_monitoring_enabled(team.id),
        "github_login": github_login,
        # The tick levers do not change the inputs, so a change to them keeps the stored fingerprints.
        "config": repr(dataclasses.replace(config, tick=TICK_DISABLED)),
        "prompt": [PROMPT_VERSION, system_prompt(config, limit)],
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def fingerprint_matches(team: Team, user: User, row: PersonalInboxRanking, fingerprint: str) -> bool:
    """True when the last full check stored this fingerprint for this row and its hash. A cache error says no."""
    try:
        stored = cache.get(_key(team.id, user.id))
    except Exception:
        logger.exception("signals.personal_ranking.precheck_read_failed", team_id=team.id, user_id=user.id)
        return False
    return stored == {"row_id": str(row.id), "input_hash": row.input_hash, "fingerprint": fingerprint}


def store_fingerprint(team: Team, user: User, row: PersonalInboxRanking, fingerprint: str, hours: int) -> None:
    try:
        cache.set(
            _key(team.id, user.id),
            {"row_id": str(row.id), "input_hash": row.input_hash, "fingerprint": fingerprint},
            timeout=hours * 3600,
        )
    except Exception:
        logger.exception("signals.personal_ranking.precheck_store_failed", team_id=team.id, user_id=user.id)
