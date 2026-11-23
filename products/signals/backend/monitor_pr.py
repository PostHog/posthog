import re
import hashlib
from datetime import datetime
from typing import Literal

from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

import posthoganalytics
from pydantic import BaseModel, ConfigDict, Field, model_validator

from posthog.dataclasses import frozen
from posthog.egress.limiter.policies import Priority
from posthog.integrations import IntegrationManager
from posthog.models import Team, User
from posthog.models.github_integration_base import GitHubIntegrationError
from posthog.models.integration import GitHubIntegration

from products.signals.backend.artefact_schemas import (
    CheckAuthoringStatus,
    NoteArtefact,
    SuggestedReviewerEntry,
    SuggestedReviewers,
)
from products.signals.backend.models import ArtefactAttribution, SignalReport, SignalReportArtefact
from products.signals.backend.pull_requests import apply_report_completion, link_pull_request, update_pull_request_state
from products.signals.backend.report_assignments import PullRequestDetails, create_claim
from products.signals.backend.report_check_authoring import create_checks_from_specs
from products.signals.backend.report_checks import (
    MAX_CHECK_HORIZON,
    CheckSpec,
    MetricThresholdConfig,
    authored_monitoring_interval_minutes,
    validate_metric_check_for_write,
)
from products.signals.backend.report_claims import get_active_claim
from products.signals.backend.report_content_gates import team_report_metrics_enabled, team_report_monitoring_enabled
from products.signals.backend.report_metrics import ReportMetric
from products.tasks.backend.facade.repo_selection_types import RepoSelectionResult


@frozen
class MonitorPRInput:
    team_id: int
    report_id: str
    user_id: int
    pr_url: str
    note: str = ""
    poll_only: bool = False


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


class InvalidPullRequest(ValueError):
    pass


def pr_identity(pr_url: str) -> tuple[str, int]:
    match = re.fullmatch(r"https://github\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)/pull/([1-9][0-9]*)/?", pr_url)
    if match is None or ".." in match[1] or len(match[1]) > 200 or int(match[2]) > 2**63 - 1:
        raise InvalidPullRequest("Use a GitHub pull request URL, such as https://github.com/owner/repo/pull/123.")
    return match[1].lower(), int(match[2])


def registered_github_for_repository(
    team_id: int, repository: str, *, source: str, priority: Priority = Priority.NORMAL
) -> GitHubIntegration | None:
    target = repository.lower()
    for integration in sorted(IntegrationManager.github.oauth.list(team_id), key=lambda row: row.id):
        github = GitHubIntegration(integration, source=source, priority=priority)
        repositories = {
            str(repo["full_name"]).lower()
            for repo in github.list_all_cached_repositories()
            if isinstance(repo, dict) and repo.get("full_name")
        }
        if target in repositories:
            return github
    return None


def _pull_request_state_and_merge_time(result: dict[str, object], *, allow_closed: bool) -> tuple[str, datetime | None]:
    raw_state = result.get("state")
    if result.get("merged"):
        state = "merged"
    elif raw_state == "open" and result.get("draft"):
        state = "draft"
    elif isinstance(raw_state, str):
        state = raw_state
    else:
        state = ""
    if state not in ({"open", "draft", "merged", "closed"} if allow_closed else {"open", "draft", "merged"}):
        raise InvalidPullRequest("This pull request was closed without merging.")
    raw_merged_at = result.get("merged_at")
    merged_at = parse_datetime(raw_merged_at) if isinstance(raw_merged_at, str) and raw_merged_at else None
    if state == "merged":
        now = timezone.now()
        if merged_at is None or timezone.is_naive(merged_at) or merged_at > now:
            raise InvalidPullRequest("GitHub did not return a valid merge timestamp. Try again shortly.")
        if not allow_closed and merged_at <= now - MAX_CHECK_HORIZON:
            raise InvalidPullRequest(
                f"This pull request merged more than {MAX_CHECK_HORIZON.days} days ago and is outside the monitoring window."
            )
    return state, merged_at


def load_pull_request(
    team_id: int, pr_url: str, *, priority: Priority = Priority.NORMAL, allow_closed: bool = False
) -> MonitoredPullRequest:
    repository, number = pr_identity(pr_url)
    github = registered_github_for_repository(team_id, repository, source="signals_monitor_pr", priority=priority)
    if github is None:
        raise InvalidPullRequest("Connect a GitHub integration that includes this repository.")
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
    state, merged_at = _pull_request_state_and_merge_time(result, allow_closed=allow_closed)
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


def monitor_key(user_id: int, pr_url: str) -> str:
    repository, number = pr_identity(pr_url)
    digest = hashlib.sha256(f"{repository}:{number}".encode()).hexdigest()
    return f"monitor-pr:{user_id}:{digest}"


def prepare_monitoring(*, team: Team, user: User, pr: MonitoredPullRequest, note: str) -> tuple[SignalReport, bool]:
    actor = ArtefactAttribution.from_user(user.id)
    key = monitor_key(user.id, pr.url)
    with transaction.atomic():
        SignalReport.objects.filter(team=team, scout_idempotency_key=key, status=SignalReport.Status.DELETED).update(
            scout_idempotency_key=None
        )
        report, created = SignalReport.objects.get_or_create(
            team=team,
            scout_idempotency_key=key,
            defaults={
                "created_by": user,
                "user_authored": True,
                "status": SignalReport.Status.IN_PROGRESS,
                "title": f"Monitor {pr.title}",
                "summary": note,
                "last_run_at": timezone.now(),
            },
        )
        if not created:
            report = SignalReport.objects.select_for_update().get(id=report.id)
            if report.status != SignalReport.Status.FAILED:
                return report, False
            report.status = SignalReport.Status.IN_PROGRESS
            report.error = None
            report.last_run_at = timezone.now()
            report.save(update_fields=["status", "error", "last_run_at", "updated_at"])
            active_claim = get_active_claim(team_id=team.id, report_id=str(report.id))
            link_pull_request(
                report=report,
                details=pr.details(),
                actor=actor,
                claim_id=str(active_claim.claim_id) if active_claim else None,
                notify_reviewers=False,
            )
            return report, True
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
            reevaluate_autostart=False,
        )
        if note:
            SignalReportArtefact.add_log(
                team_id=team.id, report_id=str(report.id), content=NoteArtefact(note=note), attribution=actor
            )
        link_pull_request(
            report=report, details=pr.details(), actor=actor, claim_id=str(claim.claim_id), notify_reviewers=False
        )
        SignalReportArtefact.append_status(
            team_id=team.id,
            report_id=str(report.id),
            content=CheckAuthoringStatus(
                status="failed", reason="PR monitoring research has not produced a measurement yet."
            ),
            attribution=ArtefactAttribution.system(),
        )
        distinct_id = user.distinct_id or str(user.uuid)
        transaction.on_commit(
            lambda: posthoganalytics.capture(
                distinct_id=distinct_id,
                event="signals_pr_monitoring_requested",
                properties={
                    "team_id": team.id,
                    "report_id": str(report.id),
                    "pr_state": pr.state,
                    "has_note": bool(note),
                },
            )
        )
    return report, True


class PRMonitoringCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)
    rationale: str = Field(default="", max_length=2000)
    kind: Literal["metric_threshold"] = "metric_threshold"
    config: MetricThresholdConfig
    soak_hours: int = Field(default=24, ge=1, le=720)
    run_interval_minutes: int | None = None

    def as_spec(self) -> CheckSpec:
        return CheckSpec.model_validate(self.model_dump(mode="json", exclude_none=True))


class PRMonitoringOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=200)
    summary: str = Field(min_length=1, max_length=20000)
    inspected_commit: str
    metric: ReportMetric | None = None
    check: PRMonitoringCheck | None = None
    unavailable_reason: str | None = Field(default=None, min_length=1, max_length=2000)

    @model_validator(mode="after")
    def coherent_measurement(self) -> "PRMonitoringOutput":
        if self.unavailable_reason:
            if self.metric is not None or self.check is not None:
                raise ValueError("An unavailable measurement must not include a metric or check")
            return self
        if self.metric is None or self.check is None:
            raise ValueError("Provide a primary metric and monitoring check, or explain why measurement is unavailable")
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


def finish_monitoring_research(inputs: MonitorPRInput, output: PRMonitoringOutput, pr: MonitoredPullRequest) -> None:
    if output.inspected_commit != pr.head_sha:
        raise ValueError("The research did not inspect the requested pull request commit")
    with transaction.atomic():
        report = SignalReport.objects.select_for_update().get(team_id=inputs.team_id, id=inputs.report_id)
        if report.status != SignalReport.Status.IN_PROGRESS:
            return
        actor = ArtefactAttribution.system()
        if output.unavailable_reason:
            report.save(
                update_fields=report.transition_to(
                    SignalReport.Status.PENDING_INPUT,
                    title=output.title,
                    summary=output.summary,
                    error=output.unavailable_reason,
                )
            )
            return
        if not team_report_monitoring_enabled(inputs.team_id) or not team_report_metrics_enabled(inputs.team_id):
            raise ValueError("Monitoring is no longer enabled for this project")
        assert output.metric is not None and output.check is not None
        report.metrics = [output.metric.model_dump(mode="json", exclude_none=True)]
        report.save(
            update_fields=[
                "metrics",
                *report.transition_to(SignalReport.Status.READY, title=output.title, summary=output.summary),
            ]
        )
        result = create_checks_from_specs(report=report, specs=[output.check.as_spec()], attribution=actor)
        if not result.applied or not result.created:
            raise ValueError("Could not create the monitoring check")
        SignalReportArtefact.append_status(
            team_id=report.team_id,
            report_id=str(report.id),
            content=CheckAuthoringStatus(status="succeeded", reason="PR monitoring measurement created."),
            attribution=actor,
        )
        apply_report_completion(report)


def refresh_monitored_pr(inputs: MonitorPRInput) -> bool:
    if not SignalReport.objects.filter(
        team_id=inputs.team_id, id=inputs.report_id, status=SignalReport.Status.READY
    ).exists():
        return False
    pr = load_pull_request(inputs.team_id, inputs.pr_url, priority=Priority.BATCH, allow_closed=True)
    update_pull_request_state(
        team_id=inputs.team_id, repository=pr.repository, number=pr.number, state=pr.state, merged_at=pr.merged_at
    )
    return pr.state in {"open", "draft"}


def fail_monitoring_research(inputs: MonitorPRInput) -> None:
    with transaction.atomic():
        report = SignalReport.objects.select_for_update().filter(team_id=inputs.team_id, id=inputs.report_id).first()
        if report is not None and report.status == SignalReport.Status.IN_PROGRESS:
            report.save(
                update_fields=report.transition_to(
                    SignalReport.Status.FAILED,
                    error="PR monitoring research failed before a measurement was saved.",
                )
            )
