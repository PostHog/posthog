import time
from datetime import timedelta
from typing import Any

import pytest
import time_machine
from unittest.mock import ANY, MagicMock, patch

from django.utils import timezone

from celery.exceptions import Retry
from redis.exceptions import ConnectionError as RedisConnectionError
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework.test import APIClient

from posthog.egress.github.transport import GitHubEgressBudgetExhausted, GitHubRateLimitError
from posthog.egress.limiter.policies import Priority
from posthog.integrations import SOURCE_MARKER_CONFIG_KEY
from posthog.models import Team, User
from posthog.models.integration import (
    GitHubIntegration,
    GitHubIntegrationError,
    GitLabIntegration,
    Integration,
    JiraIntegration,
    LinearIntegration,
)
from posthog.redis import get_client

from products.signals.backend.implementation_pr import fetch_implementation_pr_state_for_reports
from products.signals.backend.models import (
    SignalActorKind,
    SignalReport,
    SignalReportAssignment,
    SignalReportMonitoringAttempt,
    SignalReportTrackerIssue,
    SignalTeamConfig,
)
from products.signals.backend.serializers import SignalTeamConfigSerializer
from products.signals.backend.tasks import close_report_tracker_issue
from products.signals.backend.tracker_issues import (
    ABANDONED_CLAIM_REASON,
    PR_BODY_MARKER,
    close_tracker_issue_for_report,
    complete_monitoring_tracker_issues,
    create_tracker_issue_for_report,
    issue_reference,
    link_pull_request_to_tracker_issue,
)

INTEGRATION_CONFIGS = {
    "github": {"account": {"name": "acme"}},
    "gitlab": {"hostname": "https://gitlab.com", "path_with_namespace": "acme/web", "project_id": 7},
    "linear": {"data": {"viewer": {"organization": {"urlKey": "acme"}}}},
    "jira": {"cloud_id": "cloud-1", "site_url": "https://acme.atlassian.net"},
}

TRACKER_TARGETS = {
    "github": {"repository": "web"},
    "gitlab": {},
    "linear": {"team_id": "team-uuid"},
    "jira": {"project_key": "ENG"},
}

CREATED_CONTEXTS: dict[str, dict[str, Any]] = {
    "github": {"repository": "web", "number": 12},
    "gitlab": {"issue_id": 34},
    "linear": {"id": "ENG-123"},
    "jira": {"key": "ENG-9", "id": "1001"},
}

INTEGRATION_CLIENTS = {
    "github": GitHubIntegration,
    "gitlab": GitLabIntegration,
    "linear": LinearIntegration,
    "jira": JiraIntegration,
}

EXPECTED_URLS = {
    "github": "https://github.com/acme/web/issues/12",
    "gitlab": "https://gitlab.com/acme/web/issues/34",
    "linear": "https://linear.app/acme/issue/ENG-123",
    "jira": "https://acme.atlassian.net/browse/ENG-9",
}


def _connect_tracker(team, kind: str, config: dict[str, Any] | None = None) -> Integration:
    integration = Integration.objects.create(
        team=team,
        kind=kind,
        integration_id=f"{kind}-1",
        config=INTEGRATION_CONFIGS[kind],
        sensitive_config={"access_token": "token"},
    )
    SignalTeamConfig.objects.update_or_create(
        team=team,
        defaults={
            "issue_tracking_integration": integration,
            "issue_tracking_config": config if config is not None else TRACKER_TARGETS[kind],
        },
    )
    return integration


def _make_report(team) -> SignalReport:
    return SignalReport.objects.create(
        team=team, status=SignalReport.Status.READY, title="t", summary="s", signal_count=0, total_weight=0.0
    )


@pytest.mark.django_db
@pytest.mark.parametrize("kind", ["github", "gitlab", "linear", "jira"])
def test_create_tracker_issue_records_provider_identifier_and_url(team, kind):
    # Each provider's client takes a different config shape and returns a different identifier, so a
    # target wired to the wrong provider stores a reference that resolves nowhere.
    _connect_tracker(team, kind)
    report = _make_report(team)

    with patch.object(INTEGRATION_CLIENTS[kind], "create_issue", return_value=CREATED_CONTEXTS[kind]):
        tracker = create_tracker_issue_for_report(team_id=team.id, report_id=str(report.id), repository="acme/web")

    assert tracker is not None
    assert tracker.status == SignalReportTrackerIssue.Status.CREATED
    expected_context = {**CREATED_CONTEXTS[kind]}
    if kind == "github":
        expected_context["repository"] = "acme/web"
    assert tracker.external_context == expected_context
    assert tracker.issue_url == EXPECTED_URLS[kind]


@pytest.mark.django_db
def test_create_tracker_issue_opens_one_issue_per_report(team):
    # Auto-start is re-evaluated from several paths at once, and the provider call runs outside the
    # report lock. A second evaluation must reuse the issue, not open an audit duplicate.
    _connect_tracker(team, "github")
    report = _make_report(team)

    with patch.object(GitHubIntegration, "create_issue", return_value=CREATED_CONTEXTS["github"]) as create_issue:
        first = create_tracker_issue_for_report(team_id=team.id, report_id=str(report.id), repository="acme/web")
        second = create_tracker_issue_for_report(team_id=team.id, report_id=str(report.id), repository="acme/web")

    assert create_issue.call_count == 1
    assert first is not None and second is not None
    assert first.id == second.id


@pytest.mark.django_db
def test_create_tracker_issue_surfaces_an_abandoned_claim_without_opening_a_duplicate(team):
    _connect_tracker(team, "github")
    report = _make_report(team)
    tracker = SignalReportTrackerIssue.all_teams.create(
        team=team,
        report=report,
        provider="github",
        status=SignalReportTrackerIssue.Status.PENDING,
    )
    SignalReportTrackerIssue.all_teams.filter(id=tracker.id).update(updated_at=timezone.now() - timedelta(hours=1))

    with patch.object(GitHubIntegration, "create_issue") as create_issue:
        result = create_tracker_issue_for_report(team_id=team.id, report_id=str(report.id), repository="acme/web")

    create_issue.assert_not_called()
    assert result is not None
    result.refresh_from_db()
    assert result.status == SignalReportTrackerIssue.Status.FAILED
    assert result.failure_reason == ABANDONED_CLAIM_REASON


@pytest.mark.django_db
def test_create_tracker_issue_is_off_without_a_configured_integration(team):
    report = _make_report(team)

    assert create_tracker_issue_for_report(team_id=team.id, report_id=str(report.id), repository="acme/web") is None
    assert not SignalReportTrackerIssue.all_teams.filter(report_id=report.id).exists()


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("error", "expected_reason"),
    [
        (GitHubIntegrationError("token expired"), "token expired"),
        (DRFValidationError("Linear team is gone"), "Linear team is gone"),
    ],
)
def test_create_tracker_issue_records_the_failure_instead_of_raising(team, error, expected_reason):
    # The run must open its pull request even when the tracker is down, and the team has to find the
    # pull requests that ended up with no issue without reading logs.
    _connect_tracker(team, "github")
    report = _make_report(team)

    with patch.object(GitHubIntegration, "create_issue", side_effect=error):
        tracker = create_tracker_issue_for_report(team_id=team.id, report_id=str(report.id), repository="acme/web")

    assert tracker is not None
    assert tracker.status == SignalReportTrackerIssue.Status.FAILED
    assert tracker.failure_reason is not None and expected_reason in tracker.failure_reason


def test_jira_reference_prefers_the_readable_key():
    tracker = SignalReportTrackerIssue(provider="jira", external_context={"id": "1001", "key": "ENG-9"})

    assert issue_reference(tracker) == "ENG-9"


@pytest.mark.django_db
def test_link_pull_request_appends_the_reference_once(team):
    # The agent writes the pull request body, so the reference is added afterwards. Every task-run
    # save re-enters this path, and a second append would stack duplicate "Closes" lines.
    _connect_tracker(team, "github")
    report = _make_report(team)
    tracker = SignalReportTrackerIssue.all_teams.create(
        team=team,
        report=report,
        provider="github",
        status=SignalReportTrackerIssue.Status.CREATED,
        external_context={"repository": "acme/web", "number": 12},
        issue_url="https://github.com/acme/web/issues/12",
    )
    pr_url = "https://github.com/acme/web/pull/50"
    pull_request: dict[str, Any] = {"number": 50, "body": "Fixes the thing"}

    # GitHub sends an ETag on the GET but rejects a conditional header on the PATCH.
    def fake_github(method: str, path: str, *, headers: dict[str, str] | None = None, **kwargs: Any) -> MagicMock:
        if method == "GET":
            return MagicMock(status_code=200, headers={"ETag": '"v1"'}, json=MagicMock(return_value=pull_request))
        if any(name.lower().startswith("if-") for name in headers or {}):
            return MagicMock(status_code=400, text="Conditional request headers are not allowed in unsafe requests")
        pull_request["body"] = kwargs["json_body"]["body"]
        return MagicMock(status_code=200)

    with (
        patch.object(
            GitHubIntegration, "first_for_team_repository", return_value=GitHubIntegration.__new__(GitHubIntegration)
        ),
        patch.object(GitHubIntegration, "api_request", side_effect=fake_github),
    ):
        assert link_pull_request_to_tracker_issue(team_id=team.id, report_id=str(report.id), pr_url=pr_url) is True
        assert link_pull_request_to_tracker_issue(team_id=team.id, report_id=str(report.id), pr_url=pr_url) is False

    assert pull_request["body"].count(PR_BODY_MARKER) == 1
    assert "Closes #12" in pull_request["body"]
    tracker.refresh_from_db()
    assert tracker.pr_linked_at is not None


@pytest.mark.django_db
def test_link_pull_request_backs_off_when_the_body_changes_during_the_edit(team):
    _connect_tracker(team, "github")
    report = _make_report(team)
    tracker = SignalReportTrackerIssue.all_teams.create(
        team=team,
        report=report,
        provider="github",
        status=SignalReportTrackerIssue.Status.CREATED,
        external_context={"repository": "acme/web", "number": 12},
        issue_url="https://github.com/acme/web/issues/12",
    )

    with (
        patch.object(
            GitHubIntegration, "first_for_team_repository", return_value=GitHubIntegration.__new__(GitHubIntegration)
        ),
        patch.object(
            GitHubIntegration,
            "get_pull_request",
            side_effect=[
                {"success": True, "body": "Fixes the thing"},
                {"success": True, "body": "Fixes the thing, rewritten by the agent"},
            ],
        ),
        patch.object(GitHubIntegration, "update_pull_request_body", return_value={"success": True}) as update,
    ):
        linked = link_pull_request_to_tracker_issue(
            team_id=team.id, report_id=str(report.id), pr_url="https://github.com/acme/web/pull/50"
        )

    assert linked is False
    update.assert_not_called()
    tracker.refresh_from_db()
    assert tracker.pr_linked_at is None


@pytest.mark.django_db
@pytest.mark.parametrize(
    "delivery",
    [
        "sequential",
        "overlapping",
        "monitoring",
        "reopened",
        "replaced_attempt",
        "archived",
        "manual",
        "provider_retry",
        "failed_comment_retry",
        "reopened_during_pr",
        "reopened_during_comment",
    ],
)
def test_close_tracker_issue_is_recorded_once(team: Team, delivery: str) -> None:
    integration = _connect_tracker(team, "github")
    report = _make_report(team)
    attempt_id = None
    if delivery in {
        "monitoring",
        "reopened",
        "replaced_attempt",
        "archived",
        "manual",
        "reopened_during_pr",
        "reopened_during_comment",
    }:
        started_at = timezone.now() - timedelta(hours=1)
        attempt = SignalReportMonitoringAttempt.objects.for_team(team.id).create(
            team=team,
            report=report,
            monitoring_started_at=started_at,
            aggregation_state="passed",
            close_pr_on_resolve=delivery in {"manual", "reopened_during_pr"},
        )
        attempt_id = str(attempt.id)
        SignalReport.objects.filter(id=report.id).update(
            status=SignalReport.Status.READY if delivery == "reopened" else SignalReport.Status.RESOLVED,
            monitoring_started_at=timezone.now() if delivery == "replaced_attempt" else started_at,
        )
        if delivery == "archived":
            SignalReport.objects.filter(id=report.id).update(
                status=SignalReport.Status.SUPPRESSED,
                status_before_suppression=SignalReport.Status.RESOLVED,
            )
    tracker = SignalReportTrackerIssue.all_teams.create(
        team=team,
        report=report,
        integration=integration,
        provider="github",
        status=SignalReportTrackerIssue.Status.CREATED,
        external_context={"repository": "web", "number": 12},
    )

    def overlapping_close(*args: object, **kwargs: object) -> None:
        assert close_tracker_issue_for_report(team_id=team.id, report_id=str(report.id)) is False

    def reopen_report(*args: object, **kwargs: object) -> dict[str, bool]:
        SignalReport.objects.filter(team_id=team.id, id=report.id).update(status=SignalReport.Status.READY)
        return {"success": True}

    with (
        patch.object(GitHubIntegration, "close_issue") as close_issue,
        patch.object(GitHubIntegration, "comment_on_issue", return_value={"success": True}) as comment,
        patch(
            "products.signals.backend.tracker_issues.close_implementation_pr_for_report", return_value=True
        ) as close_pr,
    ):
        if delivery == "overlapping":
            close_issue.side_effect = overlapping_close
        if delivery == "reopened_during_pr":
            close_pr.side_effect = reopen_report
        if delivery == "reopened_during_comment":
            comment.side_effect = reopen_report
        if delivery in {"provider_retry", "failed_comment_retry"}:
            close_issue.side_effect = [RuntimeError("Provider unavailable"), None]
            if delivery == "failed_comment_retry":
                comment.side_effect = [{"success": False}, {"success": True}]
            assert close_tracker_issue_for_report(team_id=team.id, report_id=str(report.id)) is False
            tracker.refresh_from_db()
            assert (tracker.close_comment_posted_at is None) == (delivery == "failed_comment_retry")
        assert (
            close_tracker_issue_for_report(
                team_id=team.id,
                report_id=str(report.id),
                monitoring_attempt_id=attempt_id,
                completed=attempt_id is not None,
            )
            is True
        )
        if delivery == "manual":
            close_pr.assert_called_once_with(
                team.id,
                str(report.id),
                reason="resolved",
                actor_user_id=None,
                comment_marker=f"<!-- monitoring-completion:{attempt_id} -->",
                before_close=ANY,
                priority=Priority.CRITICAL,
                require_all=True,
            )
        elif delivery != "reopened_during_pr":
            close_pr.assert_not_called()
        if delivery in {"reopened", "replaced_attempt", "reopened_during_pr"}:
            close_issue.assert_not_called()
            comment.assert_not_called()
        elif delivery == "reopened_during_comment":
            close_issue.assert_not_called()
            comment.assert_called_once()
        else:
            assert close_tracker_issue_for_report(team_id=team.id, report_id=str(report.id)) is False
            if delivery in {"provider_retry", "failed_comment_retry"}:
                assert close_issue.call_count == 2
            else:
                close_issue.assert_called_once_with("web", 12, completed=attempt_id is not None)
            assert comment.call_count == (2 if delivery == "failed_comment_retry" else 1)


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("failure", "with_tracker"),
    [
        ("lock", False),
        ("redis", False),
        ("pr_close", False),
        ("pr_close", True),
        ("already_closed", False),
        ("budget_probe", False),
        ("rate_pr_close", False),
        ("budget_tracker_close", True),
        ("rate_tracker_comment", True),
        ("tracker_close", True),
    ],
)
def test_monitoring_completion_retries_until_all_delivery_finishes(
    team: Team, failure: str, with_tracker: bool
) -> None:
    integration = _connect_tracker(team, "github")
    report = _make_report(team)
    now = timezone.now()
    started_at = now - timedelta(hours=1)
    SignalReport.objects.filter(team_id=team.id, id=report.id).update(
        status=SignalReport.Status.RESOLVED, monitoring_started_at=started_at
    )
    attempt = SignalReportMonitoringAttempt.objects.for_team(team.id).create(
        team=team,
        report=report,
        monitoring_started_at=started_at,
        aggregation_state="passed",
        close_pr_on_resolve=True,
        tracker_issue_close_requested_at=now,
    )
    SignalReportAssignment.objects.for_team(team.id).create(
        team=team,
        report=report,
        actor_kind=SignalActorKind.SYSTEM,
        pr_url="https://github.com/acme/web/pull/50",
        repository="acme/web",
        pr_number=50,
        pr_state=SignalReportAssignment.PrState.OPEN,
    )
    tracker = (
        SignalReportTrackerIssue.objects.for_team(team.id).create(
            team=team,
            report=report,
            integration=integration,
            provider="github",
            status=SignalReportTrackerIssue.Status.CREATED,
            external_context={"repository": "web", "number": 12},
        )
        if with_tracker
        else None
    )
    waiting_attempt = (
        SignalReportMonitoringAttempt.objects.for_team(team.id).create(
            team=team,
            report=_make_report(team),
            monitoring_started_at=started_at,
            aggregation_state="passed",
            tracker_issue_close_requested_at=now + timedelta(seconds=1),
        )
        if failure.startswith(("budget_", "rate_"))
        else None
    )
    pr_closed = failure == "already_closed"
    commented = False
    failed = False
    calls: list[str] = []
    priorities: list[Priority] = []

    def deliver(client: GitHubIntegration, stage: str) -> None:
        nonlocal failed
        priorities.append(client.priority)
        calls.append(stage)
        if not failed and failure.removeprefix("budget_").removeprefix("rate_") == stage:
            failed = True
            if failure.startswith("budget_"):
                raise GitHubEgressBudgetExhausted("Budget unavailable")
            if failure.startswith("rate_"):
                if failure == "rate_tracker_comment":
                    raise GitHubRateLimitError("Provider limited", reset_at=int(now.timestamp()) + 900)
                raise GitHubRateLimitError("Provider limited", retry_after=900)
            raise RuntimeError("Provider unavailable")

    def probe(client: GitHubIntegration, repository: str, *, raise_on_transient: bool) -> bool:
        deliver(client, "probe")
        return True

    def status(client: GitHubIntegration, repository: str, number: int) -> dict[str, object]:
        deliver(client, "status")
        return {"success": True, "state": "closed" if pr_closed else "open", "merged": False}

    def find_comment(client: GitHubIntegration, repository: str, number: int, marker: str) -> bool:
        deliver(client, "find_comment")
        return commented

    def comment_pr(client: GitHubIntegration, repository: str, number: int, body: str) -> dict[str, bool]:
        nonlocal commented
        deliver(client, "pr_comment")
        commented = True
        return {"success": True}

    def close_pr(client: GitHubIntegration, repository: str, number: int) -> dict[str, bool]:
        nonlocal pr_closed
        deliver(client, "pr_close")
        pr_closed = True
        return {"success": True}

    def comment_tracker(client: GitHubIntegration, repository: str, number: int, body: str) -> dict[str, bool]:
        deliver(client, "tracker_comment")
        return {"success": True}

    def close_tracker(client: GitHubIntegration, repository: str, number: int, *, completed: bool) -> None:
        deliver(client, "tracker_close")
        assert completed

    with (
        time_machine.travel(now, tick=False),
        patch.object(GitHubIntegration, "installation_can_access_repository", autospec=True, side_effect=probe),
        patch.object(GitHubIntegration, "get_pull_request", autospec=True, side_effect=status),
        patch.object(GitHubIntegration, "has_pull_request_comment", autospec=True, side_effect=find_comment),
        patch.object(GitHubIntegration, "comment_on_pull_request", autospec=True, side_effect=comment_pr),
        patch.object(GitHubIntegration, "close_pull_request", autospec=True, side_effect=close_pr),
        patch.object(GitHubIntegration, "comment_on_issue", autospec=True, side_effect=comment_tracker),
        patch.object(GitHubIntegration, "close_issue", autospec=True, side_effect=close_tracker),
    ):
        if failure == "lock":
            with get_client().lock(f"signals:tracker-close:{team.id}:{report.id}", timeout=120):
                complete_monitoring_tracker_issues(deadline=time.monotonic() + 30)
        elif failure == "redis":
            with patch("products.signals.backend.tracker_issues.get_client", side_effect=RedisConnectionError()):
                complete_monitoring_tracker_issues(deadline=time.monotonic() + 30)
        else:
            complete_monitoring_tracker_issues(deadline=time.monotonic() + 30)
        attempt.refresh_from_db()
        if waiting_attempt is not None:
            waiting_attempt.refresh_from_db()
            assert waiting_attempt.tracker_issue_close_processed_at is None
        if failure != "already_closed":
            assert attempt.tracker_issue_close_processed_at is None
            retry_at = now + timedelta(minutes=15 if failure.startswith("rate_") else 5)
            assert attempt.tracker_issue_close_next_attempt_at == retry_at
            call_count = len(calls)
            complete_monitoring_tracker_issues(deadline=time.monotonic() + 30)
            assert len(calls) == call_count
            with time_machine.travel(retry_at, tick=False):
                complete_monitoring_tracker_issues(deadline=time.monotonic() + 30)
        attempt.refresh_from_db()
        assert attempt.tracker_issue_close_processed_at is not None
        pr_state = fetch_implementation_pr_state_for_reports([str(report.id)], team_id=team.id)[str(report.id)]
        assert pr_state.state == "closed"
        if tracker is not None:
            tracker.refresh_from_db()
            assert tracker.closed_at is not None
        assert calls.count("pr_comment") <= 1
        assert priorities and all(priority == Priority.BATCH for priority in priorities)
        call_count = len(calls)
        complete_monitoring_tracker_issues(deadline=time.monotonic() + 30)
        assert len(calls) == call_count


@pytest.mark.django_db
@pytest.mark.parametrize("bulk", [False, True])
def test_reopening_waits_for_tracker_delivery(team: Team, bulk: bool) -> None:
    integration = _connect_tracker(team, "github")
    user = User.objects.create_and_join(team.organization, "reviewer@example.com", None)
    client = APIClient()
    client.force_authenticate(user=user)
    report = _make_report(team)
    started_at = timezone.now() - timedelta(hours=1)
    SignalReport.objects.filter(team_id=team.id, id=report.id).update(
        status=SignalReport.Status.RESOLVED, monitoring_started_at=started_at
    )
    attempt = SignalReportMonitoringAttempt.objects.for_team(team.id).create(
        team=team,
        report=report,
        monitoring_started_at=started_at,
        aggregation_state="passed",
        tracker_issue_close_requested_at=timezone.now(),
    )
    SignalReportTrackerIssue.all_teams.create(
        team=team,
        report=report,
        integration=integration,
        provider="github",
        status=SignalReportTrackerIssue.Status.CREATED,
        external_context={"repository": "web", "number": 12},
    )
    url = (
        f"/api/projects/{team.id}/signals/reports/bulk-state/"
        if bulk
        else f"/api/projects/{team.id}/signals/reports/{report.id}/state/"
    )
    body: dict[str, object] = {"state": "potential"}
    if bulk:
        body["ids"] = [str(report.id)]

    def try_reopening(*args: object, **kwargs: object) -> None:
        response = client.post(url, body, format="json")
        assert response.status_code == (200 if bulk else 409), response.json()
        if bulk:
            assert response.json()["results"][0]["outcome"] == "skipped"
        report.refresh_from_db()
        assert report.status == SignalReport.Status.RESOLVED

    with (
        patch.object(GitHubIntegration, "comment_on_issue", return_value={"success": True}),
        patch.object(GitHubIntegration, "close_issue", side_effect=try_reopening) as close_issue,
    ):
        assert close_tracker_issue_for_report(
            team_id=team.id, report_id=str(report.id), completed=True, monitoring_attempt_id=str(attempt.id)
        )
        close_issue.assert_called_once()

    response = client.post(url, body, format="json")
    assert response.status_code == 200, response.json()
    report.refresh_from_db()
    assert report.status == SignalReport.Status.POTENTIAL


@pytest.mark.django_db
@pytest.mark.parametrize("comment_fails", [False, True])
def test_tracker_issue_comment_names_the_actor_and_never_blocks_the_close(team, comment_fails):
    # The close goes out under the GitHub App, so this comment is the only place the person who
    # dismissed the report appears. A comment that fails must still leave the issue closed:
    # an issue left open grows the backlog the close exists to prevent.
    integration = _connect_tracker(team, "github")
    report = _make_report(team)
    user = User.objects.create_user(email="dismisser@example.com", password=None, first_name="Dismisser")
    SignalReportTrackerIssue.all_teams.create(
        team=team,
        report=report,
        integration=integration,
        provider="github",
        status=SignalReportTrackerIssue.Status.CREATED,
        external_context={"repository": "web", "number": 12},
    )

    with (
        patch.object(User, "get_github_login", return_value="octocat"),
        patch.object(
            GitHubIntegration,
            "comment_on_issue",
            side_effect=GitHubIntegrationError("boom") if comment_fails else None,
        ) as comment,
        patch.object(GitHubIntegration, "close_issue") as close_issue,
    ):
        assert close_tracker_issue_for_report(team_id=team.id, report_id=str(report.id), actor_user_id=user.id) is True

    close_issue.assert_called_once_with("web", 12, completed=False)
    body = comment.call_args.args[2]
    assert "@octocat closed the" in body
    assert f"/project/{team.id}/inbox/reports/{report.id}?link_source=tracker)" in body


@pytest.mark.django_db
def test_completed_report_closes_tracker_issue_as_completed(team):
    integration = _connect_tracker(team, "github")
    report = _make_report(team)
    SignalReportTrackerIssue.all_teams.create(
        team=team,
        report=report,
        integration=integration,
        provider="github",
        status=SignalReportTrackerIssue.Status.CREATED,
        external_context={"repository": "web", "number": 12},
    )

    with patch.object(GitHubIntegration, "close_issue") as close_issue:
        assert close_tracker_issue_for_report(team_id=team.id, report_id=str(report.id), completed=True) is True

    close_issue.assert_called_once_with("web", 12, completed=True)


@pytest.mark.django_db
@pytest.mark.parametrize("status", [SignalReportTrackerIssue.Status.PENDING, SignalReportTrackerIssue.Status.CREATED])
@pytest.mark.parametrize("failure", ["provider", "redis"])
def test_close_tracker_issue_task_retries_pending_or_failed_provider_close(team, status, failure):
    integration = _connect_tracker(team, "github")
    report = _make_report(team)
    SignalReportTrackerIssue.all_teams.create(
        team=team,
        report=report,
        integration=integration,
        provider="github",
        status=status,
        external_context={"repository": "web", "number": 12},
    )

    with (
        patch("products.signals.backend.tasks.close_tracker_issue_for_report", return_value=False)
        if failure == "provider"
        else patch(
            "products.signals.backend.tracker_issues.get_client", side_effect=RedisConnectionError("Unavailable")
        )
    ):
        with pytest.raises(Retry):
            close_report_tracker_issue.apply(
                kwargs={"report_id": str(report.id), "team_id": team.id, "completed": False},
                throw=True,
            )


@pytest.mark.django_db
def test_create_tracker_issue_refuses_a_repository_that_holds_a_path(team):
    # The repository name reaches a GitHub path, so a value carrying path or query characters could
    # point an authenticated write at another endpoint.
    _connect_tracker(team, "github", config={"repository": "web/issues/1/comments?x="})
    report = _make_report(team)

    with patch.object(GitHubIntegration, "create_issue") as create_issue:
        tracker = create_tracker_issue_for_report(team_id=team.id, report_id=str(report.id), repository="acme/web")

    create_issue.assert_not_called()
    assert tracker is not None
    assert tracker.status == SignalReportTrackerIssue.Status.FAILED


@pytest.mark.django_db
def test_serializer_rejects_a_repository_that_holds_a_path(team):
    integration = Integration.objects.create(
        team=team, kind="github", integration_id="github-1", config=INTEGRATION_CONFIGS["github"]
    )
    serializer = SignalTeamConfigSerializer(
        data={
            "issue_tracking_integration": integration.id,
            "issue_tracking_config": {"repository": "web/issues/1/comments?x="},
        },
        partial=True,
        context={"team_id": team.id},
    )

    assert not serializer.is_valid()
    assert "issue_tracking_config" in serializer.errors


@pytest.mark.django_db
def test_serializer_rejects_a_tracker_with_no_target(team):
    # The target is what tells the provider where the issue goes, so an integration saved without one
    # would fail on every run instead of at the moment the setting was saved.
    integration = Integration.objects.create(
        team=team, kind="linear", integration_id="linear-1", config=INTEGRATION_CONFIGS["linear"]
    )
    serializer = SignalTeamConfigSerializer(
        data={"issue_tracking_integration": integration.id, "issue_tracking_config": {}},
        partial=True,
        context={"team_id": team.id},
    )

    assert not serializer.is_valid()
    assert "issue_tracking_config" in serializer.errors


@pytest.mark.django_db
def test_serializer_rejects_an_integration_from_another_project(team):
    # The field is team-scoped, so a project cannot point self-driving at a tracker it does not own.
    other_team = Team.objects.create(organization=team.organization, name="Other")
    integration = Integration.objects.create(
        team=other_team, kind="linear", integration_id="linear-1", config=INTEGRATION_CONFIGS["linear"]
    )
    serializer = SignalTeamConfigSerializer(
        data={"issue_tracking_integration": integration.id, "issue_tracking_config": {"team_id": "t"}},
        partial=True,
        context={"team_id": team.id},
    )

    assert not serializer.is_valid()
    assert "issue_tracking_integration" in serializer.errors


@pytest.mark.django_db
def test_serializer_rejects_a_provider_that_cannot_hold_issues(team):
    integration = Integration.objects.create(team=team, kind="slack", integration_id="slack-1", config={})
    serializer = SignalTeamConfigSerializer(
        data={"issue_tracking_integration": integration.id},
        partial=True,
        context={"team_id": team.id},
    )

    assert not serializer.is_valid()
    assert "issue_tracking_integration" in serializer.errors


@pytest.mark.django_db
def test_serializer_rejects_a_warehouse_source_row(team):
    integration = Integration.objects.create(
        team=team,
        kind="github",
        integration_id="github-source",
        config={"account": {"name": "acme"}, SOURCE_MARKER_CONFIG_KEY: "Github"},
    )
    serializer = SignalTeamConfigSerializer(
        data={"issue_tracking_integration": integration.id, "issue_tracking_config": {"repository": "web"}},
        partial=True,
        context={"team_id": team.id},
    )

    assert not serializer.is_valid()
    assert "issue_tracking_integration" in serializer.errors
