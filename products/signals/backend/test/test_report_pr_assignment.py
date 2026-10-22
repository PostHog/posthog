import json

import pytest
from unittest.mock import MagicMock, patch

from posthog.constants import AvailableFeature
from posthog.models.organization import OrganizationMembership

from products.access_control.backend.models.access_control import AccessControl
from products.signals.backend.artefact_attribution import ArtefactAttribution
from products.signals.backend.artefact_schemas import ReviewerEdit, SuggestedReviewerEntry, SuggestedReviewers
from products.signals.backend.models import SignalReport, SignalReportArtefact
from products.signals.backend.report_assignments import claim_report
from products.signals.backend.reviewer_pr_assignment import assign_reviewers_to_pull_request
from products.signals.backend.test.test_reviewer_pr_assignment import (
    _NOT_UNASSIGNED,
    PR_URL,
    _make_report,
    _make_reviewer,
    _open_pr_github,
    dri_flag as dri_flag,
    org_and_team as org_and_team,
)


@pytest.mark.django_db
class TestReportPRAssignment:
    @pytest.fixture(autouse=True)
    def shared_assignment(self):
        with (
            patch("products.signals.backend.reviewer_pr_assignment.assignment_writer_enabled", return_value=True),
            patch("products.signals.backend.reviewer_pr_assignment.assignment_side_effects_enabled", return_value=True),
            patch("products.signals.backend.reviewer_pr_assignment.assignment_side_effects_allowed", return_value=True),
            patch("products.signals.backend.reviewer_rules.assignment_writer_enabled", return_value=True),
            patch("products.signals.backend.reviewer_rules.assignment_side_effects_enabled", return_value=False),
            patch(
                "products.signals.backend.reviewer_pr_assignment.team_research_reviewer_selection_enabled",
                return_value=True,
            ),
        ):
            yield

    def github(self) -> MagicMock:
        github = _open_pr_github()
        github.was_ever_unassigned.return_value = _NOT_UNASSIGNED
        github.is_assignable.return_value = {"success": True, "assignable": True}
        github.add_pull_request_assignees.side_effect = lambda _repo, _number, logins: {
            "success": True,
            "assignees": logins,
        }
        return github

    def assign(self, report: SignalReport, github: MagicMock) -> list[str]:
        with patch(
            "products.signals.backend.reviewer_pr_assignment.GitHubIntegration.first_for_team_repository",
            return_value=github,
        ):
            return assign_reviewers_to_pull_request(team_id=report.team_id, report_id=str(report.id), pr_url=PR_URL)

    @pytest.mark.parametrize("dri_enabled", [False, True])
    def test_pr_uses_the_report_assignment_without_claim_or_opt_in_ranking(self, org_and_team, dri_flag, dri_enabled):
        org, team = org_and_team
        dri_flag.return_value = dri_enabled
        _make_reviewer(org, "selected-first", opted_in=False)
        _make_reviewer(org, "selected-second", opted_in=True)
        claimant = _make_reviewer(org, "claimant", opted_in=True)
        report = _make_report(team, ["selected-first", "selected-second"])
        claim_report(
            report=report, actor=ArtefactAttribution.from_user(claimant.id), user=claimant, was_impersonated=False
        )
        github = self.github()

        assert self.assign(report, github) == ["selected-first", "selected-second"]
        github.add_pull_request_assignees.assert_called_once_with(
            "PostHog/posthog", 123, ["selected-first", "selected-second"]
        )
        github.request_pull_request_reviews.assert_not_called()

    @pytest.mark.parametrize("unavailable", ["account", "repository", "inactive", "membership", "project"])
    def test_unavailable_people_are_not_replaced(self, org_and_team, unavailable):
        org, team = org_and_team
        selected = _make_reviewer(org, "selected", opted_in=False)
        _make_reviewer(org, "outside-list", opted_in=True)
        report = _make_report(team, ["selected"])
        report.artefacts.filter(type="suggested_reviewers").update(
            content=json.dumps([{"user_uuid": str(selected.uuid), "github_login": "selected"}])
        )
        github = self.github()
        if unavailable == "account":
            selected.social_auth.all().delete()
        elif unavailable == "repository":
            github.is_assignable.return_value = {"success": True, "assignable": False}
        elif unavailable == "inactive":
            selected.is_active = False
            selected.save(update_fields=["is_active"])
        elif unavailable == "membership":
            OrganizationMembership.objects.filter(organization=org, user=selected).delete()
        else:
            org.available_product_features = [{"key": AvailableFeature.ACCESS_CONTROL, "name": "Access control"}]
            org.save(update_fields=["available_product_features"])
            AccessControl.objects.create(team=team, resource="project", resource_id=str(team.id), access_level="none")

        assert self.assign(report, github) == []
        github.add_pull_request_assignees.assert_not_called()
        assert json.loads(report.artefacts.get(type="suggested_reviewers").content)[0]["user_uuid"] == str(
            selected.uuid
        )

    @pytest.mark.parametrize("protection", ["assigned", "unassigned", "history-unavailable", "needs-review", "empty"])
    def test_existing_choices_and_empty_reports_are_left_alone(self, org_and_team, protection):
        org, team = org_and_team
        reviewer = _make_reviewer(org, "selected", opted_in=False)
        report = _make_report(team, [] if protection == "empty" else ["selected"])
        github = self.github()
        if protection == "assigned":
            github.get_pull_request.return_value["assignees"] = ["manual-owner"]
        elif protection == "unassigned":
            github.was_ever_unassigned.return_value = {"success": True, "unassigned": True}
        elif protection == "history-unavailable":
            github.was_ever_unassigned.return_value = {"success": False}
        elif protection == "needs-review":
            report.artefacts.filter(type="suggested_reviewers").update(actor_kind="user", created_by=reviewer)

        assert self.assign(report, github) == []
        github.add_pull_request_assignees.assert_not_called()

    def test_saved_human_edits_are_used_by_the_pr(self, org_and_team):
        org, team = org_and_team
        removed = _make_reviewer(org, "removed", opted_in=True)
        editor = _make_reviewer(org, "retained", opted_in=False)
        added = _make_reviewer(org, "added", opted_in=False)
        report = _make_report(team, ["removed", "retained"])
        for action, user in [("remove", removed), ("add", added)]:
            SignalReportArtefact.append(
                team_id=team.id,
                report_id=str(report.id),
                content=SuggestedReviewers(root=[SuggestedReviewerEntry(user_uuid=str(user.uuid))]),
                attribution=ArtefactAttribution.from_user(editor.id),
                reviewer_edit=ReviewerEdit(action=action),
            )
        github = self.github()

        assert self.assign(report, github) == ["retained", "added"]
        github.add_pull_request_assignees.assert_called_once_with("PostHog/posthog", 123, ["retained", "added"])

    @pytest.mark.parametrize("change", ["reviewers", "identity", "access", "github", "delivery", "writer", "selection"])
    def test_a_change_during_permission_checks_stops_assignment(self, org_and_team, change):
        org, team = org_and_team
        selected = _make_reviewer(org, "selected", opted_in=False)
        report = _make_report(team, ["selected"])
        github = self.github()

        def check(_repo, _login):
            if change == "reviewers":
                SignalReportArtefact.objects.create(team=team, report=report, type="suggested_reviewers", content="[]")
            elif change == "identity":
                selected.social_auth.update(extra_data={"login": "renamed"})
            elif change == "access":
                OrganizationMembership.objects.filter(organization=org, user=selected).delete()
            elif change == "github":
                github.get_pull_request.return_value["assignees"] = ["manual-owner"]
            return {"success": True, "assignable": True}

        github.is_assignable.side_effect = check
        flag = {
            "delivery": "assignment_side_effects_enabled",
            "writer": "assignment_writer_enabled",
            "selection": "team_research_reviewer_selection_enabled",
        }.get(change)
        if flag:
            with patch(f"products.signals.backend.reviewer_pr_assignment.{flag}", side_effect=[True, False, False]):
                assert self.assign(report, github) == []
        else:
            assert self.assign(report, github) == []
        github.add_pull_request_assignees.assert_not_called()
