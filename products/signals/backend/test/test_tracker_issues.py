import pytest
from unittest.mock import patch

from rest_framework.exceptions import ValidationError as DRFValidationError

from posthog.models.integration import (
    GitHubIntegration,
    GitHubIntegrationError,
    GitLabIntegration,
    Integration,
    JiraIntegration,
    LinearIntegration,
)

from products.signals.backend.models import SignalReport, SignalReportTrackerIssue, SignalTeamConfig
from products.signals.backend.serializers import SignalTeamConfigSerializer
from products.signals.backend.tracker_issues import (
    PR_BODY_MARKER,
    branch_identifier,
    close_tracker_issue_for_report,
    create_tracker_issue_for_report,
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

CREATED_CONTEXTS = {
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


def _connect_tracker(team, kind: str) -> Integration:
    integration = Integration.objects.create(
        team=team,
        kind=kind,
        integration_id=f"{kind}-1",
        config=INTEGRATION_CONFIGS[kind],
        sensitive_config={"access_token": "token"},
    )
    SignalTeamConfig.objects.update_or_create(
        team=team,
        defaults={"issue_tracking_integration": integration, "issue_tracking_config": TRACKER_TARGETS[kind]},
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
    assert tracker.external_context == CREATED_CONTEXTS[kind]
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


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("kind", "expected"),
    [("linear", "ENG-123"), ("github", None), ("jira", None), ("gitlab", None)],
)
def test_only_linear_puts_its_identifier_in_the_branch_name(team, kind, expected):
    # Linear links a pull request off the branch name. Any other identifier there would be noise in
    # a git ref, and a GitHub issue number would read as a pull request number.
    _connect_tracker(team, kind)
    report = _make_report(team)

    with patch.object(INTEGRATION_CLIENTS[kind], "create_issue", return_value=CREATED_CONTEXTS[kind]):
        tracker = create_tracker_issue_for_report(team_id=team.id, report_id=str(report.id), repository="acme/web")

    assert branch_identifier(tracker) == expected


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
        external_context={"repository": "web", "number": 12},
        issue_url="https://github.com/acme/web/issues/12",
    )
    pr_url = "https://github.com/acme/web/pull/50"

    with (
        patch.object(
            GitHubIntegration, "first_for_team_repository", return_value=GitHubIntegration.__new__(GitHubIntegration)
        ),
        patch.object(GitHubIntegration, "get_pull_request", return_value={"success": True, "body": "Fixes the thing"}),
        patch.object(GitHubIntegration, "update_pull_request_body", return_value={"success": True}) as update,
    ):
        assert link_pull_request_to_tracker_issue(team_id=team.id, report_id=str(report.id), pr_url=pr_url) is True
        assert link_pull_request_to_tracker_issue(team_id=team.id, report_id=str(report.id), pr_url=pr_url) is False

    assert update.call_count == 1
    body = update.call_args.args[2]
    assert PR_BODY_MARKER in body
    assert "Closes #12" in body
    tracker.refresh_from_db()
    assert tracker.pr_linked_at is not None


@pytest.mark.django_db
def test_close_tracker_issue_is_recorded_once(team):
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
        assert close_tracker_issue_for_report(team_id=team.id, report_id=str(report.id)) is True
        assert close_tracker_issue_for_report(team_id=team.id, report_id=str(report.id)) is False

    close_issue.assert_called_once_with("web", 12)


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
        context={"get_team": lambda: team},
    )

    assert not serializer.is_valid()
    assert "issue_tracking_config" in serializer.errors


@pytest.mark.django_db
def test_serializer_rejects_a_provider_that_cannot_hold_issues(team):
    integration = Integration.objects.create(team=team, kind="slack", integration_id="slack-1", config={})
    serializer = SignalTeamConfigSerializer(
        data={"issue_tracking_integration": integration.id},
        partial=True,
        context={"get_team": lambda: team},
    )

    assert not serializer.is_valid()
    assert "issue_tracking_integration" in serializer.errors
