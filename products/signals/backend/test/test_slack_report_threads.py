import pytest

from posthog.models import Organization, Team
from posthog.models.integration import Integration

from products.signals.backend.models import SignalReport, SignalReportSlackThread
from products.signals.backend.slack_report_threads import record_report_slack_thread, report_id_for_slack_thread


@pytest.fixture
def team():
    org = Organization.objects.create(name="slack-thread-org")
    team = Team.objects.create(organization=org, name="slack-thread-team")
    yield team
    team.delete()
    org.delete()


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
        )

    assert SignalReportSlackThread.objects.for_team(team.id).count() == (1 if second_workspace == "T123" else 2)
    assert report_id_for_slack_thread(
        slack_workspace_id="T123", team_id=team.id, channel="CTEAM", thread_ts="1700000000.000100"
    ) == str(first.id)

    if second_workspace != "T123":
        assert report_id_for_slack_thread(
            slack_workspace_id=second_workspace, team_id=team.id, channel="CTEAM", thread_ts="1700000000.000100"
        ) == str(second.id)
