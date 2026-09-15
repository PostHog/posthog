"""Tells a GitHub issue that raised a report that self-driving has looked at it.

A GitHub issue flows into the inbox as a signal, gets researched against the codebase, and the
result lands in the inbox only. Nobody watching the issue hears anything, so a maintainer or an
outside contributor can start on work we already research. This comments a link to the report back
on the issue, which closes that loop. Opt-in per team, because the comment is public on the issue
thread.
"""

from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.utils import timezone

import structlog

from posthog.egress.limiter.policies import Priority
from posthog.models import Team
from posthog.models.github_integration_base import GitHubIntegrationBase, PullRequestRef
from posthog.models.integration import GitHubIntegration

from products.signals.backend.enums import SignalSourceProduct, SignalSourceType
from products.signals.backend.models import SignalReport, SignalReportGithubComment, SignalTeamConfig

logger = structlog.get_logger(__name__)

EGRESS_SOURCE = "signals_github_writeback"
CLAIM_LEASE = timedelta(minutes=10)
MAX_COMMENT_PAGES = 10


def _comment_body(report_url: str, marker: str) -> str:
    """A pointer, deliberately carrying none of the report's own content.

    The comment is public on the issue thread, while the report is behind the PostHog project's own
    access check. Copying the title or the summary here would publish research that only the project
    is entitled to, so the comment says the work exists and links to it.
    """
    return (
        "PostHog self-driving picked up this issue and researched it. Somebody may already be "
        f"working on it, so ask before you start a fix.\n\nReport (team access only): {report_url}\n\n{marker}"
    )


def _issue_refs(signals: list[dict]) -> list[PullRequestRef]:
    """The open GitHub issues among a report's signals, each one once.

    A closed issue is answered already, and a locked one refuses comments, so neither is worth a
    call.
    """
    refs: dict[tuple[str, int], PullRequestRef] = {}
    for signal in signals:
        if (
            signal.get("source_product") != SignalSourceProduct.GITHUB
            or signal.get("source_type") != SignalSourceType.ISSUE
        ):
            continue
        extra = signal.get("extra") or {}
        if extra.get("locked") or str(extra.get("state") or "").lower() != "open":
            continue
        ref = GitHubIntegrationBase.parse_issue_url(str(extra.get("html_url") or ""))
        if ref is not None:
            refs.setdefault((ref.repository.lower(), ref.number), ref)
    return list(refs.values())


def _has_existing_comment(github: GitHubIntegration, repository: str, number: int, marker: str) -> bool | None:
    # An incomplete read cannot prove that a previous POST failed.
    for page in range(1, MAX_COMMENT_PAGES + 1):
        response = github.api_request(
            "GET",
            f"/repos/{repository}/issues/{number}/comments",
            endpoint="/repos/{owner}/{repo}/issues/{issue_number}/comments",
            params={"per_page": 100, "page": page},
            retry_transient=False,
        )
        response.raise_for_status()
        comments = response.json()
        if not isinstance(comments, list):
            return None
        if any(isinstance(comment, dict) and marker in str(comment.get("body") or "") for comment in comments):
            return True
        if len(comments) < 100:
            return False
    return None


def _post_to_issue(
    *,
    team_id: int,
    report_id: str,
    ref: PullRequestRef,
    body: str,
    marker: str,
    integrations: dict[str, GitHubIntegration | None],
) -> bool:
    """Comment on one issue, once per (report, issue). Returns whether a comment went out.

    Pending claims survive uncertain POST outcomes. After the lease expires, a later settle checks
    for the stable comment marker before it retries. The lease exceeds the activity timeout.

    ``integrations`` memoizes the integration per repository for one run, because resolving one
    costs an authenticated GitHub call per integration the team has.
    """
    # GitHub compares a repository path without case, while the unique constraint below does not,
    # so the raw spelling would let a case-only rename claim a second row and comment twice.
    repository = ref.repository.lower()

    # for_team scopes the lookup; get_or_create still needs team_id in the defaults, because a
    # queryset filter does not propagate into the row it creates.
    claim, created = SignalReportGithubComment.objects.for_team(team_id).get_or_create(
        report_id=report_id,
        repository=repository,
        number=ref.number,
        defaults={"team_id": team_id},
    )
    if claim.commented_at is not None:
        return False

    claims = SignalReportGithubComment.objects.for_team(team_id).filter(pk=claim.pk, commented_at__isnull=True)
    if not created:
        acquired_at = timezone.now()
        if not claims.filter(updated_at__lt=acquired_at - CLAIM_LEASE).update(updated_at=acquired_at):
            return False
        claim.updated_at = acquired_at
    owned_claim = claims.filter(updated_at=claim.updated_at)

    try:
        if repository not in integrations:
            # Background comments must leave the interactive GitHub budget available.
            integrations[repository] = GitHubIntegration.first_for_team_repository(
                team_id, repository, source=EGRESS_SOURCE, priority=Priority.BATCH
            )
        github = integrations[repository]
        if github is None:
            return False
        if not created:
            existing = _has_existing_comment(github, repository, ref.number, marker)
            if existing is not False:
                if existing:
                    owned_claim.update(commented_at=timezone.now())
                return False

        response = github.api_request(
            "GET",
            f"/repos/{repository}/issues/{ref.number}",
            endpoint="/repos/{owner}/{repo}/issues/{issue_number}",
            retry_transient=False,
        )
        response.raise_for_status()
        issue = response.json()
        if (
            not isinstance(issue, dict)
            or issue.get("state") != "open"
            or issue.get("locked") is not False
            or "pull_request" in issue
        ):
            return False
        if not owned_claim.filter(updated_at__gt=timezone.now() - CLAIM_LEASE).exists():
            return False
        outcome = github.comment_on_issue(repository, ref.number, body)
    except Exception:
        logger.exception(
            "signals.github_writeback_failed",
            report_id=report_id,
            team_id=team_id,
            repository=repository,
            number=ref.number,
        )
        return False

    if not outcome.get("success"):
        logger.warning(
            "signals.github_writeback_failed",
            report_id=report_id,
            team_id=team_id,
            repository=repository,
            number=ref.number,
            error=outcome.get("error"),
        )
        return False

    owned_claim.update(commented_at=timezone.now())
    return True


def post_report_link_to_github_issues(team: Team, report_id: str, signals: list[dict]) -> int:
    """Comment a link to a ready report on each GitHub issue that contributed to it.

    Returns the number of comments posted. Best-effort: a failure here must not fail the report's
    notification flow, so per-issue errors are logged rather than raised.
    """
    if not SignalTeamConfig.objects.filter(team_id=team.pk, github_issue_writeback_enabled=True).exists():
        return 0

    refs = _issue_refs(signals)
    if not refs:
        return 0

    if not SignalReport.objects.filter(id=report_id, team_id=team.pk, status=SignalReport.Status.READY).exists():
        return 0

    marker = f"<!-- posthog:signal-report:{report_id} -->"
    body = _comment_body(f"{settings.SITE_URL}/project/{team.pk}/inbox/reports/{report_id}", marker)
    integrations: dict[str, GitHubIntegration | None] = {}
    posted = sum(
        _post_to_issue(
            team_id=team.pk, report_id=report_id, ref=ref, body=body, marker=marker, integrations=integrations
        )
        for ref in refs
    )
    logger.info(
        "signals.github_writeback_posted",
        report_id=report_id,
        team_id=team.pk,
        issues=len(refs),
        posted=posted,
    )
    return posted
