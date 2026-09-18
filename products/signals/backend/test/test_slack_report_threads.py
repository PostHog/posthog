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
        team_id=team.id,
        report_id=str(report.id),
        integration_id=_integration(team).id,
        channel="CTEAM",
        thread_ts="1700000000.000100",
    )

    resolved = report_id_for_slack_thread(team_id=team.id, channel=channel, thread_ts=thread_ts)

    assert resolved == (str(report.id) if resolves else None)


@pytest.mark.django_db
def test_thread_recorded_for_another_teams_report_does_not_resolve(team):
    # A workspace can be connected to several projects, so a mention routed to one project must
    # never resolve another project's report.
    other_org = Organization.objects.create(name="slack-thread-other-org")
    other_team = Team.objects.create(organization=other_org, name="slack-thread-other-team")
    record_report_slack_thread(
        team_id=other_team.id,
        report_id=str(_report(other_team).id),
        integration_id=_integration(other_team).id,
        channel="CTEAM",
        thread_ts="1700000000.000100",
    )

    assert report_id_for_slack_thread(team_id=team.id, channel="CTEAM", thread_ts="1700000000.000100") is None


@pytest.mark.django_db
def test_re_recording_the_same_thread_keeps_the_first_report(team):
    # Two deliveries racing on one message, and an edit redelivery, both land here. The thread
    # itself is unchanged, so the second write must not fork the link or raise.
    first, second = _report(team), _report(team)
    integration = _integration(team)
    for report in (first, second):
        record_report_slack_thread(
            team_id=team.id,
            report_id=str(report.id),
            integration_id=integration.id,
            channel="CTEAM",
            thread_ts="1700000000.000100",
        )

    assert SignalReportSlackThread.objects.for_team(team.id).count() == 1
    assert report_id_for_slack_thread(team_id=team.id, channel="CTEAM", thread_ts="1700000000.000100") == str(first.id)
