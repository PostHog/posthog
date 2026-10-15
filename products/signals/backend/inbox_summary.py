from datetime import datetime, timedelta

from django.db.models import Exists, JSONField, OuterRef, QuerySet, TextField, Value
from django.db.models.functions import Cast, Concat, JSONArray, Lower
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from posthog.egress.limiter.policies import Priority
from posthog.models.github_integration_base import GitHubIntegrationError
from posthog.models.integration import GitHubIntegration

from products.signals.backend.artefact_schemas import TASK_RUN_TYPE_IMPLEMENTATION
from products.signals.backend.models import SignalReportPullRequest, SignalReportTask

INBOX_SUMMARY_PERIOD = timedelta(days=7)


def generated_pull_requests(team_id: int) -> QuerySet[SignalReportPullRequest]:
    # Neither a manually attached PR nor an API-writable task output proves that the task created it.
    implementations = (
        SignalReportTask.objects.filter(
            team_id=team_id,
            relationship=TASK_RUN_TYPE_IMPLEMENTATION,
            task__team_id=team_id,
            task__runs__team_id=team_id,
        )
        .alias(
            verified_urls=Cast(Lower(Cast("task__runs__state__verified_pr_urls", TextField())), JSONField()),
        )
        .filter(
            verified_urls__contains=JSONArray(
                Lower(
                    Concat(
                        Value("https://github.com/"),
                        OuterRef("repository"),
                        Value("/pull/"),
                        Cast(OuterRef("number"), TextField()),
                        output_field=TextField(),
                    )
                )
            ),
        )
    )
    return SignalReportPullRequest.objects.for_team(team_id).filter(Exists(implementations))


def github_datetime(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = parse_datetime(value)
    except ValueError:
        return None
    return parsed if parsed is not None and timezone.is_aware(parsed) else None


def human_participant_id(user: object) -> int | None:
    if not isinstance(user, dict):
        raise GitHubIntegrationError("Missing pull request participant")
    login = user.get("login")
    if user.get("type") == "Bot" or (isinstance(login, str) and login.lower().endswith("[bot]")):
        return None
    user_id = user.get("id")
    if user.get("type") != "User" or type(user_id) is not int or user_id <= 0:
        raise GitHubIntegrationError("Unknown pull request participant")
    return user_id


def sync_pull_request_participants(*, team_id: int, repository: str, pr_number: int) -> None:
    pr = (
        generated_pull_requests(team_id).filter(repository=repository.lower(), number=pr_number, state="merged").first()
    )
    if pr is None:
        return
    SignalReportPullRequest.objects.for_team(team_id).filter(id=pr.id).update(
        participant_ids=None, participants_synced_at=None
    )
    github = GitHubIntegration.first_for_team_repository(
        team_id, pr.repository, source="signals_inbox_summary", priority=Priority.BATCH
    )
    if github is None:
        return
    snapshot = github.get_pull_request(pr.repository, pr.number)
    if not snapshot.get("success"):
        raise GitHubIntegrationError("Could not fetch merged pull request")
    merged_at = github_datetime(snapshot.get("merged_at"))
    if snapshot.get("merged") is not True or merged_at is None:
        raise GitHubIntegrationError("Missing verified merge time")
    now = timezone.now()
    SignalReportPullRequest.objects.for_team(team_id).filter(id=pr.id).update(merged_at=merged_at, checked_at=now)
    # Repair the merge time before applying the window: older imports can have no timestamp.
    if merged_at < now - INBOX_SUMMARY_PERIOD:
        return
    participant_ids: set[int] = set()
    merger = human_participant_id(snapshot.get("merged_by"))
    if merger is not None:
        participant_ids.add(merger)
    for review in github.get_pull_request_reviews(pr.repository, pr.number):
        if review.get("state") != "APPROVED":
            continue
        submitted_at = github_datetime(review.get("submitted_at"))
        if submitted_at is None:
            raise GitHubIntegrationError("Missing approval time")
        if submitted_at <= merged_at:
            reviewer = human_participant_id(review.get("user"))
            if reviewer is not None:
                participant_ids.add(reviewer)
    SignalReportPullRequest.objects.for_team(team_id).filter(id=pr.id).update(
        participant_ids=sorted(participant_ids), participants_synced_at=now, updated_at=now
    )
