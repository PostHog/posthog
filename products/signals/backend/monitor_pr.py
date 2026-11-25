import re
import hashlib
from collections.abc import Mapping, Sequence
from contextlib import suppress
from datetime import datetime
from functools import partial
from typing import Any, Literal
from urllib.parse import urlparse
from uuid import UUID

from django.core.cache import cache
from django.db import connection, transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

import structlog
import posthoganalytics
from asgiref.sync import async_to_sync
from pydantic import BaseModel, ConfigDict, Field, model_validator

from posthog.dataclasses import frozen
from posthog.egress.github.transport import GitHubRateLimitError
from posthog.egress.limiter.policies import Priority
from posthog.egress.transport.transport import EgressBudgetExhausted
from posthog.exceptions import QuotaLimitExceeded
from posthog.integrations import IntegrationManager
from posthog.models import Team, User
from posthog.models.github_integration_base import (
    GitHubIntegrationBase,
    GitHubIntegrationError,
    _is_safe_github_repo_path,
)
from posthog.models.integration import GitHubIntegration

from products.authorization.backend.facade import api as authorization
from products.authorization.backend.facade.contracts import CheckRequest, Resource, Subject
from products.authorization.backend.facade.enums import Action, ResourceType
from products.signals.backend.artefact_schemas import (
    CheckAuthoringStatus,
    ReviewerProposal,
    ReviewerState,
    SuggestedReviewerEntry,
    SuggestedReviewers,
)
from products.signals.backend.daily_limit import check_daily_report_admission, team_day_start
from products.signals.backend.github_actor import GITHUB_LOGIN_PATTERN
from products.signals.backend.models import ArtefactAttribution, SignalReport, SignalReportArtefact, SignalReportCheck
from products.signals.backend.pull_requests import apply_report_completion, link_pull_request
from products.signals.backend.quota import SelfDrivingAdmission, prepare_self_driving_admission
from products.signals.backend.report_assignments import MAX_PR_NUMBER, PullRequestDetails, create_claim
from products.signals.backend.report_check_authoring import create_checks_from_specs
from products.signals.backend.report_checks import (
    MAX_CHECK_HORIZON,
    CheckSpec,
    MetricThresholdConfig,
    authored_monitoring_interval_minutes,
    validate_metric_check_for_write,
)
from products.signals.backend.report_claims import get_active_claim
from products.signals.backend.report_content_gates import (
    team_pr_monitoring_enabled,
    team_report_metrics_enabled,
    team_report_monitoring_enabled,
)
from products.signals.backend.report_lifecycle import effective_report_status
from products.signals.backend.report_metric_access import ReportMetricAccessPolicy
from products.signals.backend.report_metrics import ReportMetric
from products.signals.backend.report_urls import build_bare_report_url
from products.signals.backend.trial.policy import TrialRefused
from products.signals.backend.trial.reports import prepare_report_pass
from products.tasks.backend.facade.repo_selection_types import RepoSelectionResult

logger = structlog.get_logger(__name__)
RECENT_PR_LIMIT = 50
PR_RESEARCH_DAILY_ATTEMPT_LIMIT = 5
MAX_PROMPT_DIFF_CHARS = 100_000
_STRIPPED_QUERY_KEYS = frozenset({"response", "name", "custom_name", "formulas"})


@frozen
class MonitorPRInput:
    team_id: int
    report_id: str
    user_id: int
    pr_url: str
    note: str = ""
    attempt_key: int = 0
    token_scopes: tuple[str, ...] | None = None


@frozen
class PRMonitoringRequestResult:
    report_id: UUID
    report_url: str
    status: str
    idempotent_replay: bool


@frozen
class PRReport:
    id: str
    status: str


@frozen
class BrowserPR:
    url: str
    repository: str
    number: int
    title: str
    state: str
    draft: bool
    author: str
    created_at: str
    updated_at: str
    report: PRReport | None
    monitoring_disabled_reason: str | None = None


@frozen
class PRPage:
    results: list[BrowserPR]
    github_login: str | None
    has_integration: bool


class PRMonitoringLimitExceeded(Exception):
    def __init__(self, message: str, *, retry_after: int | None = None):
        super().__init__(message)
        self.retry_after = retry_after


class PRMonitoringUnavailable(Exception):
    def __init__(self, message: str, *, report_id: UUID | None = None):
        super().__init__(message)
        self.report_id = report_id


class InvalidPullRequest(ValueError):
    pass


@frozen
class _RegisteredGitHubInstallation:
    id: int
    github: GitHubIntegration
    owner: str | None
    repositories: set[str]
    cache_pending: bool = False


@frozen
class MonitoredPullRequest:
    url: str
    repository: str
    number: int
    title: str
    head_sha: str
    base_branch: str
    state: str
    merged_at: datetime | None

    def details(self) -> PullRequestDetails:
        return PullRequestDetails(
            url=self.url,
            repository=self.repository,
            number=self.number,
            state=self.state,
            merged=self.state == "merged",
            merged_at=self.merged_at,
        )


def pr_identity(pr_url: str) -> tuple[str, int]:
    parsed_url = urlparse(pr_url)
    ref = GitHubIntegrationBase.parse_pull_request_url(pr_url)
    path_parts = [part for part in parsed_url.path.split("/") if part]
    if (
        parsed_url.scheme != "https"
        or parsed_url.netloc != "github.com"
        or len(path_parts) != 4
        or parsed_url.query
        or parsed_url.fragment
        or ref is None
        or not _is_safe_github_repo_path(ref.repository)
        or len(ref.repository) > 200
        or not 0 < ref.number <= MAX_PR_NUMBER
    ):
        raise InvalidPullRequest("Use a GitHub pull request URL, such as https://github.com/owner/repo/pull/123.")
    return ref.repository.lower(), ref.number


def monitor_key(user_id: int, pr_url: str) -> str:
    repository, number = pr_identity(pr_url)
    digest = hashlib.sha256(f"{repository}:{number}".encode()).hexdigest()
    return f"monitor-pr:{user_id}:{digest}"


def _installation_owner(github: GitHubIntegration) -> str | None:
    account = github.integration.config.get("account")
    name = account.get("name") if isinstance(account, dict) else github.integration.config.get("organization")
    return name if isinstance(name, str) and GITHUB_LOGIN_PATTERN.fullmatch(name) else None


def _schedule_repo_cache_refresh(team_id: int, integration_id: int) -> None:
    from products.signals.backend.tasks import refresh_signals_github_repository_cache  # noqa: PLC0415

    with suppress(Exception):
        if cache.add(f"signals:github-repo-refresh:{integration_id}", 1, timeout=60):
            refresh_signals_github_repository_cache.delay(team_id, integration_id)


def _registered_installations(
    team_id: int, *, source: str, priority: Priority = Priority.NORMAL
) -> list[_RegisteredGitHubInstallation]:
    result: list[_RegisteredGitHubInstallation] = []
    seen: set[str] = set()
    for integration in sorted(IntegrationManager.github.oauth.list(team_id), key=lambda row: row.id):
        github = GitHubIntegration(integration, source=source, priority=priority)
        repositories = {
            str(repo["full_name"]).lower()
            for repo in github.list_all_cached_repositories(allow_refresh=False)
            if isinstance(repo, dict) and repo.get("full_name")
        }
        if github.repository_cache_is_stale():
            _schedule_repo_cache_refresh(team_id, integration.id)
        result.append(
            _RegisteredGitHubInstallation(
                id=integration.id,
                github=github,
                owner=_installation_owner(github),
                repositories=repositories - seen,
                cache_pending=not repositories and not github.repository_cache_confirmed_empty(),
            )
        )
        seen.update(repositories)
    return result


def _pull_request_state_and_merge_time(result: dict[str, object]) -> tuple[str, datetime | None]:
    raw_state = result.get("state")
    if result.get("merged"):
        state = "merged"
    elif raw_state == "open" and result.get("draft"):
        state = "draft"
    elif isinstance(raw_state, str):
        state = raw_state
    else:
        state = ""
    if state not in {"open", "draft", "merged"}:
        raise InvalidPullRequest("This pull request was closed without merging.")
    raw_merged_at = result.get("merged_at")
    merged_at = parse_datetime(raw_merged_at) if isinstance(raw_merged_at, str) and raw_merged_at else None
    if state == "merged":
        now = timezone.now()
        if merged_at is None or timezone.is_naive(merged_at) or merged_at > now:
            raise InvalidPullRequest("GitHub did not return a valid merge timestamp. Try again shortly.")
        if merged_at <= now - MAX_CHECK_HORIZON:
            raise InvalidPullRequest(
                f"This pull request merged more than {MAX_CHECK_HORIZON.days} days ago and is outside the monitoring window."
            )
    return state, merged_at


def _resolve_repository_installation(team_id: int, repository: str, *, priority: Priority) -> GitHubIntegration:
    owner = repository.split("/", 1)[0]
    installations = _registered_installations(team_id, source="signals_monitor_pr", priority=priority)
    for item in installations:
        if repository in item.repositories:
            return item.github
    if any(item.cache_pending and (item.owner is None or item.owner.lower() == owner) for item in installations):
        raise PRMonitoringUnavailable("GitHub repositories are still syncing. Try again shortly.")
    raise InvalidPullRequest("Connect a GitHub integration that includes this repository.")


def load_pull_request(team_id: int, pr_url: str, *, priority: Priority = Priority.NORMAL) -> MonitoredPullRequest:
    repository, number = pr_identity(pr_url)
    github = _resolve_repository_installation(team_id, repository, priority=priority)
    result = github.get_pull_request(repository, number)
    if not result.get("success"):
        status_code = result.get("status_code")
        if status_code is None or status_code >= 500:
            raise GitHubIntegrationError(
                "GitHub is temporarily unavailable. Try again shortly.", status_code=status_code
            )
        raise InvalidPullRequest("Could not read this pull request through the project's GitHub integration.")
    head_repository = result.get("head_repository")
    if not isinstance(head_repository, str) or head_repository.lower() != repository:
        raise InvalidPullRequest(
            "Only pull requests from branches in this project's connected repositories can be monitored."
        )
    state, merged_at = _pull_request_state_and_merge_time(result)
    head_sha = result.get("head_sha") or ""
    if not re.fullmatch(r"[a-fA-F0-9]{40,64}", head_sha):
        raise InvalidPullRequest("GitHub did not return a valid pull request commit.")
    return MonitoredPullRequest(
        url=f"https://github.com/{repository}/pull/{number}",
        repository=repository,
        number=number,
        title=result.get("title") or f"{repository}#{number}",
        head_sha=head_sha,
        base_branch=result.get("base_branch") or "HEAD",
        state=state,
        merged_at=merged_at,
    )


def load_pull_request_diff(team_id: int, pr: MonitoredPullRequest, *, priority: Priority = Priority.NORMAL) -> str:
    github = _resolve_repository_installation(team_id, pr.repository, priority=priority)
    result = github.get_pull_request_diff(pr.repository, pr.number)
    if not result.get("success"):
        status_code = result.get("status_code")
        if status_code is None or status_code >= 500:
            raise GitHubIntegrationError(
                "GitHub is temporarily unavailable. Try again shortly.", status_code=status_code
            )
        raise InvalidPullRequest("Could not read this pull request diff through the project's GitHub integration.")
    diff = str(result.get("diff") or "")
    if len(diff) > MAX_PROMPT_DIFF_CHARS:
        return diff[:MAX_PROMPT_DIFF_CHARS] + "\n\n... diff truncated ...\n"
    return diff


def _fetch_recent_items(
    *, team_id: int, integration: _RegisteredGitHubInstallation, login: str
) -> list[dict[str, Any]]:
    assert integration.owner is not None
    query = f"is:pr author:{login} user:{integration.owner}"
    key = f"signals:pr-browser:{team_id}:{integration.id}:{hashlib.sha256(query.encode()).hexdigest()}"
    cached = cache.get(key)
    if cached is not None:
        return cached
    response = integration.github.api_request(
        "GET",
        "/search/issues",
        params={"q": query, "sort": "created", "order": "desc", "per_page": 100, "page": 1},
    )
    if not response.ok:
        raise GitHubIntegrationError("Could not list pull requests from GitHub.")
    try:
        items = response.json().get("items", [])
    except ValueError as error:
        raise GitHubIntegrationError("Could not list pull requests from GitHub.") from error
    cache.set(key, items, timeout=60)
    return items


def _browser_monitoring_disabled_reason(state: str, raw_merged_at: object) -> str | None:
    if state == "closed":
        return "Closed pull requests cannot be monitored"
    if state != "merged":
        return None
    merged_at = parse_datetime(raw_merged_at) if isinstance(raw_merged_at, str) and raw_merged_at else None
    now = timezone.now()
    if merged_at is None or timezone.is_naive(merged_at) or merged_at <= now - MAX_CHECK_HORIZON:
        return f"Pull requests merged more than {MAX_CHECK_HORIZON.days} days ago are outside the monitoring window"
    return None


def _browser_pr_from_search_item(
    *,
    item: dict[str, Any],
    integration: _RegisteredGitHubInstallation,
    user_id: int,
    reports: dict[str, PRReport],
) -> BrowserPR | None:
    try:
        repository, number = pr_identity(item["html_url"])
    except (KeyError, TypeError, InvalidPullRequest):
        return None
    if repository not in integration.repositories:
        return None
    raw_merged_at = item.get("pull_request", {}).get("merged_at")
    state = "merged" if raw_merged_at else item["state"]
    return BrowserPR(
        url=f"https://github.com/{repository}/pull/{number}",
        repository=repository,
        number=number,
        title=item["title"],
        state=state,
        draft=bool(item.get("draft")),
        author=item["user"]["login"],
        created_at=item["created_at"],
        updated_at=item["updated_at"],
        report=reports.get(monitor_key(user_id, item["html_url"])),
        monitoring_disabled_reason=_browser_monitoring_disabled_reason(state, raw_merged_at),
    )


def _collect_authored_prs(
    *,
    team_id: int,
    eligible: Sequence[_RegisteredGitHubInstallation],
    user_id: int,
    login: str,
    reports: dict[str, PRReport],
) -> list[BrowserPR]:
    results: list[BrowserPR] = []
    failures: list[Exception] = []
    for integration in eligible:
        try:
            items = _fetch_recent_items(team_id=team_id, integration=integration, login=login)
        except (EgressBudgetExhausted, GitHubIntegrationError, GitHubRateLimitError) as error:
            logger.warning(
                "signals_pr_browser_integration_failed", team_id=team_id, integration_id=integration.id, exc_info=True
            )
            failures.append(error)
            continue
        results.extend(
            pr
            for item in items
            if (
                pr := _browser_pr_from_search_item(item=item, integration=integration, user_id=user_id, reports=reports)
            )
        )
    if failures and len(failures) == len(eligible):
        raise failures[0]
    return results


def _has_pr_resource_access(team_id: int, user_id: int, action: Action) -> bool:
    subject = Subject(user_id=user_id)
    return all(
        authorization.check(
            [
                CheckRequest(resource=Resource(type=slug, project_id=team_id), action=action, subject=subject)
                for slug in (ResourceType.INBOX, ResourceType.TASK)
            ]
        )
    )


def list_authored_prs(*, team: Team, user: User) -> PRPage:
    team = team.parent_team or team
    if not team_pr_monitoring_enabled(team.id):
        raise PermissionError("PR monitoring is not enabled for this project.")
    if not _has_pr_resource_access(team.id, user.id, Action.VIEW):
        raise PermissionError("You need permission to view tasks in this project.")
    login = user.get_github_login(include_team_fallback=False)
    integrations = _registered_installations(team.id, source="signals_pr_browser")
    if not login or not GITHUB_LOGIN_PATTERN.fullmatch(login):
        return PRPage(results=[], github_login=None, has_integration=bool(integrations))
    eligible = [item for item in integrations if item.repositories and item.owner]
    if not eligible and any(item.cache_pending and item.owner for item in integrations):
        raise PRMonitoringUnavailable("GitHub repositories are still syncing. Try again shortly.")

    monitoring_enabled = team_report_monitoring_enabled(team.id)
    reports = {
        key: PRReport(
            id=str(report_id),
            status=effective_report_status(status, team_id=team.id, monitoring_enabled=monitoring_enabled),
        )
        for key, report_id, status in SignalReport.objects.filter(
            team_id=team.id, created_by_id=user.id, scout_idempotency_key__startswith=f"monitor-pr:{user.id}:"
        )
        .exclude(status=SignalReport.Status.DELETED)
        .values_list("scout_idempotency_key", "id", "status")
        if key is not None
    }
    results = _collect_authored_prs(team_id=team.id, eligible=eligible, user_id=user.id, login=login, reports=reports)
    results.sort(key=lambda pr: (pr.created_at, pr.url), reverse=True)
    return PRPage(results=results[:RECENT_PR_LIMIT], github_login=login, has_integration=bool(integrations))


def _ensure_pr_monitoring_permitted(team: Team, user: User) -> None:
    if (
        not team_pr_monitoring_enabled(team.id)
        or not team_report_monitoring_enabled(team.id)
        or not team_report_metrics_enabled(team.id)
    ):
        raise PermissionError("PR monitoring is not enabled for this project.")
    if not team.organization.is_ai_data_processing_approved:
        raise PermissionError("Enable AI data processing for this organization to monitor a PR.")
    if not _has_pr_resource_access(team.id, user.id, Action.EDIT):
        raise PermissionError("You need permission to start tasks in this project.")


def attempt_key_from_timestamp(timestamp: datetime | None) -> int:
    return int(timestamp.timestamp() * 1_000_000) if timestamp else 0


def attempt_key(report: SignalReport) -> int:
    return attempt_key_from_timestamp(report.last_run_at)


def pr_monitoring_pass_key(timestamp: datetime | None) -> str:
    return f"monitor-pr:{attempt_key_from_timestamp(timestamp)}"


def is_pr_monitoring_attempt(
    idempotency_key: str | None,
    self_driving_funding: object,
    last_run_at: datetime | None,
    *,
    run_count: int = 0,
) -> bool:
    if not idempotency_key or not idempotency_key.startswith("monitor-pr:"):
        return False
    if isinstance(self_driving_funding, Mapping) and "report_pass_key" in self_driving_funding:
        return self_driving_funding.get("report_pass_key") == pr_monitoring_pass_key(last_run_at)
    return run_count == 0


def report_has_active_pr_monitoring_pass(report: SignalReport) -> bool:
    return report.status == SignalReport.Status.IN_PROGRESS and is_pr_monitoring_attempt(
        report.scout_idempotency_key,
        report.self_driving_funding,
        report.last_run_at,
        run_count=report.run_count,
    )


def require_pr_monitoring_initiator(team: Team, user_id: int) -> User:
    initiator = User.objects.get(
        id=user_id, is_active=True, organization_membership__organization_id=team.organization_id
    )
    if (
        not team.organization.is_ai_data_processing_approved
        or not authorization.check(
            resource=Resource.project(team.id), action=Action.VIEW, subject=Subject(user_id=initiator.id)
        )
        or not _has_pr_resource_access(team.id, initiator.id, Action.EDIT)
    ):
        raise ValueError("The initiating user can no longer start PR research in this project")
    return initiator


def monitor_pr_workflow_id(team_id: int, report_id: str, attempt: int) -> str:
    return f"signals-monitor-pr-{team_id}-{report_id}-{attempt}"


def _lock_user_pr_monitoring(team_id: int, user_id: int) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            [f"signals-pr-monitor:{team_id}:{user_id}"],
        )


def _can_restart_pr_monitoring(report: SignalReport) -> bool:
    if report.status == SignalReport.Status.FAILED:
        return True
    return (
        report.status in {SignalReport.Status.PENDING_INPUT, SignalReport.Status.POTENTIAL}
        and bool(report.scout_idempotency_key and report.scout_idempotency_key.startswith("monitor-pr:"))
        and not report.metrics
        and not SignalReportCheck.objects.for_team(report.team_id).filter(report=report).exists()
    )


def _bind_pr_monitoring_pass(
    *,
    team: Team,
    report_id: UUID,
    run_started_at: datetime,
    admission: SelfDrivingAdmission,
    is_new_report: bool = False,
) -> None:
    try:
        if is_new_report:
            check_daily_report_admission(team, report_id=str(report_id))
        prepare_report_pass(
            team=team,
            report_id=str(report_id),
            operation_key=pr_monitoring_pass_key(run_started_at),
            admission=admission,
        )
    except (QuotaLimitExceeded, TrialRefused):
        raise PRMonitoringLimitExceeded("This project has reached its self-driving usage limit.") from None


def _append_pending_check_authoring(team_id: int, report_id: UUID, actor: ArtefactAttribution) -> None:
    SignalReportArtefact.append_status(
        team_id=team_id,
        report_id=str(report_id),
        content=CheckAuthoringStatus(
            status="failed",
            reason="PR monitoring research has not produced a measurement yet.",
        ),
        attribution=actor,
    )


def _restart_failed_report(
    *,
    team: Team,
    report: SignalReport,
    pr: MonitoredPullRequest,
    actor: ArtefactAttribution,
    run_started_at: datetime,
    admission: SelfDrivingAdmission,
) -> SignalReport:
    _bind_pr_monitoring_pass(team=team, report_id=report.id, run_started_at=run_started_at, admission=admission)
    report.status = SignalReport.Status.IN_PROGRESS
    report.error = None
    report.last_run_at = run_started_at
    report.save(update_fields=["status", "error", "last_run_at", "updated_at"])
    report.refresh_from_db(fields=["self_driving_funding"])
    active_claim = get_active_claim(team_id=team.id, report_id=str(report.id))
    link_pull_request(
        report=report,
        details=pr.details(),
        actor=actor,
        claim_id=str(active_claim.claim_id) if active_claim else None,
        notify_reviewers=False,
    )
    _append_pending_check_authoring(team.id, report.id, actor)
    return report


def prepare_monitoring(
    *,
    team: Team,
    user: User,
    pr: MonitoredPullRequest,
    admission: SelfDrivingAdmission | None = None,
) -> tuple[SignalReport, bool]:
    admission = admission or prepare_self_driving_admission(team)
    actor = ArtefactAttribution.from_user(user.id)
    key = monitor_key(user.id, pr.url)
    with transaction.atomic():
        _lock_user_pr_monitoring(team.id, user.id)
        SignalReport.objects.filter(team=team, scout_idempotency_key=key, status=SignalReport.Status.DELETED).update(
            scout_idempotency_key=None
        )
        existing = (
            SignalReport.objects.select_for_update(of=("self",), no_key=True)
            .filter(team=team, scout_idempotency_key=key)
            .first()
        )
        if existing is not None and not _can_restart_pr_monitoring(existing):
            return existing, False
        _enforce_pr_research_limits(team, user, existing)
        run_started_at = timezone.now()
        if existing is not None:
            return (
                _restart_failed_report(
                    team=team,
                    report=existing,
                    pr=pr,
                    actor=actor,
                    run_started_at=run_started_at,
                    admission=admission,
                ),
                True,
            )
        report = SignalReport.objects.create(
            team=team,
            scout_idempotency_key=key,
            created_by=user,
            user_authored=True,
            status=SignalReport.Status.IN_PROGRESS,
            title=f"Monitor {pr.title}",
            summary=f"Post-merge impact check for {pr.repository}#{pr.number}.",
            last_run_at=run_started_at,
        )
        _bind_pr_monitoring_pass(
            team=team,
            report_id=report.id,
            run_started_at=run_started_at,
            admission=admission,
            is_new_report=True,
        )
        report.refresh_from_db(fields=["self_driving_funding"])
        claim = create_claim(report, actor)
        SignalReportArtefact.append_status(
            team_id=team.id,
            report_id=str(report.id),
            content=RepoSelectionResult(
                repository=pr.repository,
                reason="Repository of the pull request selected for monitoring.",
                autostart_eligible=False,
            ),
            attribution=actor,
            reevaluate_autostart=False,
        )
        SignalReportArtefact.append_status(
            team_id=team.id,
            report_id=str(report.id),
            content=SuggestedReviewers(root=[SuggestedReviewerEntry(user_uuid=str(user.uuid))]),
            attribution=actor,
            reviewer_proposal=ReviewerProposal(expected_state=ReviewerState(), source="pr_monitoring"),
            reevaluate_autostart=False,
        )
        link_pull_request(
            report=report, details=pr.details(), actor=actor, claim_id=str(claim.claim_id), notify_reviewers=False
        )
        _append_pending_check_authoring(team.id, report.id, actor)
        distinct_id = user.distinct_id or str(user.uuid)
        transaction.on_commit(
            lambda: posthoganalytics.capture(
                distinct_id=distinct_id,
                event="signals_pr_monitoring_requested",
                properties={
                    "team_id": team.id,
                    "report_id": str(report.id),
                    "pr_state": pr.state,
                },
            )
        )
    return report, True


def _enforce_pr_research_limits(team: Team, user: User, report: SignalReport | None) -> None:
    from products.signals.backend.scout_harness.tools.report_author import (  # noqa: PLC0415 -- scout_harness imports temporal, which imports monitor_pr
        USER_REPORT_DAILY_LIMIT,
        UserReportAuthor,
        user_report_limit_resets_at,
    )

    retry_after = max(1, int((user_report_limit_resets_at(team) - timezone.now()).total_seconds()))
    if report is None:
        author = UserReportAuthor(
            user_id=user.id,
            user_distinct_id=user.distinct_id or str(user.uuid),
            request_attribution=ArtefactAttribution.from_user(user.id),
        )
        if author.preflight_skip_reason(team):
            raise PRMonitoringLimitExceeded("You've reached today's limit for reports.", retry_after=retry_after)
    attempts_today = SignalReportArtefact.objects.filter(
        team_id=team.id,
        type=SignalReportArtefact.ArtefactType.CHECK_AUTHORING,
        created_by_id=user.id,
        created_at__gte=team_day_start(team),
    )
    if attempts_today.count() >= USER_REPORT_DAILY_LIMIT or (
        report is not None and attempts_today.filter(report_id=report.id).count() >= PR_RESEARCH_DAILY_ATTEMPT_LIMIT
    ):
        raise PRMonitoringLimitExceeded(
            "You've reached today's limit for PR research attempts.", retry_after=retry_after
        )


def request_pr_monitoring(
    *,
    team: Team,
    user: User,
    pr_url: str,
    note: str = "",
    token_scopes: Sequence[str] | None = None,
) -> PRMonitoringRequestResult:
    from products.signals.backend.temporal.monitor_pr import (
        start_pr_monitoring,  # noqa: PLC0415 -- keeps Temporal client off model import path
    )

    team = team.parent_team or team
    _ensure_pr_monitoring_permitted(team, user)

    key = monitor_key(user.id, pr_url)
    report = (
        SignalReport.objects.filter(team_id=team.id, scout_idempotency_key=key)
        .exclude(status=SignalReport.Status.DELETED)
        .first()
    )
    started = False
    if report is None or _can_restart_pr_monitoring(report):
        _enforce_pr_research_limits(team, user, report)
        admission = prepare_self_driving_admission(team)
        if admission.gate.limited and admission.gate.enforced:
            raise PRMonitoringLimitExceeded("This project has reached its self-driving usage limit.")
        try:
            pr = load_pull_request(team.id, pr_url)
        except (EgressBudgetExhausted, GitHubIntegrationError) as error:
            raise PRMonitoringUnavailable("GitHub is temporarily unavailable. Try again shortly.") from error
        report, started = prepare_monitoring(team=team, user=user, pr=pr, admission=admission)

    if report_has_active_pr_monitoring_pass(report):
        inputs = MonitorPRInput(
            team_id=team.id,
            report_id=str(report.id),
            user_id=user.id,
            pr_url=pr_url,
            note=note.strip()[:4000],
            attempt_key=attempt_key(report),
            token_scopes=tuple(token_scopes) if token_scopes is not None else None,
        )
        try:
            async_to_sync(start_pr_monitoring)(inputs)
        except Exception as error:
            logger.exception("signals_monitor_pr_dispatch_failed", team_id=team.id, report_id=str(report.id))
            if started:
                fail_monitoring_research(inputs)
            raise PRMonitoringUnavailable(
                "Could not start PR research. Retry this request; the report has been saved.", report_id=report.id
            ) from error
    return PRMonitoringRequestResult(
        report_id=report.id,
        report_url=build_bare_report_url(team.id, report.id),
        status=report.status,
        idempotent_replay=not started,
    )


class PRMonitoringCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(default="Post-merge check", min_length=1, max_length=200)
    kind: Literal["metric_threshold"] = "metric_threshold"
    config: MetricThresholdConfig
    soak_hours: int = Field(default=24, ge=1, le=720)
    run_interval_minutes: int | None = None

    def as_spec(self) -> CheckSpec:
        return CheckSpec.model_validate(self.model_dump(mode="json", exclude_none=True))


class PRMonitoringOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    inspected_commit: str
    metric: ReportMetric | None = None
    check: PRMonitoringCheck | None = None
    unavailable: bool = False

    @model_validator(mode="after")
    def coherent_measurement(self) -> "PRMonitoringOutput":
        if self.unavailable:
            if self.metric is not None or self.check is not None:
                raise ValueError("An unavailable measurement must not include a metric or check")
            return self
        if self.metric is None or self.check is None:
            raise ValueError("Provide a primary metric and monitoring check, or set unavailable to true")
        if self.metric.role != "primary":
            raise ValueError("Provide one primary metric and a new metric_threshold check")
        self.check.as_spec()
        config = self.check.config
        if config.query is not None:
            raise ValueError("Reference the primary metric with metric_id instead of repeating query on check.config")
        if config.metric_id != self.metric.metric_id or config.monitoring is None:
            raise ValueError("The check must monitor the primary metric by metric_id")
        authored_monitoring_interval_minutes(self.check.soak_hours * 60, self.check.run_interval_minutes)
        validate_metric_check_for_write(
            config.model_copy(
                update={
                    "query": self.metric.query,
                    "metric_kind": self.metric.kind,
                    "value_format": self.metric.value_format,
                    "unit": self.metric.unit,
                }
            )
        )
        return self


def _reconcile_researched_pr(report: SignalReport, pr: MonitoredPullRequest, actor: ArtefactAttribution) -> None:
    from products.signals.backend.tasks import (
        refresh_linked_pull_request_state,  # noqa: PLC0415 -- keeps Celery task module off import path
    )

    active_claim = get_active_claim(team_id=report.team_id, report_id=str(report.id))
    link_pull_request(
        report=report,
        details=pr.details(),
        actor=actor,
        claim_id=str(active_claim.claim_id) if active_claim else None,
        notify_reviewers=False,
    )
    apply_report_completion(report)
    if pr.state != "merged":
        transaction.on_commit(
            partial(refresh_linked_pull_request_state.delay, report.team_id, pr.url),
            robust=True,
        )


def _strip_embedded_query_metadata(value: object) -> Any:
    if isinstance(value, Mapping):
        return {
            key: _strip_embedded_query_metadata(item) for key, item in value.items() if key not in _STRIPPED_QUERY_KEYS
        }
    if isinstance(value, list):
        return [_strip_embedded_query_metadata(item) for item in value]
    return value


def _sanitized_measurement(output: PRMonitoringOutput, pr: MonitoredPullRequest) -> tuple[dict[str, Any], CheckSpec]:
    assert output.metric is not None and output.check is not None
    raw_unit = output.metric.unit
    safe_unit = raw_unit if isinstance(raw_unit, str) and re.fullmatch(r"ms|s|[A-Z]{3}", raw_unit) else None
    metric = ReportMetric(
        metric_id="primary_metric",
        title=f"Impact metric for {pr.repository}#{pr.number}",
        kind=output.metric.kind,
        role="primary",
        value_format=output.metric.value_format,
        unit=safe_unit,
        query=_strip_embedded_query_metadata(output.metric.query),
    )
    check = output.check.model_copy(
        update={
            "title": f"Post-merge check for {pr.repository}#{pr.number}",
            "config": output.check.config.model_copy(update={"metric_id": "primary_metric", "unit": safe_unit}),
        }
    )
    return metric.model_dump(mode="json", exclude_none=True), check.as_spec()


def _assert_initiator_may_read_metric(
    report: SignalReport, initiator: User, inputs: MonitorPRInput, metric_payload: dict[str, Any]
) -> None:
    policy = ReportMetricAccessPolicy(request=None, team=report.team, user=initiator, token_scopes=inputs.token_scopes)
    if not policy.may_read_query(metric_payload):
        raise ValueError("The initiating user cannot access the selected metric query")


def finish_monitoring_research(inputs: MonitorPRInput, output: PRMonitoringOutput, pr: MonitoredPullRequest) -> None:
    if output.inspected_commit != pr.head_sha:
        raise ValueError("The research did not inspect the requested pull request commit")
    with transaction.atomic():
        report = (
            SignalReport.objects.select_for_update(of=("self",), no_key=True)
            .select_related("team__organization")
            .get(team_id=inputs.team_id, id=inputs.report_id)
        )
        if not report_has_active_pr_monitoring_pass(report) or attempt_key(report) != inputs.attempt_key:
            return
        initiator = require_pr_monitoring_initiator(report.team, inputs.user_id)
        actor = ArtefactAttribution.system()
        if output.unavailable:
            report.save(
                update_fields=report.transition_to(
                    SignalReport.Status.PENDING_INPUT,
                    error="PR monitoring research could not identify a measurable metric.",
                )
            )
            return
        if not team_report_monitoring_enabled(inputs.team_id) or not team_report_metrics_enabled(inputs.team_id):
            raise ValueError("Monitoring is no longer enabled for this project")
        metric_payload, check_spec = _sanitized_measurement(output, pr)
        _assert_initiator_may_read_metric(report, initiator, inputs, metric_payload)
        report.metrics = [metric_payload]
        report.save(
            update_fields=[
                "metrics",
                *report.transition_to(
                    SignalReport.Status.READY,
                    title=f"Monitor {pr.title}",
                    summary=f"Post-merge impact check for {pr.repository}#{pr.number}.",
                ),
            ]
        )
        result = create_checks_from_specs(report=report, specs=[check_spec], attribution=actor)
        if not result.applied or not result.created:
            raise ValueError("Could not create the monitoring check")
        SignalReportArtefact.append_status(
            team_id=report.team_id,
            report_id=str(report.id),
            content=CheckAuthoringStatus(status="succeeded", reason="PR monitoring measurement created."),
            attribution=actor,
        )
        _reconcile_researched_pr(report, pr, actor)


def fail_monitoring_research(inputs: MonitorPRInput) -> None:
    with transaction.atomic():
        report = (
            SignalReport.objects.select_for_update(of=("self",), no_key=True)
            .filter(team_id=inputs.team_id, id=inputs.report_id)
            .first()
        )
        if (
            report is not None
            and report_has_active_pr_monitoring_pass(report)
            and attempt_key(report) == inputs.attempt_key
        ):
            report.save(
                update_fields=report.transition_to(
                    SignalReport.Status.FAILED,
                    error="PR monitoring research failed before a measurement was saved.",
                )
            )


def fail_stale_pr_monitoring(team_id: int, report_id: str, *, started_before: datetime) -> bool:
    with transaction.atomic():
        report = (
            SignalReport.objects.select_for_update(of=("self",), no_key=True)
            .filter(
                team_id=team_id,
                id=report_id,
                status=SignalReport.Status.IN_PROGRESS,
                last_run_at__lt=started_before,
            )
            .first()
        )
        if report is None or not is_pr_monitoring_attempt(
            report.scout_idempotency_key,
            report.self_driving_funding,
            report.last_run_at,
            run_count=report.run_count,
        ):
            return False
        report.save(
            update_fields=report.transition_to(
                SignalReport.Status.FAILED,
                error="PR monitoring research stopped before a measurement was saved.",
            )
        )
        return True
