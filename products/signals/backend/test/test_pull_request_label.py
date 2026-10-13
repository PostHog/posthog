import pytest
from unittest.mock import MagicMock, patch

from posthog.models import Organization, Team, User

from products.signals.backend.artefact_attribution import ArtefactAttribution
from products.signals.backend.models import SignalReport, SignalReportAssignment, SignalTeamConfig
from products.signals.backend.pull_request_label import (
    DEFAULT_PULL_REQUEST_LABEL,
    apply_pull_request_label,
    configured_pull_request_label,
    schedule_pull_request_label,
)
from products.signals.backend.report_assignments import claim_report

PR_URL = "https://github.com/PostHog/posthog/pull/123"


@pytest.fixture
def org_and_team():
    org = Organization.objects.create(name="pr-label-org")
    team = Team.objects.create(organization=org, name="pr-label-team")
    yield org, team
    team.delete()
    org.delete()


def _make_report(team: Team) -> SignalReport:
    return SignalReport.objects.create(
        team=team, status=SignalReport.Status.READY, title="Report", summary="Summary", signal_count=1, total_weight=1.0
    )


def _labelling_github(label: str) -> MagicMock:
    github = MagicMock()
    github.add_pull_request_labels.return_value = {"success": True, "labels": [label]}
    return github


class TestConfiguredPullRequestLabel:
    @pytest.mark.django_db
    @pytest.mark.parametrize(
        ("enabled", "name", "expected"),
        [
            (True, "self-driving-pr", "self-driving-pr"),
            (True, "  spaced  ", "spaced"),
            # A team that turns the label on without naming one still gets a label.
            (True, None, DEFAULT_PULL_REQUEST_LABEL),
            (True, "", DEFAULT_PULL_REQUEST_LABEL),
            (True, "   ", DEFAULT_PULL_REQUEST_LABEL),
            # A name left behind by an earlier opt-in must not label anything once the switch is off.
            (False, "self-driving-pr", None),
            (False, None, None),
        ],
        ids=["named", "trimmed", "null_name", "blank_name", "whitespace_name", "off_with_name", "off"],
    )
    def test_the_switch_decides_and_a_blank_name_means_the_default(
        self, org_and_team, enabled: bool, name: str | None, expected: str | None
    ):
        _, team = org_and_team
        SignalTeamConfig.objects.update_or_create(
            team=team, defaults={"pull_request_label_enabled": enabled, "pull_request_label": name}
        )

        assert configured_pull_request_label(team.id) == expected

    @pytest.mark.django_db
    def test_a_team_that_never_touched_the_setting_wants_no_label(self, org_and_team):
        _, team = org_and_team
        SignalTeamConfig.objects.filter(team=team).delete()

        assert configured_pull_request_label(team.id) is None


class TestApplyPullRequestLabel:
    @pytest.mark.django_db
    def test_the_configured_label_reaches_the_pull_request(self, org_and_team):
        _, team = org_and_team
        SignalTeamConfig.objects.update_or_create(
            team=team, defaults={"pull_request_label_enabled": True, "pull_request_label": "ours"}
        )
        report = _make_report(team)
        github = _labelling_github("ours")

        with patch(
            "products.signals.backend.pull_request_label.GitHubIntegration.first_for_team_repository",
            return_value=github,
        ):
            assert apply_pull_request_label(team_id=team.id, report_id=str(report.id), pr_url=PR_URL) == "ours"

        github.add_pull_request_labels.assert_called_once_with("PostHog/posthog", 123, ["ours"])

    @pytest.mark.django_db
    def test_a_team_that_did_not_opt_in_skips_github_entirely(self, org_and_team):
        _, team = org_and_team
        report = _make_report(team)

        with patch(
            "products.signals.backend.pull_request_label.GitHubIntegration.first_for_team_repository"
        ) as mock_lookup:
            assert apply_pull_request_label(team_id=team.id, report_id=str(report.id), pr_url=PR_URL) is None
        mock_lookup.assert_not_called()

    @pytest.mark.django_db
    @pytest.mark.parametrize(
        "outcome",
        [
            Exception("boom"),
            {"success": False, "error": "Failed to label pull request"},
            {"success": True, "labels": []},
        ],
        ids=["raises", "reports_failure", "github_dropped_it"],
    )
    def test_a_github_failure_is_swallowed(self, org_and_team, outcome: object):
        _, team = org_and_team
        SignalTeamConfig.objects.update_or_create(team=team, defaults={"pull_request_label_enabled": True})
        report = _make_report(team)
        github = MagicMock()
        if isinstance(outcome, Exception):
            github.add_pull_request_labels.side_effect = outcome
        else:
            github.add_pull_request_labels.return_value = outcome

        with patch(
            "products.signals.backend.pull_request_label.GitHubIntegration.first_for_team_repository",
            return_value=github,
        ):
            assert apply_pull_request_label(team_id=team.id, report_id=str(report.id), pr_url=PR_URL) is None

    @pytest.mark.django_db
    def test_a_report_from_another_team_is_not_touched(self, org_and_team):
        org, team = org_and_team
        other_team = Team.objects.create(organization=org, name="other-team")
        SignalTeamConfig.objects.update_or_create(team=team, defaults={"pull_request_label_enabled": True})
        report = _make_report(other_team)

        with patch(
            "products.signals.backend.pull_request_label.GitHubIntegration.first_for_team_repository"
        ) as mock_lookup:
            assert apply_pull_request_label(team_id=team.id, report_id=str(report.id), pr_url=PR_URL) is None
        mock_lookup.assert_not_called()


class TestSchedulePullRequestLabel:
    @pytest.mark.django_db(transaction=True)
    @pytest.mark.parametrize(
        ("pr_url", "pr_state", "expected"),
        [
            (PR_URL, SignalReportAssignment.PrState.OPEN, True),
            (PR_URL, SignalReportAssignment.PrState.DRAFT, True),
            (PR_URL, SignalReportAssignment.PrState.UNKNOWN, True),
            (PR_URL, None, True),
            # Nothing to find in a GitHub search, so the round trip is not worth queuing.
            (PR_URL, SignalReportAssignment.PrState.CLOSED, False),
            (PR_URL, SignalReportAssignment.PrState.MERGED, False),
            (None, SignalReportAssignment.PrState.OPEN, False),
        ],
        ids=["open", "draft", "unknown", "null_state", "closed", "merged", "no_url"],
    )
    def test_only_a_live_pull_request_queues_work(
        self, org_and_team, pr_url: str | None, pr_state: str | None, expected: bool
    ):
        _, team = org_and_team
        report = _make_report(team)

        with patch("products.signals.backend.tasks.label_implementation_pr.delay") as mock_delay:
            schedule_pull_request_label(team_id=team.id, report_id=str(report.id), pr_url=pr_url, pr_state=pr_state)

        assert mock_delay.called is expected

    @pytest.mark.django_db(transaction=True)
    def test_linking_a_pull_request_to_a_report_queues_the_label_once(self, org_and_team):
        # The wiring guard: without it the whole feature can go dead with every unit test above
        # still green, and a re-queue would label a pull request somebody unlabelled by hand.
        _, team = org_and_team
        report = _make_report(team)
        user = User.objects.create(email="claimer@example.com")

        with (
            patch("products.signals.backend.tasks.label_implementation_pr.delay") as mock_delay,
            patch(
                "products.signals.backend.report_assignments.GitHubIntegration.first_for_team_repository",
                return_value=None,
            ),
        ):
            for _ in range(2):
                claim_report(
                    report=report,
                    actor=ArtefactAttribution.from_user(user.id),
                    user=user,
                    was_impersonated=False,
                    pr_url=PR_URL,
                    release=False,
                )

        mock_delay.assert_called_once_with(team_id=team.id, report_id=str(report.id), pr_url=PR_URL)
