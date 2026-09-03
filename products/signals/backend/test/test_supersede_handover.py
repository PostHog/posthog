import pytest
from unittest.mock import MagicMock, patch

from django.apps import apps

from posthog.models import Organization, Team

from products.signals.backend.implementation_pr import (
    close_superseded_implementation_prs,
    fetch_implementation_pr_state_for_reports,
    report_has_newer_implementation_task,
)
from products.signals.backend.models import SignalReport, SignalReportTask
from products.signals.backend.task_run_artefacts import TASK_RUN_TYPE_DISCUSSION, TASK_RUN_TYPE_IMPLEMENTATION
from products.tasks.backend.webhooks import _transition_signal_reports_for_pr

_OLD_PR = "https://github.com/PostHog/posthog/pull/1"
_NEW_PR = "https://github.com/PostHog/posthog/pull/2"


@pytest.fixture
def team(db):
    org = Organization.objects.create(name="supersede-org")
    team = Team.objects.create(organization=org, name="supersede-team")
    yield team
    team.delete()
    org.delete()


@pytest.fixture
def report(team):
    return SignalReport.objects.create(
        team=team, status=SignalReport.Status.READY, title="t", summary="s", signal_count=1, total_weight=1.0
    )


def _link_task(team, report, *, pr_url, relationship=TASK_RUN_TYPE_IMPLEMENTATION):
    Task = apps.get_model("tasks", "Task")
    TaskRun = apps.get_model("tasks", "TaskRun")
    task = Task.objects.create(
        team=team, title="impl", description="d", origin_product=Task.OriginProduct.SIGNAL_REPORT
    )
    SignalReportTask.objects.create(team=team, report=report, task=task, relationship=relationship)
    TaskRun.objects.create(team=team, task=task, output={"pr_url": pr_url} if pr_url else {})
    return task


def _github(state="open", merged=False):
    github = MagicMock()
    github.get_pull_request.return_value = {"success": True, "state": state, "merged": merged}
    github.comment_on_pull_request.return_value = {"success": True}
    github.close_pull_request.return_value = {"success": True, "number": 1, "state": "closed"}
    return github


@pytest.mark.django_db
def test_report_surfaces_the_newest_implementation_pr(team, report):
    _link_task(team, report, pr_url=_OLD_PR)
    _link_task(team, report, pr_url=_NEW_PR)

    surfaced = fetch_implementation_pr_state_for_reports([str(report.id)])

    # Ordering matters only once a report can have two implementation tasks. Surfacing the older one
    # would point the inbox at a PR that is about to close.
    assert surfaced[str(report.id)].url == _NEW_PR


@pytest.mark.django_db
def test_discussion_pr_still_loses_to_an_implementation_pr(team, report):
    _link_task(team, report, pr_url=_OLD_PR)
    _link_task(team, report, pr_url=_NEW_PR, relationship=TASK_RUN_TYPE_DISCUSSION)

    surfaced = fetch_implementation_pr_state_for_reports([str(report.id)])

    # Newest-first applies within a group, not across them: a later "Discuss" PR must not displace
    # the implementation PR.
    assert surfaced[str(report.id)].url == _OLD_PR


@pytest.mark.django_db
@pytest.mark.parametrize("position", ["older", "newest", "only"])
def test_report_has_newer_implementation_task(team, report, position):
    first = _link_task(team, report, pr_url=_OLD_PR)
    if position != "only":
        second = _link_task(team, report, pr_url=_NEW_PR)
    task = first if position in ("older", "only") else second

    assert report_has_newer_implementation_task(team.id, str(report.id), str(task.id)) is (position == "older")


@pytest.mark.django_db
def test_closing_a_superseded_pr_does_not_archive_the_report(team, report):
    """A superseded PR closes unmerged, which is indistinguishable from an abandoned one at the
    GitHub webhook. Without the guard the handover archives the very report it is replacing work for."""
    _link_task(team, report, pr_url=_OLD_PR)
    # The replacement task exists but has not opened its PR yet, so the old PR is still the one the
    # report surfaces — the window where the close looks like an abandonment.
    _link_task(team, report, pr_url=None)

    _transition_signal_reports_for_pr(
        _OLD_PR, SignalReport.Status.SUPPRESSED, "archived", [team.id], skip_superseded=True
    )

    report.refresh_from_db()
    assert report.status == SignalReport.Status.READY


@pytest.mark.django_db
def test_closing_the_newest_pr_still_archives_the_report(team, report):
    _link_task(team, report, pr_url=_OLD_PR)

    _transition_signal_reports_for_pr(
        _OLD_PR, SignalReport.Status.SUPPRESSED, "archived", [team.id], skip_superseded=True
    )

    report.refresh_from_db()
    assert report.status == SignalReport.Status.SUPPRESSED


@pytest.mark.django_db
def test_handover_closes_the_earlier_pr_only(team, report):
    _link_task(team, report, pr_url=_OLD_PR)
    new_task = _link_task(team, report, pr_url=_NEW_PR)
    github = _github()

    with patch(
        "products.signals.backend.implementation_pr.GitHubIntegration.first_for_team_repository",
        return_value=github,
    ):
        closed = close_superseded_implementation_prs(
            team_id=team.id, report_id=str(report.id), task_id=str(new_task.id), pr_url=_NEW_PR
        )

    assert closed == 1
    # The URL it acted on is the old PR: closing the replacement would leave the report with nothing.
    assert github.get_pull_request.call_args.args[1] == 1


@pytest.mark.django_db
def test_handover_closes_nothing_for_a_report_with_one_implementation(team, report):
    task = _link_task(team, report, pr_url=_NEW_PR)

    with patch(
        "products.signals.backend.implementation_pr.GitHubIntegration.first_for_team_repository"
    ) as mock_resolve:
        closed = close_superseded_implementation_prs(
            team_id=team.id, report_id=str(report.id), task_id=str(task.id), pr_url=_NEW_PR
        )

    assert closed == 0
    mock_resolve.assert_not_called()
