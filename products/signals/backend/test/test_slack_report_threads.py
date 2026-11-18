import pytest
from unittest.mock import patch

from django.utils import timezone

from celery.exceptions import Retry, SoftTimeLimitExceeded
from slack_sdk.errors import SlackApiError
from slack_sdk.web import SlackResponse

from posthog.ingress.contracts import WebhookDelivery
from posthog.models import Organization, OrganizationMembership, Team, User
from posthog.models.integration import Integration
from posthog.models.user_integration import UserIntegration

from products.access_control.backend.models.access_control import AccessControl
from products.signals.backend.facade.api import notify_implementation_pr_opened, notify_implementation_prs_opened
from products.signals.backend.implementation_pr_notification_tasks import deliver_implementation_pr_notifications
from products.signals.backend.models import (
    ArtefactAttribution,
    SignalReport,
    SignalReportArtefact,
    SignalReportSlackThread,
    SignalTeamConfig,
)
from products.signals.backend.report_merge import merge_reports
from products.signals.backend.slack_report_threads import record_report_slack_thread, report_id_for_slack_thread
from products.signals.backend.task_run_artefacts import record_implementation_task
from products.slack_app.backend.models import SlackThreadTaskMapping
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
        recipient_user_ids=[],
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
        recipient_user_ids=[],
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
            recipient_user_ids=[],
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
@pytest.mark.parametrize(
    "thread_timing",
    ["before_pr", "after_pr", "merged_before_pr", "merged_after_pr", "merged_after_delivery", "deleted"],
)
def test_implementation_pr_reaches_report_threads_once(
    team, django_capture_on_commit_callbacks, source: str, thread_timing: str
) -> None:
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
    thread_report = _report(team) if thread_timing.startswith("merged") else report

    def record_threads() -> None:
        for channel, thread_ts in targets:
            record_report_slack_thread(
                team_id=team.id,
                report_id=str(
                    report.id if thread_timing == "merged_after_delivery" and channel == "CTEAM" else thread_report.id
                ),
                integration_id=integration.id,
                slack_workspace_id="T123",
                channel=channel,
                thread_ts=thread_ts,
                kind=SignalReportSlackThread.Kind.INBOX_NOTIFICATION,
                recipient_user_ids=[],
            )

    if thread_timing not in {"after_pr", "merged_after_pr"}:
        record_threads()
    if thread_report != report and thread_timing != "merged_after_delivery":
        merge_reports(
            team=team,
            survivor=thread_report,
            source_ids=[str(report.id)],
            attribution=ArtefactAttribution.from_task(str(task.id)),
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
        if thread_timing == "deleted":
            SignalReport.objects.filter(team_id=team.id, id=report.id).update(status=SignalReport.Status.DELETED)
        for job in queued.call_args_list:
            deliver_implementation_pr_notifications.apply(kwargs=job.kwargs, throw=True)
        if thread_timing == "merged_after_delivery":
            previous_jobs = len(queued.call_args_list)
            with django_capture_on_commit_callbacks(execute=True):
                merge_reports(
                    team=team,
                    survivor=thread_report,
                    source_ids=[str(report.id)],
                    attribution=ArtefactAttribution.from_task(str(task.id)),
                )
            for job in queued.call_args_list[previous_jobs:]:
                deliver_implementation_pr_notifications.apply(kwargs=job.kwargs, throw=True)
        if thread_timing in {"after_pr", "merged_after_pr"}:
            assert not client.chat_postMessage.call_args_list
            previous_jobs = len(queued.call_args_list)
            with django_capture_on_commit_callbacks(execute=True):
                record_threads()
            for job in queued.call_args_list[previous_jobs:]:
                deliver_implementation_pr_notifications.apply(kwargs=job.kwargs, throw=True)

        assert client.chat_postMessage.call_count == (0 if thread_timing == "deleted" else 4)
        assert {
            (call.kwargs["channel"], call.kwargs["thread_ts"]) for call in client.chat_postMessage.call_args_list
        } == (set() if thread_timing == "deleted" else targets)
        assert all(
            sum(url in call.kwargs["text"] for call in client.chat_postMessage.call_args_list)
            == (0 if thread_timing == "deleted" else 2)
            for url in [pr_url, other_pr_url]
        )
        run.refresh_from_db()
        assert run.status == TaskRun.Status.IN_PROGRESS


@pytest.mark.django_db
@pytest.mark.parametrize("failure", ["connection", "rate_limit", "soft_timeout"])
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
    if failure == "soft_timeout":
        error = SoftTimeLimitExceeded()
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
    job_args = {"team_id": team.id, "task_id": str(task.id), "pr_urls": [pr_url]}

    with patch("products.signals.backend.slack_report_threads.SlackIntegration") as slack_cls:
        client = slack_cls.return_value.client
        client.chat_postMessage.side_effect = [error, {"ok": True}]
        with pytest.raises(Retry) as retry:
            deliver_implementation_pr_notifications.apply(kwargs=job_args, throw=True)
        if failure == "soft_timeout":
            assert 0 <= retry.value.when <= 60
        else:
            assert retry.value.when == (120 if failure == "rate_limit" else 60)
        failed = client.chat_postMessage.call_args_list[0]
        if failure == "soft_timeout":
            assert len(client.chat_postMessage.call_args_list) == 1
        else:
            sent = client.chat_postMessage.call_args_list[1]
            assert failed.kwargs["channel"] != sent.kwargs["channel"]
        client.chat_postMessage.reset_mock(side_effect=True)
        deliver_implementation_pr_notifications.apply(kwargs=job_args, throw=True)
        if failure == "soft_timeout":
            assert {call.kwargs["channel"] for call in client.chat_postMessage.call_args_list} == {"CFAILED", "CSENT"}
        else:
            client.chat_postMessage.assert_called_once_with(**failed.kwargs)

        deliver_implementation_pr_notifications.apply(kwargs={**job_args, "pr_urls": [other_pr_url]}, throw=True)
        deliver_implementation_pr_notifications.apply(kwargs=job_args, throw=True)
        assert client.chat_postMessage.call_count == (4 if failure == "soft_timeout" else 3)


@pytest.mark.django_db
@pytest.mark.parametrize(
    "boundary",
    [
        "team",
        "integration",
        "workspace",
        "disconnected",
        "unsafe_url",
        "repository",
        "host",
        "http",
        "sibling",
        "gate",
        "legacy_personal",
        "legacy_project",
        "legacy_unbound",
        "legacy_integration",
    ],
)
def test_pr_notification_does_not_reach_an_invalid_target(team, boundary: str) -> None:
    report = _report(team)
    integration = _integration(team)
    task = Task.objects.create(
        team=team, title="Implement report", description="Fix the issue", repository="example/repo"
    )
    record_implementation_task(team_id=team.id, report_id=str(report.id), task_id=str(task.id))
    other_team = Team.objects.create(
        organization=team.organization,
        name="Other team",
        **({"project": team.project} if boundary == "sibling" else {}),
    )
    record_report_slack_thread(
        team_id=other_team.id if boundary == "team" else team.id,
        report_id=str(report.id),
        integration_id=None if boundary == "disconnected" else integration.id,
        slack_workspace_id="TOTHER" if boundary == "workspace" else "T123",
        channel="CTEAM",
        thread_ts="1700000000.000100",
        kind=SignalReportSlackThread.Kind.INBOX_NOTIFICATION,
        recipient_user_ids=None if boundary.startswith("legacy") else [],
    )
    if boundary in {"legacy_project", "legacy_integration", "legacy_unbound"}:
        SignalTeamConfig.objects.create(
            team=team,
            default_slack_notification_channel="CTEAM|#inbox",
            default_slack_notification_integration_id=(
                None
                if boundary == "legacy_unbound"
                else integration.id
                if boundary == "legacy_project"
                else integration.id + 1
            ),
        )
    if boundary in {"integration", "sibling"}:
        integration.team = other_team
        integration.save(update_fields=["team"])
    if boundary == "gate":
        SignalReportArtefact.objects.create(team=team, report=report, type="reviewer_corrections", content="{}")
    pr_url = "https://github.com/example/repo/pull/42"
    if boundary == "unsafe_url":
        pr_url += "|unsafe>"
    elif boundary == "repository":
        pr_url = "https://github.com/example/other/pull/42"
    elif boundary == "host":
        pr_url = "https://example.com/login"
    elif boundary == "http":
        pr_url = "http://github.com/example/repo/pull/42"
    with (
        patch("products.signals.backend.slack_report_threads.SlackIntegration") as slack_cls,
        patch("posthoganalytics.feature_enabled", return_value=False),
    ):
        for team_id in [team.id, other_team.id]:
            deliver_implementation_pr_notifications.apply(
                kwargs={"team_id": team_id, "task_id": str(task.id), "pr_urls": [pr_url]}, throw=True
            )
        assert slack_cls.return_value.client.chat_postMessage.call_count == (
            1 if boundary in {"sibling", "legacy_project", "legacy_unbound"} else 0
        )


@pytest.mark.django_db
@pytest.mark.parametrize("destination", ["dm", "personal_channel"])
@pytest.mark.parametrize(
    "recipient",
    [
        "active",
        "saved",
        "removed",
        "guest",
        "unknown",
        "changed_email",
        "no_inbox",
        "inactive",
        "shared",
        "mobile_pickup",
        "unmapped_mobile_pickup",
    ],
)
def test_pr_notification_rechecks_personal_recipient(team, recipient: str, destination: str) -> None:
    report = _report(team)
    integration = _integration(team)
    user = User.objects.create(email="reviewer@example.com")
    membership = OrganizationMembership.objects.create(user=user, organization=team.organization)
    if recipient != "saved":
        UserIntegration.objects.create(
            user=user, kind="slack", integration_id="UREVIEWER", config={"slack_team_id": "T123"}
        )
    task = Task.objects.create(
        team=team, title="Implement report", description="Fix the issue", repository="example/repo"
    )
    if recipient in {"mobile_pickup", "unmapped_mobile_pickup"}:
        task.state = {"mobile_push_user_ids": [user.id]}
        task.save(update_fields=["state"])
        run = TaskRun.objects.create(
            task=task,
            team=team,
            state={"slack_actor_user_id": user.id, "slack_actor_slack_user_id": "UREVIEWER"},
            output={
                "pr_url": "https://github.com/example/repo/pull/43",
                "pr_urls": ["https://github.com/example/repo/pull/43", "https://github.com/example/repo/pull/42"],
            },
        )
        if recipient == "mobile_pickup":
            SlackThreadTaskMapping.objects.create(
                team=team,
                integration=integration,
                slack_workspace_id="T123",
                channel="DREVIEWER" if destination == "dm" else "CPERSONAL",
                thread_ts="1700000000.000100",
                task=task,
                task_run=run,
                mentioning_slack_user_id="UREVIEWER",
                conversation_type=(
                    SlackThreadTaskMapping.ConversationType.IM
                    if destination == "dm"
                    else SlackThreadTaskMapping.ConversationType.PUBLIC_CHANNEL
                ),
            )
    record_implementation_task(team_id=team.id, report_id=str(report.id), task_id=str(task.id))
    record_report_slack_thread(
        team_id=team.id,
        report_id=str(report.id),
        integration_id=integration.id,
        slack_workspace_id="T123",
        channel="DREVIEWER" if destination == "dm" else "CPERSONAL",
        thread_ts="1700000000.000100",
        kind=SignalReportSlackThread.Kind.INBOX_NOTIFICATION,
        target=(None if recipient == "unknown" else "UREVIEWER") if destination == "dm" else "CPERSONAL",
        recipient_user_ids=(
            [user.id]
            if recipient == "saved" or (destination == "personal_channel" and recipient != "unknown")
            else None
        ),
    )
    if recipient == "inactive":
        user.is_active = False
        user.save(update_fields=["is_active"])
    if recipient in {"removed", "changed_email", "shared"}:
        membership.delete()
    if recipient == "changed_email":
        other_user = User.objects.create(email="active@example.com")
        OrganizationMembership.objects.create(user=other_user, organization=team.organization)
    if recipient == "shared":
        other_user = User.objects.create(email="other-reviewer@example.com")
        OrganizationMembership.objects.create(user=other_user, organization=team.organization)
        report.slack_threads.update(recipient_user_ids=[user.id, other_user.id])
    if recipient in {"no_inbox", "no_project"}:
        team.organization.available_product_features = [{"key": "access_control", "name": "access_control"}]
        team.organization.save()
        AccessControl.objects.create(
            team=team,
            resource="project" if recipient == "no_project" else "task",
            resource_id=str(team.id) if recipient == "no_project" else None,
            access_level="none",
            organization_member=membership,
        )
    with patch("products.signals.backend.slack_report_threads.SlackIntegration") as slack_cls:
        slack = slack_cls.return_value
        slack.get_user_by_id.return_value = (
            None if recipient == "guest" else {"id": "UREVIEWER", "profile": {"email": "active@example.com"}}
        )
        deliver_implementation_pr_notifications.apply(
            kwargs={
                "team_id": team.id,
                "task_id": str(task.id),
                "pr_urls": ["https://github.com/example/repo/pull/42"],
            },
            throw=True,
        )
        delivered = recipient in {"active", "saved", "shared", "unmapped_mobile_pickup"} or (
            recipient in {"guest", "mobile_pickup"} and destination == "personal_channel"
        )
        assert slack.client.chat_postMessage.call_count == int(delivered)


@pytest.mark.django_db
def test_pr_notifications_queue_one_bounded_batch(team, django_capture_on_commit_callbacks) -> None:
    report = _report(team)
    task = Task.objects.create(team=team, title="Implement report", repository="example/repo")
    record_implementation_task(team_id=team.id, report_id=str(report.id), task_id=str(task.id))
    urls = [f"invalid-{index}" for index in range(10000)]
    urls.extend(f"https://github.com/example/repo/pull/{index}" for index in range(1, 102))
    with patch.object(deliver_implementation_pr_notifications, "delay") as queued:
        with django_capture_on_commit_callbacks(execute=True):
            notify_implementation_prs_opened(team.id, str(task.id), urls)
        assert len(queued.call_args_list) == 1
        assert queued.call_args.kwargs["pr_urls"] == urls[10000:10050]


@pytest.mark.django_db
def test_opened_webhook_does_not_announce_in_mapped_task_thread(team, django_capture_on_commit_callbacks) -> None:
    task = Task.objects.create(team=team, title="Implement report", repository="example/repo")
    run = TaskRun.objects.create(
        task=task, team=team, state={"self_driving_head_branch": "fix-report"}, status=TaskRun.Status.IN_PROGRESS
    )
    SlackThreadTaskMapping.objects.create(
        team=team,
        integration=_integration(team),
        slack_workspace_id="T123",
        channel="CTEAM",
        thread_ts="1700000000.000100",
        task=task,
        task_run=run,
        mentioning_slack_user_id="UREVIEWER",
    )
    report = _report(team)
    record_implementation_task(team_id=team.id, report_id=str(report.id), task_id=str(task.id), run_id=str(run.id))
    integration = Integration.objects.get(team=team, kind="slack")
    for channel in ["CTEAM", "COTHER"]:
        record_report_slack_thread(
            team_id=team.id,
            report_id=str(report.id),
            integration_id=integration.id,
            slack_workspace_id="T123",
            channel=channel,
            thread_ts="1700000000.000100",
            kind=SignalReportSlackThread.Kind.INBOX_NOTIFICATION,
            recipient_user_ids=[],
        )
    Integration.objects.create(team=team, kind="github", integration_id="12345", config={})
    with (
        patch("products.slack_app.backend.slack_thread.SlackThreadHandler.post_pr_opened") as delivered,
        patch("celery.app.task.Task.apply_async"),
        patch("products.signals.backend.slack_report_threads.SlackIntegration") as report_slack,
        patch.object(deliver_implementation_pr_notifications, "delay") as queued,
    ):
        with django_capture_on_commit_callbacks(execute=True):
            accept_github_pull_request(
                WebhookDelivery(
                    provider="github",
                    app="posthog",
                    delivery_id="mapped-pr",
                    event_type="pull_request",
                    payload={
                        "action": "opened",
                        "installation": {"id": 12345},
                        "repository": {"full_name": "example/repo"},
                        "pull_request": {
                            "html_url": "https://github.com/example/repo/pull/42",
                            "head": {"ref": "fix-report", "repo": {"full_name": "example/repo"}},
                        },
                    },
                    received_at=timezone.now(),
                    context={},
                )
            )
        for job in queued.call_args_list:
            deliver_implementation_pr_notifications.apply(kwargs=job.kwargs, throw=True)
        assert [
            call.kwargs["channel"] for call in report_slack.return_value.client.chat_postMessage.call_args_list
        ] == ["COTHER"]
    delivered.assert_not_called()


@pytest.mark.django_db
@pytest.mark.parametrize("mapped_before_recovery", [True, False])
@pytest.mark.parametrize("thread_timing", ["before_pr", "after_pr", "app_rerun", "successor_run", "secondary_pr"])
def test_late_report_thread_keeps_mapped_delivery_once(
    team, django_capture_on_commit_callbacks, mapped_before_recovery: bool, thread_timing: str
) -> None:
    report = _report(team)
    integration = _integration(team)
    task = Task.objects.create(team=team, title="Implement report", repository="example/repo")
    run = TaskRun.objects.create(task=task, team=team, status=TaskRun.Status.IN_PROGRESS)
    record_implementation_task(team_id=team.id, report_id=str(report.id), task_id=str(task.id), run_id=str(run.id))
    SlackThreadTaskMapping.objects.create(
        team=team,
        integration=integration,
        slack_workspace_id="T123",
        channel="CTEAM",
        thread_ts="1700000000.000100",
        task=task,
        task_run=run,
        mentioning_slack_user_id="UREVIEWER",
    )
    record_report_slack_thread(
        team_id=team.id,
        report_id=str(report.id),
        integration_id=integration.id,
        slack_workspace_id="T123",
        channel="CTEAM",
        thread_ts="1700000000.000100",
        kind=SignalReportSlackThread.Kind.INBOX_NOTIFICATION,
        recipient_user_ids=[],
    )
    if thread_timing == "app_rerun":
        TaskRun.objects.filter(id=run.id, team_id=team.id).update(status=TaskRun.Status.FAILED)
        run = TaskRun.objects.create(task=task, team=team, status=TaskRun.Status.IN_PROGRESS)
        record_implementation_task(team_id=team.id, report_id=str(report.id), task_id=str(task.id), run_id=str(run.id))
    output = {"pr_url": "https://github.com/example/repo/pull/42"}
    with (
        patch("products.slack_app.backend.slack_thread.SlackIntegration") as mapped_slack,
        patch("products.signals.backend.slack_report_threads.SlackIntegration") as report_slack,
        patch("celery.app.task.Task.apply_async"),
        patch.object(deliver_implementation_pr_notifications, "delay") as queued,
    ):
        if thread_timing == "before_pr":
            with django_capture_on_commit_callbacks(execute=True):
                record_report_slack_thread(
                    team_id=team.id,
                    report_id=str(report.id),
                    integration_id=integration.id,
                    slack_workspace_id="T123",
                    channel="COTHER",
                    thread_ts="1700000000.000200",
                    kind=SignalReportSlackThread.Kind.INBOX_NOTIFICATION,
                    recipient_user_ids=[],
                )
        if mapped_before_recovery:
            with django_capture_on_commit_callbacks(execute=True):
                update_task_run(run.id, task.id, team.id, validated_data={"output": output})
        else:
            TaskRun.objects.filter(id=run.id, team_id=team.id).update(output=output)
        if thread_timing == "successor_run":
            successor = TaskRun.objects.create(task=task, team=team, status=TaskRun.Status.IN_PROGRESS)
            SlackThreadTaskMapping.objects.filter(task_id=task.id, team_id=team.id).update(task_run=successor)
        if thread_timing != "before_pr":
            with django_capture_on_commit_callbacks(execute=True):
                record_report_slack_thread(
                    team_id=team.id,
                    report_id=str(report.id),
                    integration_id=integration.id,
                    slack_workspace_id="T123",
                    channel="COTHER",
                    thread_ts="1700000000.000200",
                    kind=SignalReportSlackThread.Kind.INBOX_NOTIFICATION,
                    recipient_user_ids=[],
                )
        for job in queued.call_args_list:
            deliver_implementation_pr_notifications.apply(kwargs=job.kwargs, throw=True)
        if not mapped_before_recovery:
            previous_jobs = len(queued.call_args_list)
            with django_capture_on_commit_callbacks(execute=True):
                set_task_run_output(run.id, task.id, team.id, output=output)
            for job in queued.call_args_list[previous_jobs:]:
                deliver_implementation_pr_notifications.apply(kwargs=job.kwargs, throw=True)
        assert [
            call.kwargs["channel"] for call in mapped_slack.return_value.client.chat_postMessage.call_args_list
        ] == (
            []
            if thread_timing == "app_rerun" or (thread_timing == "successor_run" and not mapped_before_recovery)
            else ["CTEAM"]
        )
        channels = [call.kwargs["channel"] for call in report_slack.return_value.client.chat_postMessage.call_args_list]
        saved_thread_owns_primary = thread_timing == "app_rerun" or (
            thread_timing == "successor_run" and not mapped_before_recovery
        )
        assert sorted(channels) == (["COTHER", "CTEAM"] if saved_thread_owns_primary else ["COTHER"])
        if thread_timing == "secondary_pr":
            report_slack.return_value.client.chat_postMessage.reset_mock()
            previous_jobs = len(queued.call_args_list)
            secondary = "https://github.com/example/repo/pull/43"
            with django_capture_on_commit_callbacks(execute=True):
                update_task_run(
                    run.id,
                    task.id,
                    team.id,
                    validated_data={"output": {**output, "pr_urls": [output["pr_url"], secondary]}},
                )
            for job in queued.call_args_list[previous_jobs:]:
                deliver_implementation_pr_notifications.apply(kwargs=job.kwargs, throw=True)
            posts = report_slack.return_value.client.chat_postMessage.call_args_list
            assert sorted(call.kwargs["channel"] for call in posts) == ["COTHER", "CTEAM"]
            assert all(secondary in call.kwargs["text"] for call in posts)
            previous_jobs = len(queued.call_args_list)
            with django_capture_on_commit_callbacks(execute=True):
                update_task_run(run.id, task.id, team.id, validated_data={"output": {"pr_url": secondary}})
            for job in queued.call_args_list[previous_jobs:]:
                deliver_implementation_pr_notifications.apply(kwargs=job.kwargs, throw=True)
            assert report_slack.return_value.client.chat_postMessage.call_count == 2
            assert mapped_slack.return_value.client.chat_postMessage.call_count == 1
            task.refresh_from_db()
            assert task.claim_slack_pr_closed_notification(secondary, merged=mapped_before_recovery)
