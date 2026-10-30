import hashlib
from collections.abc import Mapping
from dataclasses import asdict
from datetime import datetime
from uuid import UUID

from django.db import connection, transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from pydantic import TypeAdapter, ValidationError
from pydantic.dataclasses import dataclass
from temporalio.exceptions import ActivityError, ApplicationError

from posthog.models import HealthIssue, OrganizationMembership, Team

from products.notifications.backend.facade.api import (
    NotificationData,
    NotificationType,
    RecipientsResolver,
    TargetType,
    create_notification,
)
from products.tasks.backend.facade import api as tasks_facade
from products.tasks.backend.facade.contracts import AgentStartupFailure

RESEARCH_STARTUP_FAILURE = "ResearchAgentStartupFailed"
RESEARCH_SANDBOX_UNAVAILABLE_ERROR_TYPE = "ResearchSandboxUnavailable"
ISSUE_KIND = "signals_agent_startup_failed"
SCOPE_KEYS = ["repository", "provider", "runtime"]


@dataclass(frozen=True, kw_only=True)
class ResearchStartupFailure:
    failure: AgentStartupFailure
    task_id: UUID
    run_id: UUID
    repository: str


_failure_adapter = TypeAdapter(ResearchStartupFailure)


def research_startup_failure(error: Exception) -> ResearchStartupFailure | None:
    cause = error.cause if isinstance(error, ActivityError) else error
    if (
        not isinstance(cause, ApplicationError)
        or cause.type not in (RESEARCH_STARTUP_FAILURE, RESEARCH_SANDBOX_UNAVAILABLE_ERROR_TYPE)
        or not cause.details
    ):
        return None
    try:
        return _failure_adapter.validate_python(cause.details[0])
    except ValidationError:
        return None


def startup_failure_message(failure: AgentStartupFailure) -> str:
    if failure.reason == "credential_unavailable":
        return "Research could not start because the agent could not obtain its credentials. Follow the provider's reconnect or token-relay instructions in the linked run, then retry."
    if failure.reason == "credential_service_unavailable":
        return "Research could not start because the provider's credential service was temporarily unavailable. Retry from the linked run."
    explanations = {
        "proxy_invalid": "The agent's proxy configuration is invalid.",
        "managed_settings_invalid": "The agent's managed settings are invalid.",
        "shell_tool_missing": "A shell tool required by the agent is unavailable.",
        "gateway_signin_required": "The agent needs to sign in to its provider.",
        "gateway_access_denied": "The provider denied access while loading the agent's managed settings.",
        "org_pin_api_key_conflict": "The agent's API key conflicts with its organization settings.",
        "org_pin_mismatch": "The agent's organization settings do not match its credentials.",
        "cli_version_too_old": "The agent requires a newer provider runtime.",
        "bypass_root": "The provider rejected the agent's permission configuration.",
        "sandbox_required_unavailable": "The repository's Claude Code settings require a sandbox that is not available in this environment.",
        "provider_not_allowed": "The agent's managed settings do not allow the configured provider.",
        "org_config_refused": "The provider refused the organization's configuration for this sign-in.",
    }
    explanation = explanations.get(failure.reason or "") if failure.provider == "claude" else None
    if explanation and failure.retryability == "requires_action":
        return f"Research could not start. {explanation} Check the linked run and update the configuration before retrying."
    return "Research stopped before the agent could start. The provider did not report a confirmed cause. Check the linked run for details before retrying."


def report_startup_failure(failure: ResearchStartupFailure) -> dict[str, object]:
    return {
        **asdict(failure.failure),
        "task_id": str(failure.task_id),
        "run_id": str(failure.run_id),
        "message": startup_failure_message(failure.failure),
    }


class ProjectOrganizationAdminRecipients(RecipientsResolver):
    def resolve(self, target_type: TargetType, target_id: str, team_id: int | None) -> list[int]:
        team = Team.objects.get(id=team_id)
        admins = OrganizationMembership.objects.filter(
            organization_id=team.organization_id, level__gte=OrganizationMembership.Level.ADMIN
        ).values_list("user_id", flat=True)
        return list(team.all_users_with_access().filter(id__in=admins).values_list("id", flat=True))


def _lock_scope(team_id: int, scope_hash: str) -> None:
    key = int.from_bytes(hashlib.sha256(f"{ISSUE_KIND}:{team_id}:{scope_hash}".encode()).digest()[:8], signed=True)
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(%s)", [key])


def _started_at(
    state: Mapping[str, object], fallback: datetime | None = None, *, key: str = "startup_started_at"
) -> datetime | None:
    value = state.get(key)
    try:
        parsed = parse_datetime(value) if isinstance(value, str) else None
    except ValueError:
        parsed = None
    return parsed if parsed is not None and timezone.is_aware(parsed) else fallback


def notify_research_startup_failure(team_id: int, report_id: str, failure: ResearchStartupFailure) -> None:
    run = tasks_facade.get_task_run(failure.run_id, team_id=team_id)
    if run is None or run.task_id != failure.task_id:
        return
    attempt = run.state.get("agent_startup_attempt")
    started_at = (
        _started_at(attempt, run.created_at, key="started_at")
        if isinstance(attempt, dict)
        else _started_at(run.state, run.created_at)
    )
    if started_at is None:
        return
    runtime = (
        attempt.get("runtime", "unknown") if isinstance(attempt, dict) else run.state.get("startup_runtime", "unknown")
    )
    if runtime not in ("gvisor", "vm"):
        runtime = "unknown"
    scope = {"repository": failure.repository.lower(), "provider": failure.failure.provider, "runtime": runtime}
    scope_hash = HealthIssue.compute_unique_hash(ISSUE_KIND, scope, SCOPE_KEYS)
    issue_payload = {**scope, "category": failure.failure.reason or failure.failure.phase}
    issue_hash = HealthIssue.compute_unique_hash(ISSUE_KIND, issue_payload, [*SCOPE_KEYS, "category"])
    with transaction.atomic():
        _lock_scope(team_id, scope_hash)
        successful_at = tasks_facade.latest_agent_startup_success(
            team_id=team_id, repository=scope["repository"], provider=scope["provider"], runtime=scope["runtime"]
        )
        if successful_at is not None:
            recovered = HealthIssue.objects.filter(
                team_id=team_id,
                kind=ISSUE_KIND,
                status=HealthIssue.Status.ACTIVE,
                payload__repository=scope["repository"],
                payload__provider=scope["provider"],
                payload__runtime=scope["runtime"],
            )
            for recovered_issue in recovered:
                previous_started_at = _started_at(recovered_issue.payload)
                if previous_started_at is not None and previous_started_at <= successful_at:
                    recovered_issue.status = HealthIssue.Status.RESOLVED
                    recovered_issue.resolved_at = timezone.now()
                    recovered_issue.save(update_fields=["status", "resolved_at", "updated_at"])
        if successful_at is not None and successful_at >= started_at:
            return
        issue = HealthIssue.objects.filter(
            team_id=team_id, kind=ISSUE_KIND, unique_hash=issue_hash, status=HealthIssue.Status.ACTIVE
        ).first()
        if issue is None:
            issue = HealthIssue.objects.create(
                team_id=team_id,
                kind=ISSUE_KIND,
                unique_hash=issue_hash,
                severity=HealthIssue.Severity.WARNING,
                payload={**issue_payload, "startup_started_at": started_at.isoformat(), "report_id": report_id},
            )
        elif started_at > (_started_at(issue.payload) or issue.created_at):
            issue.payload.update(startup_started_at=started_at.isoformat(), report_id=report_id)
            issue.save(update_fields=["payload", "updated_at"])
    create_notification(
        NotificationData(
            team_id=team_id,
            notification_type=NotificationType.PIPELINE_FAILURE,
            title="Research agent could not start",
            body=startup_failure_message(failure.failure),
            target_type=TargetType.TEAM,
            target_id=str(team_id),
            source_url=f"/project/{team_id}/inbox/{report_id}",
            idempotency_key=f"{ISSUE_KIND}:{issue.id}",
            resolver=ProjectOrganizationAdminRecipients(),
        )
    )


def reconcile_research_startups(team_id: int, repository: str) -> None:
    issues = HealthIssue.objects.filter(
        team_id=team_id,
        kind=ISSUE_KIND,
        status=HealthIssue.Status.ACTIVE,
        payload__repository=repository.lower(),
    )
    for issue in issues:
        with transaction.atomic():
            _lock_scope(team_id, HealthIssue.compute_unique_hash(ISSUE_KIND, issue.payload, SCOPE_KEYS))
            issue.refresh_from_db()
            started_at = _started_at(issue.payload)
            if issue.status != HealthIssue.Status.ACTIVE or started_at is None:
                continue
            successful_at = tasks_facade.latest_agent_startup_success(
                team_id=team_id,
                repository=repository.lower(),
                provider=issue.payload["provider"],
                runtime=issue.payload["runtime"],
            )
            if successful_at is not None and successful_at >= started_at:
                issue.status = HealthIssue.Status.RESOLVED
                issue.resolved_at = timezone.now()
                issue.save(update_fields=["status", "resolved_at", "updated_at"])
