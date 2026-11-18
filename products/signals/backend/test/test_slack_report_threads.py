import pytest
from unittest.mock import patch

from posthog.models import Organization, Team
from posthog.models.integration import Integration

from products.signals.backend.facade.api import notify_implementation_pr_opened
from products.signals.backend.models import SignalReport, SignalReportSlackThread
from products.signals.backend.slack_report_threads import record_report_slack_thread, report_id_for_slack_thread
from products.signals.backend.task_run_artefacts import record_implementation_task
from products.tasks.backend.facade.api import set_task_run_output, update_task_run
from products.tasks.backend.models import Task, TaskRun
from products.tasks.backend.webhooks import handle_pull_request_event


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
    run = TaskRun.objects.create(task=task, team=team, branch="fix-report", status=TaskRun.Status.IN_PROGRESS)
    record_implementation_task(team_id=team.id, report_id=str(report.id), task_id=str(task.id), run_id=str(run.id))
    targets = {("CTEAM", "1700000000.000100"), ("DREVIEWER", "1700000000.000200")}
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

    with (
        patch("products.signals.backend.slack_report_threads.SlackIntegration") as slack_cls,
        patch("celery.app.task.Task.apply_async"),
    ):
        client = slack_cls.return_value.client
        client.chat_postMessage.return_value = {"ok": True, "ts": "1700000000.000300"}
        for _ in range(2):
            with django_capture_on_commit_callbacks(execute=True):
                if source == "run_output":
                    update_task_run(run.id, task.id, team.id, validated_data={"output": {"pr_url": pr_url}})
                elif source == "set_output":
                    set_task_run_output(run.id, task.id, team.id, output={"pr_url": pr_url})
                else:
                    handle_pull_request_event(
                        {
                            "action": "opened",
                            "installation": {"id": 12345},
                            "repository": {"full_name": "example/repo"},
                            "pull_request": {
                                "html_url": pr_url,
                                "head": {"ref": "fix-report", "repo": {"full_name": "example/repo"}},
                            },
                        }
                    )
        notify_implementation_pr_opened(team.id, str(task.id), pr_url)

        assert client.chat_postMessage.call_count == 2
        assert {
            (call.kwargs["channel"], call.kwargs["thread_ts"]) for call in client.chat_postMessage.call_args_list
        } == targets
        assert all(pr_url in call.kwargs["text"] for call in client.chat_postMessage.call_args_list)
        run.refresh_from_db()
        assert run.status == TaskRun.Status.IN_PROGRESS


@pytest.mark.django_db
def test_pr_notification_retries_failed_threads_and_remembers_each_pr(team) -> None:
    report = _report(team)
    integration = _integration(team)
    task = Task.objects.create(team=team, title="Implement report", description="Fix the issue")
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

    with patch("products.signals.backend.slack_report_threads.SlackIntegration") as slack_cls:
        client = slack_cls.return_value.client
        client.chat_postMessage.side_effect = [RuntimeError("Slack unavailable"), {"ok": True}]
        notify_implementation_pr_opened(team.id, str(task.id), pr_url)
        failed, sent = client.chat_postMessage.call_args_list
        client.chat_postMessage.reset_mock(side_effect=True)
        notify_implementation_pr_opened(team.id, str(task.id), pr_url)
        client.chat_postMessage.assert_called_once_with(**failed.kwargs)
        assert failed.kwargs["channel"] != sent.kwargs["channel"]

        notify_implementation_pr_opened(team.id, str(task.id), other_pr_url)
        notify_implementation_pr_opened(team.id, str(task.id), pr_url)
        assert client.chat_postMessage.call_count == 3


@pytest.mark.django_db
@pytest.mark.parametrize("boundary", ["team", "integration", "workspace", "disconnected", "unsafe_url"])
def test_pr_notification_does_not_reach_an_invalid_target(team, boundary: str) -> None:
    report = _report(team)
    integration = _integration(team)
    task = Task.objects.create(team=team, title="Implement report", description="Fix the issue")
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
    with patch("products.signals.backend.slack_report_threads.SlackIntegration") as slack_cls:
        notify_implementation_pr_opened(team.id, str(task.id), pr_url)
        notify_implementation_pr_opened(other_team.id, str(task.id), pr_url)
        slack_cls.assert_not_called()
