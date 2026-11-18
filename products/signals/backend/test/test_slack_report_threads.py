import pytest
from unittest.mock import patch

from django.utils import timezone

from celery.exceptions import Retry
from slack_sdk.errors import SlackApiError
from slack_sdk.web import SlackResponse

from posthog.ingress.contracts import WebhookDelivery
from posthog.models import Organization, OrganizationMembership, Team, User
from posthog.models.integration import Integration
from posthog.models.user_integration import UserIntegration

from products.signals.backend.facade.api import notify_implementation_pr_opened
from products.signals.backend.implementation_pr_notification_tasks import deliver_implementation_pr_notifications
from products.signals.backend.models import SignalReport, SignalReportSlackThread
from products.signals.backend.slack_report_threads import record_report_slack_thread, report_id_for_slack_thread
from products.signals.backend.task_run_artefacts import record_implementation_task
from products.tasks.backend.facade.api import accept_github_pull_request, set_task_run_output, update_task_run
from products.tasks.backend.models import Task, TaskRun


@pytest.fixture
def team():
    org = Organization.objects.create(name="slack-thread-org")
    team = Team.objects.create(organization=org, name="slack-thread-team")
    return team


def _integration(team: Team) -> Integration:
    return Integration.objects.create(
        team=team,
        kind="slack",
        integration_id="T123",
        config={"team": {"id": "T123"}},
        sensitive_config={"access_token": "xoxb-test"},
    )


def _report(team: Team) -> SignalReport:
    return SignalReport.objects.create(
        team=team, status=SignalReport.Status.READY, title="A report", summary="Summary", total_weight=1.0
    )


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("channel", "thread_ts", "resolves"),
    [
        ("CTEAM", "1700000000.000100", True),
        # A mention in a different thread of the same channel is an ordinary Slack conversation.
        ("CTEAM", "1700000000.000200", False),
        ("COTHER", "1700000000.000100", False),
    ],
)
def test_only_the_recorded_thread_resolves_to_the_report(team, channel, thread_ts, resolves):
    report = _report(team)
    record_report_slack_thread(
        slack_workspace_id="T123",
        team_id=team.id,
        report_id=str(report.id),
        integration_id=_integration(team).id,
        channel="CTEAM",
        thread_ts="1700000000.000100",
        kind=SignalReportSlackThread.Kind.INBOX_NOTIFICATION,
    )

    resolved = report_id_for_slack_thread(
        slack_workspace_id="T123", team_id=team.id, channel=channel, thread_ts=thread_ts
    )

    assert resolved == (str(report.id) if resolves else None)


@pytest.mark.django_db
@pytest.mark.parametrize("boundary", ["organization", "parent", "sibling"])
def test_thread_recorded_for_another_teams_report_does_not_resolve(team, boundary):
    if boundary == "organization":
        other_org = Organization.objects.create(name="slack-thread-other-org")
        other_team = Team.objects.create(organization=other_org, name="slack-thread-other-team")
        lookup_team = team
    else:
        other_team = Team.objects.create(organization=team.organization, name="Report environment", parent_team=team)
        lookup_team = (
            team
            if boundary == "parent"
            else Team.objects.create(organization=team.organization, name="Other environment", parent_team=team)
        )
    report = _report(other_team)
    record_report_slack_thread(
        slack_workspace_id="T123",
        team_id=other_team.id,
        report_id=str(report.id),
        integration_id=_integration(other_team).id,
        channel="CTEAM",
        thread_ts="1700000000.000100",
        kind=SignalReportSlackThread.Kind.INBOX_NOTIFICATION,
    )

    assert report_id_for_slack_thread(
        slack_workspace_id="T123", team_id=other_team.id, channel="CTEAM", thread_ts="1700000000.000100"
    ) == str(report.id)
    assert (
        report_id_for_slack_thread(
            slack_workspace_id="T123", team_id=lookup_team.id, channel="CTEAM", thread_ts="1700000000.000100"
        )
        is None
    )


@pytest.mark.django_db
@pytest.mark.parametrize("second_workspace", ["T123", "TOTHER"])
def test_re_recording_the_same_thread_keeps_the_first_report(team, second_workspace):
    # Two deliveries racing on one message, and an edit redelivery, both land here. The thread
    # itself is unchanged, so the second write must not fork the link or raise.
    first, second = _report(team), _report(team)
    integration = _integration(team)
    for report, workspace in ((first, "T123"), (second, second_workspace)):
        record_report_slack_thread(
            slack_workspace_id=workspace,
            team_id=team.id,
            report_id=str(report.id),
            integration_id=integration.id,
            channel="CTEAM",
            thread_ts="1700000000.000100",
            kind=SignalReportSlackThread.Kind.INBOX_NOTIFICATION,
        )

    assert SignalReportSlackThread.objects.for_team(team.id).count() == (1 if second_workspace == "T123" else 2)
    assert report_id_for_slack_thread(
        slack_workspace_id="T123", team_id=team.id, channel="CTEAM", thread_ts="1700000000.000100"
    ) == str(first.id)

    if second_workspace != "T123":
        assert report_id_for_slack_thread(
            slack_workspace_id=second_workspace, team_id=team.id, channel="CTEAM", thread_ts="1700000000.000100"
        ) == str(second.id)


@pytest.mark.django_db
@pytest.mark.parametrize("source", ["run_output", "set_output", "github_webhook"])
def test_implementation_pr_reaches_report_threads_once(team, django_capture_on_commit_callbacks, source: str) -> None:
    report = _report(team)
    integration = _integration(team)
    task = Task.objects.create(
        team=team,
        title="Implement report",
        description="Fix the issue",
        origin_product=Task.OriginProduct.SIGNAL_REPORT,
        repository="example/repo",
    )
    run = TaskRun.objects.create(
        task=task,
        team=team,
        branch="fix-report",
        state={"self_driving_head_branch": "fix-report"},
        status=TaskRun.Status.IN_PROGRESS,
    )
    record_implementation_task(team_id=team.id, report_id=str(report.id), task_id=str(task.id), run_id=str(run.id))
    targets = {("CTEAM", "1700000000.000100"), ("COTHER", "1700000000.000200")}
    for channel, thread_ts in targets:
        record_report_slack_thread(
            team_id=team.id,
            report_id=str(report.id),
            integration_id=integration.id,
            slack_workspace_id="T123",
            channel=channel,
            thread_ts=thread_ts,
            kind=SignalReportSlackThread.Kind.INBOX_NOTIFICATION,
        )
    Integration.objects.create(team=team, kind="github", integration_id="12345", config={})
    pr_url = "https://github.com/example/repo/pull/42"
    other_pr_url = "https://github.com/example/repo/pull/43"

    with (
        patch("products.signals.backend.slack_report_threads.SlackIntegration") as slack_cls,
        patch("celery.app.task.Task.apply_async"),
        patch.object(deliver_implementation_pr_notifications, "delay") as queued,
    ):
        client = slack_cls.return_value.client
        client.chat_postMessage.return_value = {"ok": True, "ts": "1700000000.000300"}
        for pr_urls in [[pr_url], [pr_url, other_pr_url], [pr_url, other_pr_url]]:
            with django_capture_on_commit_callbacks(execute=True):
                if source == "run_output":
                    update_task_run(
                        run.id, task.id, team.id, validated_data={"output": {"pr_url": pr_url, "pr_urls": pr_urls}}
                    )
                elif source == "set_output":
                    set_task_run_output(run.id, task.id, team.id, output={"pr_url": pr_url, "pr_urls": pr_urls})
                else:
                    accept_github_pull_request(
                        WebhookDelivery(
                            provider="github",
                            app="posthog",
                            delivery_id="pr-opened-42",
                            event_type="pull_request",
                            payload={
                                "action": "opened",
                                "installation": {"id": 12345},
                                "repository": {"full_name": "example/repo"},
                                "pull_request": {
                                    "html_url": pr_urls[-1],
                                    "head": {"ref": "fix-report", "repo": {"full_name": "example/repo"}},
                                },
                            },
                            received_at=timezone.now(),
                            context={},
                        )
                    )
        with django_capture_on_commit_callbacks(execute=True):
            notify_implementation_pr_opened(team.id, str(task.id), pr_url)
        client.chat_postMessage.assert_not_called()
        for job in queued.call_args_list:
            deliver_implementation_pr_notifications.apply(kwargs=job.kwargs, throw=True)

        assert client.chat_postMessage.call_count == 4
        assert {
            (call.kwargs["channel"], call.kwargs["thread_ts"]) for call in client.chat_postMessage.call_args_list
        } == targets
        assert all(
            sum(url in call.kwargs["text"] for call in client.chat_postMessage.call_args_list) == 2
            for url in [pr_url, other_pr_url]
        )
        run.refresh_from_db()
        assert run.status == TaskRun.Status.IN_PROGRESS


@pytest.mark.django_db
@pytest.mark.parametrize("failure", ["connection", "rate_limit"])
def test_pr_notification_retries_failed_threads_and_remembers_each_pr(team, failure: str) -> None:
    report = _report(team)
    integration = _integration(team)
    task = Task.objects.create(
        team=team, title="Implement report", description="Fix the issue", repository="example/repo"
    )
    record_implementation_task(team_id=team.id, report_id=str(report.id), task_id=str(task.id))
    for channel in ["CFAILED", "CSENT"]:
        record_report_slack_thread(
            team_id=team.id,
            report_id=str(report.id),
            integration_id=integration.id,
            slack_workspace_id="T123",
            channel=channel,
            thread_ts="1700000000.000100",
            kind=SignalReportSlackThread.Kind.SCOUT_REPORT,
        )
    pr_url = "https://github.com/example/repo/pull/42"
    other_pr_url = "https://github.com/example/repo/pull/43"
    error: Exception = RuntimeError("Slack unavailable")
    if failure == "rate_limit":
        error = SlackApiError(
            "Rate limited",
            SlackResponse(
                client=None,
                http_verb="POST",
                api_url="https://slack.com/api/chat.postMessage",
                req_args={},
                data={"ok": False, "error": "ratelimited"},
                headers={"Retry-After": "120"},
                status_code=429,
            ),
        )
    job_args = {"team_id": team.id, "task_id": str(task.id), "pr_url": pr_url}

    with patch("products.signals.backend.slack_report_threads.SlackIntegration") as slack_cls:
        client = slack_cls.return_value.client
        client.chat_postMessage.side_effect = [error, {"ok": True}]
        with pytest.raises(Retry) as retry:
            deliver_implementation_pr_notifications.apply(kwargs=job_args, throw=True)
        assert retry.value.when == (120 if failure == "rate_limit" else 60)
        failed, sent = client.chat_postMessage.call_args_list
        client.chat_postMessage.reset_mock(side_effect=True)
        deliver_implementation_pr_notifications.apply(kwargs=job_args, throw=True)
        client.chat_postMessage.assert_called_once_with(**failed.kwargs)
        assert failed.kwargs["channel"] != sent.kwargs["channel"]

        deliver_implementation_pr_notifications.apply(kwargs={**job_args, "pr_url": other_pr_url}, throw=True)
        deliver_implementation_pr_notifications.apply(kwargs=job_args, throw=True)
        assert client.chat_postMessage.call_count == 3


@pytest.mark.django_db
@pytest.mark.parametrize(
    "boundary", ["team", "integration", "workspace", "disconnected", "unsafe_url", "repository", "host", "http"]
)
def test_pr_notification_does_not_reach_an_invalid_target(team, boundary: str) -> None:
    report = _report(team)
    integration = _integration(team)
    task = Task.objects.create(
        team=team, title="Implement report", description="Fix the issue", repository="example/repo"
    )
    record_implementation_task(team_id=team.id, report_id=str(report.id), task_id=str(task.id))
    other_team = Team.objects.create(organization=team.organization, name="Other team")
    record_report_slack_thread(
        team_id=other_team.id if boundary == "team" else team.id,
        report_id=str(report.id),
        integration_id=None if boundary == "disconnected" else integration.id,
        slack_workspace_id="TOTHER" if boundary == "workspace" else "T123",
        channel="CTEAM",
        thread_ts="1700000000.000100",
        kind=SignalReportSlackThread.Kind.INBOX_NOTIFICATION,
    )
    if boundary == "integration":
        integration.team = other_team
        integration.save(update_fields=["team"])
    pr_url = "https://github.com/example/repo/pull/42"
    if boundary == "unsafe_url":
        pr_url += "|unsafe>"
    elif boundary == "repository":
        pr_url = "https://github.com/example/other/pull/42"
    elif boundary == "host":
        pr_url = "https://example.com/login"
    elif boundary == "http":
        pr_url = "http://github.com/example/repo/pull/42"
    with patch("products.signals.backend.slack_report_threads.SlackIntegration") as slack_cls:
        for team_id in [team.id, other_team.id]:
            deliver_implementation_pr_notifications.apply(
                kwargs={"team_id": team_id, "task_id": str(task.id), "pr_url": pr_url}, throw=True
            )
        slack_cls.assert_not_called()


@pytest.mark.django_db
@pytest.mark.parametrize("recipient", ["active", "removed", "guest", "unknown"])
def test_pr_notification_rechecks_dm_recipient(team, recipient: str) -> None:
    report = _report(team)
    integration = _integration(team)
    user = User.objects.create(email="reviewer@example.com")
    membership = OrganizationMembership.objects.create(user=user, organization=team.organization)
    UserIntegration.objects.create(
        user=user, kind="slack", integration_id="UREVIEWER", config={"slack_team_id": "T123"}
    )
    task = Task.objects.create(
        team=team, title="Implement report", description="Fix the issue", repository="example/repo"
    )
    record_implementation_task(team_id=team.id, report_id=str(report.id), task_id=str(task.id))
    record_report_slack_thread(
        team_id=team.id,
        report_id=str(report.id),
        integration_id=integration.id,
        slack_workspace_id="T123",
        channel="DREVIEWER",
        thread_ts="1700000000.000100",
        kind=SignalReportSlackThread.Kind.INBOX_NOTIFICATION,
        target=None if recipient == "unknown" else "UREVIEWER",
    )
    if recipient == "removed":
        membership.delete()
    with patch("products.signals.backend.slack_report_threads.SlackIntegration") as slack_cls:
        slack = slack_cls.return_value
        slack.get_user_by_id.return_value = None if recipient == "guest" else {"id": "UREVIEWER"}
        deliver_implementation_pr_notifications.apply(
            kwargs={"team_id": team.id, "task_id": str(task.id), "pr_url": "https://github.com/example/repo/pull/42"},
            throw=True,
        )
        assert slack.client.chat_postMessage.call_count == (1 if recipient == "active" else 0)
