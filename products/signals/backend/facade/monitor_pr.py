from uuid import UUID

from django.utils import timezone

import structlog
from asgiref.sync import async_to_sync

from posthog.dataclasses import frozen
from posthog.egress.github.transport import GitHubRateLimitError
from posthog.egress.transport.transport import EgressBudgetExhausted
from posthog.models import Team, User
from posthog.models.github_integration_base import GitHubIntegrationError

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.signals.backend.models import ArtefactAttribution, SignalReport
from products.signals.backend.monitor_pr import (
    InvalidPullRequest as InvalidPullRequest,
    MonitorPRInput,
    load_pull_request,
    monitor_key,
    prepare_monitoring,
)
from products.signals.backend.quota import self_driving_quota_gate
from products.signals.backend.report_content_gates import (
    team_pr_monitoring_enabled,
    team_report_metrics_enabled,
    team_report_monitoring_enabled,
)
from products.signals.backend.report_urls import build_bare_report_url
from products.signals.backend.scout_harness.tools.report_author import UserReportAuthor, user_report_limit_resets_at
from products.signals.backend.temporal.monitor_pr import start_pr_monitoring

logger = structlog.get_logger(__name__)
REPORT_STATUS_CHOICES = tuple(SignalReport.Status.choices)


@frozen
class PRMonitoringRequestResult:
    report_id: UUID
    report_url: str
    status: str
    idempotent_replay: bool


class PRMonitoringLimitExceeded(Exception):
    def __init__(self, message: str, *, retry_after: int | None = None):
        super().__init__(message)
        self.retry_after = retry_after


class PRMonitoringUnavailable(Exception):
    def __init__(self, message: str, *, report_id: UUID | None = None):
        super().__init__(message)
        self.report_id = report_id


def request_pr_monitoring(*, team: Team, user: User, pr_url: str, note: str = "") -> PRMonitoringRequestResult:
    if (
        not team_pr_monitoring_enabled(team.id)
        or not team_report_monitoring_enabled(team.id)
        or not team_report_metrics_enabled(team.id)
    ):
        raise PermissionError("PR monitoring is not enabled for this project.")
    if not team.organization.is_ai_data_processing_approved:
        raise PermissionError("Enable AI data processing for this organization to monitor a PR.")
    if not UserAccessControl(
        user=user, team=team, organization_id=str(team.organization_id)
    ).check_access_level_for_resource("task", "editor"):
        raise PermissionError("You need permission to start tasks in this project.")

    key = monitor_key(user.id, pr_url)
    report = SignalReport.objects.filter(team_id=team.id, scout_idempotency_key=key).first()
    created = False
    if report is None:
        author = UserReportAuthor(
            user_id=user.id,
            user_distinct_id=user.distinct_id or str(user.uuid),
            request_attribution=ArtefactAttribution.from_user(user.id),
        )
        if author.preflight_skip_reason(team):
            raise PRMonitoringLimitExceeded(
                "You've reached today's limit for reports.",
                retry_after=max(1, int((user_report_limit_resets_at(team) - timezone.now()).total_seconds())),
            )
        gate = self_driving_quota_gate(team)
        if gate.limited and gate.enforced:
            raise PRMonitoringLimitExceeded("This project has reached its self-driving usage limit.")
        try:
            pr = load_pull_request(team.id, pr_url)
        except (GitHubRateLimitError, EgressBudgetExhausted, GitHubIntegrationError) as error:
            raise PRMonitoringUnavailable("GitHub is temporarily unavailable. Try again shortly.") from error
        report, created = prepare_monitoring(team=team, user=user, pr=pr, note=note)

    if report.status == SignalReport.Status.IN_PROGRESS:
        inputs = MonitorPRInput(
            team_id=team.id,
            report_id=str(report.id),
            user_id=user.id,
            pr_url=pr_url,
            note=report.summary or "",
        )
        try:
            async_to_sync(start_pr_monitoring)(inputs)
        except Exception as error:
            logger.exception("signals_monitor_pr_dispatch_failed", team_id=team.id, report_id=str(report.id))
            raise PRMonitoringUnavailable(
                "Could not start PR research. Retry this request; the report has been saved.", report_id=report.id
            ) from error
    return PRMonitoringRequestResult(
        report_id=report.id,
        report_url=build_bare_report_url(team.id, report.id),
        status=report.status,
        idempotent_replay=not created,
    )
