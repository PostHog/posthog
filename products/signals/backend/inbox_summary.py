from datetime import datetime, timedelta

from django.db.models import Exists, OuterRef, Q, QuerySet, TextField, Value
from django.db.models.functions import Cast, Concat, JSONArray
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from posthog.dataclasses import frozen
from posthog.egress.github.transport import GitHubEgressBudgetExhausted, GitHubRateLimitError
from posthog.egress.limiter.policies import Priority
from posthog.models.github_integration_base import GitHubIntegrationBase, GitHubIntegrationError
from posthog.models.integration import GitHubIntegration
from posthog.models.organization import OrganizationMembership
from posthog.models.user_integration import UserGitHubIntegration

from products.signals.backend.artefact_schemas import TASK_RUN_TYPE_IMPLEMENTATION
from products.signals.backend.models import SignalReportPullRequest, SignalReportTask

INBOX_SUMMARY_PERIOD = timedelta(days=7)


@frozen
class GitHubParticipant:
    id: int
    login: str


def generated_pull_requests(team_id: int, *, task_filter: Q | None = None) -> QuerySet[SignalReportPullRequest]:
    # Neither a manually attached PR nor an API-writable task output proves that the task created it.
    implementations = SignalReportTask.objects.filter(
        team_id=team_id,
        relationship=TASK_RUN_TYPE_IMPLEMENTATION,
        task__team_id=team_id,
        task__runs__team_id=team_id,
    ).filter(
        Q(task__runs__state__verified_pr_urls__contains=JSONArray(OuterRef("url")))
        | Q(
            task__runs__state__verified_pr_urls__contains=JSONArray(
                Concat(
                    Value("https://github.com/"),
                    OuterRef("repository"),
                    Value("/pull/"),
                    Cast(OuterRef("number"), TextField()),
                    output_field=TextField(),
                )
            )
        )
    )
    if task_filter is not None:
        implementations = implementations.filter(task_filter)
    return SignalReportPullRequest.objects.for_team(team_id).filter(Exists(implementations))


def github_datetime(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = parse_datetime(value)
    except ValueError:
        return None
    return parsed if parsed is not None and timezone.is_aware(parsed) else None


def human_participant(user: object) -> GitHubParticipant | None:
    if not isinstance(user, dict):
        raise GitHubIntegrationError("Missing pull request participant")
    login = user.get("login")
    if user.get("type") == "Bot" or (isinstance(login, str) and login.lower().endswith("[bot]")):
        return None
    user_id = user["id"]
    if (
        user.get("type") != "User"
        or type(user_id) is not int
        or user_id <= 0
        or not isinstance(login, str)
        or not login
        or len(login) > 255
    ):
        raise GitHubIntegrationError("Unknown pull request participant")
    return GitHubParticipant(id=user_id, login=login)


def github_for_generated_pull_request(
    *, team_id: int, repository: str, pr_number: int, pr_url: str
) -> GitHubIntegrationBase | None:
    verified_url = f"https://github.com/{repository.lower()}/pull/{pr_number}"
    implementations = (
        SignalReportTask.objects.filter(
            team_id=team_id,
            relationship=TASK_RUN_TYPE_IMPLEMENTATION,
            task__team_id=team_id,
            task__runs__team_id=team_id,
        )
        .filter(
            Q(task__runs__state__verified_pr_urls__contains=[verified_url])
            | Q(task__runs__state__verified_pr_urls__contains=[pr_url])
        )
        .select_related("task__github_integration", "task__github_user_integration", "task__team")
        .order_by("task_id")
    )
    seen_task_ids: set[str] = set()
    probe_error: Exception | None = None
    for implementation in implementations.iterator():
        task = implementation.task
        task_id = str(task.id)
        if task_id in seen_task_ids:
            continue
        seen_task_ids.add(task_id)
        personal = task.github_user_integration
        if (
            personal is not None
            and personal.kind == "github"
            and personal.user_id == task.created_by_id
            and OrganizationMembership.objects.filter(
                user_id=personal.user_id, organization_id=task.team.organization_id
            ).exists()
        ):
            personal_github = UserGitHubIntegration(personal, source="signals_inbox_summary", priority=Priority.BATCH)
            try:
                if personal_github.installation_can_access_repository(repository, raise_on_transient=True):
                    return personal_github
            except (GitHubEgressBudgetExhausted, GitHubRateLimitError, GitHubIntegrationError) as error:
                probe_error = probe_error or error
        integration = task.github_integration
        if integration is not None and integration.kind == "github" and integration.team_id == team_id:
            team_github = GitHubIntegration(integration, source="signals_inbox_summary", priority=Priority.BATCH)
            try:
                if team_github.installation_can_access_repository(repository, raise_on_transient=True):
                    return team_github
            except (GitHubEgressBudgetExhausted, GitHubRateLimitError, GitHubIntegrationError) as error:
                probe_error = probe_error or error
    fallback = GitHubIntegration.first_for_team_repository(
        team_id, repository, source="signals_inbox_summary", priority=Priority.BATCH
    )
    if fallback is not None:
        return fallback
    if probe_error is not None:
        raise probe_error
    return None


def sync_pull_request_participants(*, team_id: int, repository: str, pr_number: int) -> None:
    pr = (
        generated_pull_requests(team_id).filter(repository=repository.lower(), number=pr_number, state="merged").first()
    )
    if pr is None:
        return
    github = github_for_generated_pull_request(
        team_id=team_id, repository=pr.repository, pr_number=pr.number, pr_url=pr.url
    )
    if github is None:
        return
    snapshot = github.get_pull_request(pr.repository, pr.number)
    if not snapshot.get("success"):
        raise GitHubIntegrationError("Could not fetch merged pull request")
    merged_at = github_datetime(snapshot["merged_at"])
    if snapshot.get("merged") is not True or merged_at is None:
        raise GitHubIntegrationError("Missing verified merge time")
    now = timezone.now()
    SignalReportPullRequest.objects.for_team(team_id).filter(id=pr.id).update(merged_at=merged_at, checked_at=now)
    # Repair the merge time before applying the window: older imports can have no timestamp.
    if merged_at < now - INBOX_SUMMARY_PERIOD:
        return
    participants: dict[int, str] = {}
    merger = human_participant(snapshot["merged_by"])
    if merger is not None:
        participants[merger.id] = merger.login
    for review in github.get_pull_request_reviews(pr.repository, pr.number):
        if review.get("state") != "APPROVED":
            continue
        submitted_at = github_datetime(review.get("submitted_at"))
        if submitted_at is None:
            raise GitHubIntegrationError("Missing approval time")
        if submitted_at <= merged_at:
            reviewer = human_participant(review.get("user"))
            if reviewer is not None:
                participants[reviewer.id] = reviewer.login
    participant_ids = sorted(participants)
    SignalReportPullRequest.objects.for_team(team_id).filter(id=pr.id).update(
        participant_ids=participant_ids,
        participant_logins=[participants[participant_id] for participant_id in participant_ids],
        participants_synced_at=now,
        updated_at=now,
    )
