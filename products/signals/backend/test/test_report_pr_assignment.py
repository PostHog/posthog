import json

import pytest
from unittest.mock import MagicMock, patch

from celery.exceptions import Retry

from posthog.constants import AvailableFeature
from posthog.egress.github.transport import GitHubRateLimitError
from posthog.models import Organization, Team
from posthog.models.integration import GitHubIntegrationError
from posthog.models.organization import OrganizationMembership

from products.access_control.backend.models.access_control import AccessControl
from products.signals.backend.artefact_attribution import ArtefactAttribution
from products.signals.backend.artefact_schemas import (
    PROwnerAssignment,
    ReviewerEdit,
    SuggestedReviewerEntry,
    SuggestedReviewers,
)
from products.signals.backend.models import SignalReport, SignalReportArtefact, SignalUserAutonomyConfig
from products.signals.backend.report_assignments import claim_report
from products.signals.backend.reviewer_exclusions import create_exclusion
from products.signals.backend.reviewer_pr_assignment import (
    FirstAssignment,
    assign_reviewers_to_pull_request,
    deliver_pull_request_assignment,
)
from products.signals.backend.tasks import assign_reviewers_on_implementation_pr
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
        assignee_state: list[str] = []
        github.assignee_state = assignee_state
        github.get_pull_request.side_effect = lambda *_args: {
            "success": True,
            "state": "open",
            "draft": False,
            "merged": False,
            "assignees": list(assignee_state),
            "requested_reviewers": [],
        }
        github.was_ever_unassigned.return_value = _NOT_UNASSIGNED
        github.is_assignable.return_value = {"success": True, "assignable": True}
        github.get_collaborator_permission.return_value = "write"

        def add_assignees(_repo, _number, logins):
            assignee_state[:] = list(dict.fromkeys([*assignee_state, *logins]))
            return {"success": True, "assignees": list(assignee_state)}

        def remove_assignees(_repo, _number, logins):
            assignee_state[:] = [login for login in assignee_state if login not in logins]
            return {"success": True, "assignees": list(assignee_state)}

        github.add_pull_request_assignees.side_effect = add_assignees
        github.remove_pull_request_assignees.side_effect = remove_assignees
        return github

    def assign(self, report: SignalReport, github: MagicMock) -> list[str]:
        with patch(
            "products.signals.backend.reviewer_pr_assignment.GitHubIntegration.first_for_team_repository",
            return_value=github,
        ):
            return assign_reviewers_to_pull_request(team_id=report.team_id, report_id=str(report.id), pr_url=PR_URL)

    def deliver(self, report: SignalReport, github: MagicMock) -> FirstAssignment:
        with patch(
            "products.signals.backend.reviewer_pr_assignment.GitHubIntegration.first_for_team_repository",
            return_value=github,
        ):
            return deliver_pull_request_assignment(team_id=report.team_id, report_id=str(report.id), pr_url=PR_URL)

    @pytest.mark.parametrize("dri_enabled", [False, True])
    @pytest.mark.parametrize("first_assignable", [False, True])
    def test_pr_selects_one_eligible_owner_without_changing_report_recipients(
        self, org_and_team: tuple[Organization, Team], dri_flag: MagicMock, dri_enabled: bool, first_assignable: bool
    ) -> None:
        org, team = org_and_team
        dri_flag.return_value = dri_enabled
        _make_reviewer(org, "selected-first", opted_in=True)
        _make_reviewer(org, "selected-second", opted_in=True)
        _make_reviewer(org, "opted-out", opted_in=False)
        claimant = _make_reviewer(org, "claimant", opted_in=True)
        report_logins = ["opted-out", "selected-second", "selected-first"]
        report = _make_report(team, report_logins)
        claim_report(
            report=report, actor=ArtefactAttribution.from_user(claimant.id), user=claimant, was_impersonated=False
        )
        github = self.github()
        github.is_assignable.side_effect = lambda _repo, login: {
            "success": True,
            "assignable": first_assignable or login != "selected-second",
        }
        expected_owner = "selected-second" if first_assignable else "selected-first"

        assert self.assign(report, github) == [expected_owner]
        github.add_pull_request_assignees.assert_called_once_with("PostHog/posthog", 123, [expected_owner])
        assert json.loads(report.artefacts.get(type="suggested_reviewers").content) == [
            {"github_login": login} for login in report_logins
        ]

    @pytest.mark.parametrize(
        "unavailable", ["account", "repository", "inactive", "membership", "project", "opted-out", "no-config"]
    )
    def test_unavailable_people_are_not_replaced(self, org_and_team, unavailable):
        org, team = org_and_team
        selected = _make_reviewer(org, "selected", opted_in=True)
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
        elif unavailable == "opted-out":
            SignalUserAutonomyConfig.objects.filter(user=selected).update(github_assign_on_pull_request=False)
        elif unavailable == "no-config":
            SignalUserAutonomyConfig.objects.filter(user=selected).delete()
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
        reviewer = _make_reviewer(org, "selected", opted_in=True)
        report = _make_report(team, [] if protection == "empty" else ["selected"])
        github = self.github()
        if protection == "assigned":
            github.assignee_state[:] = ["manual-owner"]
        elif protection == "unassigned":
            github.was_ever_unassigned.return_value = {"success": True, "unassigned": True}
        elif protection == "history-unavailable":
            github.was_ever_unassigned.return_value = {"success": False}
        elif protection == "needs-review":
            report.artefacts.filter(type="suggested_reviewers").update(actor_kind="user", created_by=reviewer)
            github.assignee_state[:] = ["selected"]

        assert self.assign(report, github) == []
        github.add_pull_request_assignees.assert_not_called()
        if protection == "needs-review":
            github.request_pull_request_reviews.assert_not_called()

    def test_saved_human_edits_are_used_by_the_pr(self, org_and_team):
        org, team = org_and_team
        removed = _make_reviewer(org, "removed", opted_in=True)
        editor = _make_reviewer(org, "retained", opted_in=True)
        added = _make_reviewer(org, "added", opted_in=True)
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

        assert self.assign(report, github) == ["retained"]
        github.add_pull_request_assignees.assert_called_once_with("PostHog/posthog", 123, ["retained"])

    @pytest.mark.parametrize("assignable", [False, True])
    def test_large_reviewer_lists_have_bounded_github_checks(
        self, org_and_team: tuple[Organization, Team], assignable: bool
    ) -> None:
        org, team = org_and_team
        logins = [f"reviewer-{index}" for index in range(12)]
        for login in logins:
            _make_reviewer(org, login, opted_in=True)
        report = _make_report(team, logins)
        github = self.github()
        github.is_assignable.return_value = {"success": True, "assignable": assignable}

        assert self.assign(report, github) == (logins[:1] if assignable else [])
        assert github.is_assignable.call_count == (1 if assignable else 10)

    @pytest.mark.parametrize(
        "change",
        ["reviewers", "identity", "access", "preference", "github", "exclusion", "delivery", "writer", "selection"],
    )
    def test_a_change_during_permission_checks_stops_assignment(self, org_and_team, change):
        org, team = org_and_team
        selected = _make_reviewer(org, "selected", opted_in=True)
        report = _make_report(team, ["selected"])
        github = self.github()

        def check(_repo, _login):
            if change == "reviewers":
                SignalReportArtefact.objects.create(team=team, report=report, type="suggested_reviewers", content="[]")
            elif change == "identity":
                selected.social_auth.update(extra_data={"login": "renamed"})
            elif change == "access":
                OrganizationMembership.objects.filter(organization=org, user=selected).delete()
            elif change == "preference":
                SignalUserAutonomyConfig.objects.filter(user=selected).update(github_assign_on_pull_request=False)
            elif change == "github":
                github.assignee_state[:] = ["manual-owner"]
            elif change == "exclusion":
                create_exclusion(
                    team_id=team.id, actor_id=selected.id, instruction="Off.", subject_user_uuid=selected.uuid
                )
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
        if change == "exclusion":
            github.request_pull_request_reviews.assert_not_called()

    @pytest.mark.parametrize("opted_in", [False, True])
    def test_retry_uses_current_github_assignment_preference(
        self, org_and_team: tuple[Organization, Team], opted_in: bool
    ) -> None:
        org, team = org_and_team
        selected = _make_reviewer(org, "selected", opted_in=True)
        report = _make_report(team, ["selected"])
        github = self.github()
        add_assignees = github.add_pull_request_assignees.side_effect

        def fail_once(repository: str, number: int, logins: list[str]) -> dict[str, object]:
            if github.add_pull_request_assignees.call_count == 1:
                return {"success": False, "status_code": 503}
            return add_assignees(repository, number, logins)

        github.add_pull_request_assignees.side_effect = fail_once

        assert self.assign(report, github) == []

        SignalUserAutonomyConfig.objects.filter(user=selected).update(github_assign_on_pull_request=opted_in)

        assert self.assign(report, github) == (["selected"] if opted_in else [])
        assert github.add_pull_request_assignees.call_count == (2 if opted_in else 1)

    @pytest.mark.parametrize("next_reviewers", [["second", "opted-out", "replacement"], ["opted-out"], []])
    def test_report_assignment_replaces_only_the_recorded_automatic_owner(
        self, org_and_team: tuple[Organization, Team], next_reviewers: list[str]
    ) -> None:
        org, team = org_and_team
        for login in ["first", "second", "replacement"]:
            _make_reviewer(org, login, opted_in=True)
        _make_reviewer(org, "opted-out", opted_in=False)
        report = _make_report(team, ["first", "second"])
        github = self.github()

        assert self.assign(report, github) == ["first"]
        SignalReportArtefact.objects.create(
            team=team,
            report=report,
            type="suggested_reviewers",
            content=json.dumps([{"github_login": login} for login in next_reviewers]),
        )
        expected = ["second"] if "second" in next_reviewers else []
        assert self.assign(report, github) == expected
        assert github.assignee_state == expected

        assignment = PROwnerAssignment.model_validate_json(
            report.artefacts.filter(type="pr_owner_assignment").latest("created_at").content
        )
        assert [owner.login for owner in assignment.owners] == expected
        assert assignment.replaced_logins == ("first",)
        assert all(owner.proof is not None for owner in assignment.owners)
        github.remove_pull_request_assignees.assert_called_once_with("PostHog/posthog", 123, ["first"])

    @pytest.mark.parametrize("manual_state", [[], ["first", "manual-owner"]])
    def test_manual_assignment_changes_block_report_reassessment(self, org_and_team, manual_state):
        org, team = org_and_team
        for login in ["first", "replacement"]:
            _make_reviewer(org, login, opted_in=True)
        report = _make_report(team, ["first"])
        github = self.github()

        assert self.assign(report, github) == ["first"]
        github.assignee_state[:] = manual_state
        SignalReportArtefact.objects.create(
            team=team,
            report=report,
            type="suggested_reviewers",
            content=json.dumps([{"github_login": "replacement"}]),
        )

        assert self.assign(report, github) == []
        assert report.artefacts.filter(type="pr_owner_assignment").count() == 1
        github.remove_pull_request_assignees.assert_not_called()

    def test_linked_report_owner_must_match_the_stable_github_identity(self, org_and_team):
        org, team = org_and_team
        selected = _make_reviewer(org, "selected", opted_in=True)
        report = _make_report(team, ["selected"])
        github = self.github()
        github.get_collaborator_permission.return_value = "none"

        assert self.assign(report, github) == []
        github.get_collaborator_permission.assert_called_once_with(
            "PostHog/posthog",
            "selected",
            expected_user_id=int(selected.social_auth.get(provider="github").uid),
        )
        github.add_pull_request_assignees.assert_not_called()

    @pytest.mark.parametrize(
        "failure,expected",
        [
            ("pr-network", "retryable_failure"),
            ("pr-not-found", "permanent_failure"),
            ("pr-closed", "skipped"),
            ("events-network", "retryable_failure"),
            ("events-forbidden", "permanent_failure"),
            ("events-forbidden-second-read", "permanent_failure"),
            ("check-network", "retryable_failure"),
            ("check-forbidden", "permanent_failure"),
            ("permission-403", "permanent_failure"),
            ("permission-429", "retryable_failure"),
            ("permission-503", "retryable_failure"),
            ("permission-network", "retryable_failure"),
            ("write-raises", "unknown_write"),
            ("write-bad-gateway", "retryable_failure"),
            ("write-unprocessable", "permanent_failure"),
            ("delivery-off", "skipped"),
        ],
    )
    def test_only_transient_and_unknown_delivery_failures_are_retryable(self, org_and_team, failure, expected):
        org, team = org_and_team
        _make_reviewer(org, "selected", opted_in=True)
        report = _make_report(team, ["selected"])
        github = self.github()
        if failure.startswith("pr-"):
            github.get_pull_request.side_effect = None
        if failure == "pr-network":
            github.get_pull_request.return_value = {"success": False, "error": "network"}
        elif failure == "pr-not-found":
            github.get_pull_request.return_value = {"success": False, "error": "gone", "status_code": 404}
        elif failure == "pr-closed":
            github.get_pull_request.return_value["state"] = "closed"
        elif failure == "events-network":
            github.was_ever_unassigned.return_value = {"success": False, "error": "network"}
        elif failure.startswith("events-forbidden"):
            github.was_ever_unassigned.side_effect = ([_NOT_UNASSIGNED] if failure.endswith("second-read") else []) + [
                {"success": False, "status_code": 403}
            ]
        elif failure == "check-network":
            github.is_assignable.return_value = {"success": False, "error": "network"}
        elif failure == "check-forbidden":
            github.is_assignable.return_value = {"success": False, "error": "forbidden", "status_code": 403}
        elif failure.startswith("permission-"):
            status_code = None if failure == "permission-network" else int(failure.removeprefix("permission-"))
            github.get_collaborator_permission.side_effect = GitHubIntegrationError(
                "Permission lookup failed", status_code=status_code
            )
        elif failure == "write-raises":
            github.add_pull_request_assignees.side_effect = RuntimeError("socket closed")
        elif failure == "write-bad-gateway":
            github.add_pull_request_assignees.side_effect = None
            github.add_pull_request_assignees.return_value = {"success": False, "error": "bad", "status_code": 502}
        elif failure == "write-unprocessable":
            github.add_pull_request_assignees.side_effect = None
            github.add_pull_request_assignees.return_value = {"success": False, "error": "bad", "status_code": 422}

        if failure == "delivery-off":
            with patch(
                "products.signals.backend.reviewer_pr_assignment.assignment_side_effects_enabled", return_value=False
            ):
                outcome = self.deliver(report, github)
        else:
            outcome = self.deliver(report, github)

        assert outcome.status == expected
        assert outcome.retryable is (expected in {"retryable_failure", "unknown_write"})
        assert outcome.assigned == ()
        if failure.startswith("permission-"):
            github.add_pull_request_assignees.assert_not_called()
            github.request_pull_request_reviews.assert_not_called()

    @pytest.mark.parametrize(
        "step",
        ["integration", "pr", "pr-second-read", "history", "history-second-read", "assignability", "identity", "write"],
    )
    def test_rate_limit_delay_reaches_the_worker(self, org_and_team: tuple[Organization, Team], step: str) -> None:
        org, team = org_and_team
        _make_reviewer(org, "selected", opted_in=True)
        report = _make_report(team, ["selected"])
        github = self.github()
        error = GitHubRateLimitError("rate limited", retry_after=3600)
        if step.startswith("pr"):
            github.get_pull_request.side_effect = (
                [github.get_pull_request()] if step.endswith("second-read") else []
            ) + [error]
        elif step.startswith("history"):
            github.was_ever_unassigned.side_effect = ([_NOT_UNASSIGNED] if step.endswith("second-read") else []) + [
                error
            ]
        elif step == "assignability":
            github.is_assignable.side_effect = error
        elif step == "identity":
            github.get_collaborator_permission.side_effect = error
        elif step == "write":
            github.add_pull_request_assignees.side_effect = error

        with patch(
            "products.signals.backend.reviewer_pr_assignment.GitHubIntegration.first_for_team_repository",
            return_value=github,
            side_effect=error if step == "integration" else None,
        ):
            outcome = deliver_pull_request_assignment(team_id=team.id, report_id=str(report.id), pr_url=PR_URL)

        assert outcome.retryable
        assert outcome.retry_after == 3600
        assert github.add_pull_request_assignees.call_count == (1 if step == "write" else 0)
        github.request_pull_request_reviews.assert_not_called()

    @pytest.mark.parametrize("dri_enabled", [False, True])
    @pytest.mark.parametrize(
        "failure", ["integration-network", "integration-limit", "pr-network", "pr-limit", "pr-503"]
    )
    def test_legacy_failures_do_not_retry(
        self, org_and_team: tuple[Organization, Team], dri_flag: MagicMock, dri_enabled: bool, failure: str
    ) -> None:
        org, team = org_and_team
        dri_flag.return_value = dri_enabled
        _make_reviewer(org, "selected", opted_in=True)
        report = _make_report(team, ["selected"])
        github = self.github()
        error = (
            GitHubRateLimitError("rate limited", retry_after=3600) if failure.endswith("limit") else OSError("offline")
        )
        if failure == "pr-503":
            github.get_pull_request.side_effect = None
            github.get_pull_request.return_value = {"success": False, "status_code": 503}
        elif failure.startswith("pr"):
            github.get_pull_request.side_effect = error

        with (
            patch("products.signals.backend.reviewer_pr_assignment.assignment_writer_enabled", return_value=False),
            patch(
                "products.signals.backend.reviewer_pr_assignment.GitHubIntegration.first_for_team_repository",
                return_value=github,
                side_effect=error if failure.startswith("integration") else None,
            ),
        ):
            outcome = deliver_pull_request_assignment(team_id=team.id, report_id=str(report.id), pr_url=PR_URL)

        assert outcome.status == "skipped"
        assert not outcome.retryable
        github.add_pull_request_assignees.assert_not_called()

    @pytest.mark.parametrize("landed,opted_in", [(True, True), (False, True), (False, False)])
    def test_a_retry_after_an_unknown_write_reads_github_before_writing_again(
        self, org_and_team: tuple[Organization, Team], landed: bool, opted_in: bool
    ) -> None:
        org, team = org_and_team
        selected = _make_reviewer(org, "selected", opted_in=True)
        report = _make_report(team, ["selected"])
        github = self.github()
        add_assignees = github.add_pull_request_assignees.side_effect
        github.add_pull_request_assignees.side_effect = RuntimeError("socket closed")

        assert self.deliver(report, github).status == "unknown_write"

        github.add_pull_request_assignees.side_effect = add_assignees
        if landed:
            github.assignee_state[:] = ["selected"]
        SignalUserAutonomyConfig.objects.filter(user=selected).update(github_assign_on_pull_request=opted_in)
        retry = self.deliver(report, github)

        if landed:
            assert (retry.status, retry.reason) == ("skipped", "unknown_assignment_origin")
            assert github.add_pull_request_assignees.call_count == 1
            github.request_pull_request_reviews.assert_called_once_with("PostHog/posthog", 123, ["selected"])
        elif not opted_in:
            assert (retry.status, retry.reason) == ("skipped", "no_assignable_recipients")
            assert not retry.retryable
            assert github.add_pull_request_assignees.call_count == 1
        else:
            assert (retry.status, retry.assigned) == ("assigned", ("selected",))
            assert github.add_pull_request_assignees.call_count == 2
            assignment = PROwnerAssignment.model_validate_json(report.artefacts.get(type="pr_owner_assignment").content)
            assert assignment.owners[0].login == "selected"
            assert assignment.owners[0].proof is not None

    @pytest.mark.parametrize("selection_enabled", [False, True])
    def test_disabling_delivery_stops_owner_removal(
        self, org_and_team: tuple[Organization, Team], dri_flag: MagicMock, selection_enabled: bool
    ) -> None:
        org, team = org_and_team
        dri_flag.return_value = True
        _make_reviewer(org, "selected", opted_in=True)
        _make_reviewer(org, "replacement", opted_in=True)
        report = _make_report(team, ["selected"])
        github = self.github()
        with patch(
            "products.signals.backend.reviewer_pr_assignment.team_research_reviewer_selection_enabled",
            return_value=selection_enabled,
        ):
            assert self.assign(report, github) == ["selected"]
            SignalReportArtefact.objects.create(
                team=team,
                report=report,
                type="suggested_reviewers",
                content=json.dumps([{"github_login": "replacement"}]),
            )
            github.request_pull_request_reviews.reset_mock()
            add_assignees = github.add_pull_request_assignees.side_effect
            with patch(
                "products.signals.backend.reviewer_pr_assignment.assignment_side_effects_allowed", return_value=True
            ) as delivery_allowed:

                def add_then_disable(repository: str, number: int, logins: list[str]) -> dict[str, object]:
                    result = add_assignees(repository, number, logins)
                    delivery_allowed.return_value = False
                    return result

                github.add_pull_request_assignees.side_effect = add_then_disable
                outcome = self.deliver(report, github)

        assert outcome.status == "skipped"
        assert not outcome.retryable
        assert github.assignee_state == ["selected", "replacement"]
        github.remove_pull_request_assignees.assert_not_called()
        github.request_pull_request_reviews.assert_not_called()
        assert report.artefacts.filter(type="pr_owner_assignment").count() == 1

    @pytest.mark.parametrize("step", ["integration", "pr", "assignability", "identity", "write"])
    def test_reassessment_failures_do_not_start_first_assignment_retries(
        self, org_and_team: tuple[Organization, Team], step: str
    ) -> None:
        org, team = org_and_team
        _make_reviewer(org, "selected", opted_in=True)
        _make_reviewer(org, "replacement", opted_in=True)
        report = _make_report(team, ["selected"])
        github = self.github()
        assert self.assign(report, github) == ["selected"]
        SignalReportArtefact.objects.create(
            team=team, report=report, type="suggested_reviewers", content=json.dumps([{"github_login": "replacement"}])
        )
        error = GitHubRateLimitError("rate limited", retry_after=3600)
        boundary = {
            "pr": github.get_pull_request,
            "assignability": github.is_assignable,
            "identity": github.get_collaborator_permission,
            "write": github.add_pull_request_assignees,
        }.get(step)
        if boundary is not None:
            boundary.side_effect = error
        with patch(
            "products.signals.backend.reviewer_pr_assignment.GitHubIntegration.first_for_team_repository",
            return_value=github,
            side_effect=error if step == "integration" else None,
        ):
            outcome = deliver_pull_request_assignment(team_id=team.id, report_id=str(report.id), pr_url=PR_URL)

        assert outcome.status == "skipped"
        assert not outcome.retryable
        assert github.assignee_state == ["selected"]
        assert report.artefacts.filter(type="pr_owner_assignment").count() == 1


@pytest.mark.django_db
class TestFirstAssignmentRecovery:
    def run_task(self, team_id: int, outcome: FirstAssignment, *, retries: int = 0) -> MagicMock:
        task = assign_reviewers_on_implementation_pr
        task.push_request(retries=retries)
        try:
            with (
                patch("products.signals.backend.tasks.deliver_pull_request_assignment", return_value=outcome),
                patch.object(task, "retry", side_effect=Retry()) as retry,
            ):
                if outcome.retryable and retries < task.max_retries:
                    with pytest.raises(Retry):
                        task.run(team_id=team_id, report_id="report", pr_url=PR_URL)
                else:
                    task.run(team_id=team_id, report_id="report", pr_url=PR_URL)
        finally:
            task.pop_request()
        return retry

    @pytest.mark.parametrize(
        "status,countdowns",
        [
            ("assigned", []),
            ("skipped", []),
            ("permanent_failure", []),
            ("retryable_failure", [60, 120, 240, 480, 900]),
            ("unknown_write", [60, 120, 240, 480, 900]),
        ],
    )
    def test_recovery_is_bounded_and_only_for_retryable_outcomes(self, org_and_team, status, countdowns):
        _, team = org_and_team
        outcome = FirstAssignment(status=status, reason="test")

        for attempt, countdown in enumerate(countdowns):
            self.run_task(team.id, outcome, retries=attempt).assert_called_once_with(countdown=countdown)
        self.run_task(team.id, outcome, retries=len(countdowns)).assert_not_called()

    @pytest.mark.parametrize("retry_after,countdown", [(30, 900), (3600, 3600)])
    def test_recovery_waits_for_the_rate_limit(
        self, org_and_team: tuple[Organization, Team], retry_after: int, countdown: int
    ) -> None:
        _, team = org_and_team
        outcome = FirstAssignment(status="retryable_failure", reason="rate_limited", retry_after=retry_after)

        self.run_task(team.id, outcome, retries=4).assert_called_once_with(countdown=countdown)
