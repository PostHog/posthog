import json
from datetime import timedelta

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from django.utils import timezone

from asgiref.sync import sync_to_async

from posthog.models import Organization, Team, User
from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.ownership.paths import PathOwnership

from products.signals.backend.artefact_attribution import ArtefactAttribution
from products.signals.backend.artefact_schemas import PROwnerSelection, SuggestedReviewerEntry, SuggestedReviewers
from products.signals.backend.assignment_service import ReportAssignmentService
from products.signals.backend.models import SignalReport, SignalRepositoryAreaActivity, SignalUserAutonomyConfig
from products.signals.backend.pr_owning_team import OwningTeam
from products.signals.backend.report_assignments import claim_report
from products.signals.backend.report_generation.repo_activity import area_for_path
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
class TestRelevantPROwner:
    @pytest.fixture(autouse=True)
    def selection_enabled(self, dri_flag):
        dri_flag.return_value = True
        with (
            patch("products.signals.backend.reviewer_pr_assignment.assignment_writer_enabled", return_value=True),
            patch("products.signals.backend.reviewer_pr_assignment.assignment_side_effects_enabled", return_value=True),
            patch("products.signals.backend.assignment_service.assignment_writer_enabled", return_value=True),
            patch("products.signals.backend.assignment_service.assignment_side_effects_enabled", return_value=False),
            patch("products.signals.backend.reviewer_pr_assignment.assignment_side_effects_allowed", return_value=True),
            patch(
                "products.signals.backend.reviewer_pr_assignment.team_research_reviewer_selection_enabled",
                return_value=True,
            ),
            patch("products.signals.backend.pr_owner_evidence.AuthenticatedRepoFiles") as files,
            patch(
                "products.signals.backend.pr_owner_evidence.own_paths",
                return_value=PathOwnership(
                    team_by_path={"src/payments.py": "payments"},
                    registry={},
                    resolved=True,
                ),
            ),
        ):
            files.return_value.read.side_effect = lambda path: "ownership" if path == "owners.yaml" else None
            yield

    def setup_report(self, org: Organization, team: Team) -> tuple[SignalReport, MagicMock]:
        _make_reviewer(org, "prolific", opted_in=False)
        _make_reviewer(org, "current-owner", opted_in=False)
        report = _make_report(team, ["prolific", "current-owner"])
        SignalRepositoryAreaActivity.objects.for_team(team.id).create(
            team_id=team.id,
            repository="posthog/posthog",
            area=area_for_path("src/payments.py"),
            contributors=[{"login": "prolific", "commit_count": 200, "last_commit_at": "2025-01-01T00:00:00Z"}],
            refreshed_at=timezone.now(),
        )
        github = _open_pr_github()
        github.get_pull_request.return_value.update(head_sha="a" * 40, base_sha="b" * 40)
        github.list_pull_request_files.return_value = {"success": True, "paths": ["src/payments.py"]}
        github.list_team_members.return_value = {
            "success": True,
            "logins": ["prolific", "current-owner", "github-only"],
        }
        github.was_ever_unassigned.return_value = _NOT_UNASSIGNED
        github.is_assignable.return_value = {"success": True, "assignable": True}
        github.add_pull_request_assignees.side_effect = lambda _repo, _number, logins: {
            "success": True,
            "assignees": logins,
        }
        return report, github

    def decision(self, *logins: str) -> dict:
        return {
            "outcome": "selected" if logins else "no_suitable_owner",
            "reason": "The PR changes the payments module, whose current owner has relevant responsibility.",
            "candidates": [
                {
                    "login": login,
                    "reason": "Current responsibility for the changed code.",
                    "evidence_refs": ["owners.yaml"],
                }
                for login in logins
            ],
        }

    def run_assignment(self, report: SignalReport, github: MagicMock, model: AsyncMock) -> list[str]:
        with (
            patch(
                "products.signals.backend.reviewer_pr_assignment.GitHubIntegration.first_for_team_repository",
                return_value=github,
            ),
            patch("products.signals.backend.pr_owner_selection.call_llm", model),
        ):
            return assign_reviewers_to_pull_request(team_id=report.team_id, report_id=str(report.id), pr_url=PR_URL)

    def model(self, output: dict) -> AsyncMock:
        return AsyncMock(side_effect=lambda **kwargs: kwargs["validate"](json.dumps(output)))

    @pytest.mark.parametrize(
        "opted_in, expected", [(None, "current-owner"), ("current-owner", "current-owner"), ("prolific", "prolific")]
    )
    def test_relevance_reaches_github_with_opt_in_priority(self, org_and_team, opted_in, expected):
        org, team = org_and_team
        report, github = self.setup_report(org, team)
        if opted_in:
            SignalUserAutonomyConfig.objects.filter(user__email=f"{opted_in}@example.com").update(
                github_assign_on_pull_request=True
            )
        model = self.model(self.decision("current-owner", "prolific"))
        assert self.run_assignment(report, github, model) == [expected]
        github.add_pull_request_assignees.assert_called_once_with("PostHog/posthog", 123, [expected])
        requested = github.request_pull_request_reviews.call_args.args[2]
        assert expected not in requested
        saved = PROwnerSelection.model_validate_json(report.artefacts.get(type="pr_owner_selection").content)
        assert saved.inputs.paths == ("src/payments.py",)
        assert saved.decision.candidates[0].login == "current-owner"
        assert saved.decision.candidates[0].evidence_refs == ("owners.yaml",)
        assert any('"commit_count": 200' in entry.content for entry in saved.inputs.evidence if entry.kind == "history")
        assert report.artefacts.filter(type="suggested_reviewers").count() == 1

    def test_github_team_member_needs_no_inbox_account(self, org_and_team):
        org, team = org_and_team
        report, github = self.setup_report(org, team)
        model = self.model(self.decision("github-only"))
        assert self.run_assignment(report, github, model) == ["github-only"]
        github.add_pull_request_assignees.assert_called_once_with("PostHog/posthog", 123, ["github-only"])
        assert "github-only" not in github.request_pull_request_reviews.call_args.args[2]

    @pytest.mark.parametrize("related", [True, False])
    def test_corrections_reach_selection_as_scoped_evidence(self, org_and_team, related):
        org, team = org_and_team
        report, github = self.setup_report(org, team)
        prior = _make_report(team, ["prolific"])
        title = "Payments module ownership" if related else "Search index ownership"
        ActivityLog.objects.create(
            team_id=team.id,
            organization_id=org.id,
            scope="SignalReport",
            activity="suggested_reviewers_changed",
            item_id=str(prior.id),
            was_impersonated=False,
            is_system=False,
            detail={"name": title, "changes": [{"before": ["prolific"], "after": ["current-owner"]}]},
        )
        chosen = "current-owner" if related else "prolific"
        model = self.model(self.decision(chosen))
        assert self.run_assignment(report, github, model) == [chosen]
        inputs = json.loads(model.call_args.kwargs["user_prompt"])
        correction = next(entry for entry in inputs["evidence"] if entry["kind"] == "correction")
        assert json.loads(correction["content"])["report_title"] == title
        assert {identity["login"] for identity in inputs["identities"]} >= {"prolific", "current-owner"}
        assert "never to unrelated" in model.call_args.kwargs["system_prompt"]

    def test_changed_pr_scope_can_select_someone_outside_report_recipients(self, org_and_team):
        org, team = org_and_team
        report, github = self.setup_report(org, team)
        report.summary = "The search index needs attention."
        report.save(update_fields=["summary"])
        before = report.artefacts.get(type="suggested_reviewers").content
        model = self.model(self.decision("github-only"))
        assert self.run_assignment(report, github, model) == ["github-only"]
        inputs = json.loads(model.call_args.kwargs["user_prompt"])
        assert inputs["paths"] == ["src/payments.py"]
        assert any(report.summary in entry["content"] for entry in inputs["evidence"])
        assert report.artefacts.get(type="suggested_reviewers").content == before

    @pytest.mark.parametrize("choice", ["assigned", "unassigned", "claim", "ineligible_claim"])
    def test_existing_human_choice_prevents_selection(self, org_and_team, choice):
        org, team = org_and_team
        report, github = self.setup_report(org, team)
        if choice == "assigned":
            github.get_pull_request.return_value["assignees"] = ["prolific"]
        elif choice == "unassigned":
            github.was_ever_unassigned.return_value = {"success": True, "unassigned": True}
        else:
            claimant = User.objects.get(email="prolific@example.com")
            claim_report(
                report=report, actor=ArtefactAttribution.from_user(claimant.id), user=claimant, was_impersonated=False
            )
            if choice == "ineligible_claim":
                github.is_assignable.return_value = {"success": True, "assignable": False}
        model = self.model(self.decision("current-owner"))
        assert self.run_assignment(report, github, model) == (["prolific"] if choice == "claim" else [])
        model.assert_not_called()
        if choice == "ineligible_claim":
            github.is_assignable.assert_called_once_with("PostHog/posthog", "prolific")

    def test_human_edit_while_model_runs_discards_decision(self, org_and_team):
        org, team = org_and_team
        report, github = self.setup_report(org, team)
        editor = User.objects.get(email="prolific@example.com")

        async def edit_then_select(**kwargs):
            await sync_to_async(ReportAssignmentService(team=team, report_id=str(report.id)).edit_reviewers)(
                SuggestedReviewers(root=[]), actor=ArtefactAttribution.from_user(editor.id)
            )
            return kwargs["validate"](json.dumps(self.decision("current-owner")))

        model = AsyncMock(side_effect=edit_then_select)
        assert self.run_assignment(report, github, model) == []
        model.assert_called_once()
        assert ReportAssignmentService.read_for_report(team_id=team.id, report_id=str(report.id)).control == "human"
        assert not report.artefacts.filter(type="pr_owner_selection").exists()
        github.add_pull_request_assignees.assert_not_called()
        github.request_pull_request_reviews.assert_not_called()

    @pytest.mark.parametrize("gate", ["assignment_side_effects_enabled"])
    def test_delivery_gate_blocks_selection_even_before_writer_enrollment(self, org_and_team, gate):
        org, team = org_and_team
        report, github = self.setup_report(org, team)
        model = self.model(self.decision("current-owner"))
        with patch(f"products.signals.backend.reviewer_pr_assignment.{gate}", return_value=False):
            assert self.run_assignment(report, github, model) == []
        model.assert_not_called()
        github.add_pull_request_assignees.assert_not_called()
        github.request_pull_request_reviews.assert_not_called()

    def test_disabled_selection_keeps_legacy_ownership_policy(self, org_and_team):
        org, team = org_and_team
        report, github = self.setup_report(org, team)
        model = self.model(self.decision("current-owner"))
        with (
            patch(
                "products.signals.backend.reviewer_pr_assignment.team_research_reviewer_selection_enabled",
                return_value=False,
            ),
            patch(
                "products.signals.backend.reviewer_pr_assignment._owning_team",
                return_value=OwningTeam(slug="payments", logins=("prolific", "current-owner", "github-only")),
            ),
        ):
            assigned = self.run_assignment(report, github, model)
        assert len(assigned) == 1
        assert assigned[0] in {"prolific", "current-owner", "github-only"}
        model.assert_not_called()

    @pytest.mark.parametrize("outcome", ["no_suitable_owner", "lookup_failed", "unverified", "malformed"])
    def test_empty_and_failed_decisions_never_use_random_fallback(self, org_and_team, outcome):
        org, team = org_and_team
        report, github = self.setup_report(org, team)
        output = self.decision()
        if outcome == "lookup_failed":
            output.update(outcome="lookup_failed", reason="Required ownership evidence unavailable.")
        elif outcome == "unverified":
            output = self.decision("invented-login")
        elif outcome == "malformed":
            output = {"outcome": "selected"}
        model = self.model(output)
        for _ in range(2):
            assert self.run_assignment(report, github, model) == []
        github.add_pull_request_assignees.assert_not_called()
        assert model.call_count == 1
        saved = PROwnerSelection.model_validate_json(report.artefacts.get(type="pr_owner_selection").content)
        assert saved.decision.outcome == ("no_suitable_owner" if outcome == "no_suitable_owner" else "lookup_failed")

    @pytest.mark.parametrize("failure", ["roster", "files", "incomplete_files", "access"])
    def test_missing_evidence_or_access_stops_assignment(self, org_and_team, failure):
        org, team = org_and_team
        report, github = self.setup_report(org, team)
        if failure == "roster":
            github.list_team_members.return_value = {"success": False}
        elif failure == "files":
            github.list_pull_request_files.return_value = {"success": False}
        elif failure == "incomplete_files":
            github.list_pull_request_files.return_value = {
                "success": True,
                "paths": [f"src/{i}.py" for i in range(100)],
            }
        else:
            User.objects.filter(email="current-owner@example.com").update(is_active=False)
        model = self.model(self.decision("current-owner"))
        assert self.run_assignment(report, github, model) == []
        github.add_pull_request_assignees.assert_not_called()
        saved = PROwnerSelection.model_validate_json(report.artefacts.get(type="pr_owner_selection").content)
        assert saved.decision.outcome == "lookup_failed"

    @pytest.mark.parametrize("enabled", [True, False])
    @pytest.mark.parametrize("keep", [[], ["prolific"]])
    def test_human_list_cannot_be_bypassed_by_pr_selection(self, org_and_team, keep, enabled):
        org, team = org_and_team
        report, github = self.setup_report(org, team)
        editor = User.objects.get(email="prolific@example.com")
        service = ReportAssignmentService(team=team, report_id=str(report.id))
        service.edit_reviewers(
            SuggestedReviewers(root=[SuggestedReviewerEntry(github_login=login) for login in keep]),
            actor=ArtefactAttribution.from_user(editor.id),
        )
        before = service.read()
        model = self.model(self.decision("current-owner"))
        with patch(
            "products.signals.backend.reviewer_pr_assignment.team_research_reviewer_selection_enabled",
            return_value=enabled,
        ):
            assert self.run_assignment(report, github, model) == keep
        model.assert_not_called()
        assert service.read() == before

    def test_failed_lookup_can_be_reassessed_after_cooldown(self, org_and_team):
        org, team = org_and_team
        report, github = self.setup_report(org, team)
        github.list_team_members.return_value = {"success": False}
        model = self.model(self.decision("current-owner"))
        assert self.run_assignment(report, github, model) == []
        model.assert_not_called()
        report.artefacts.filter(type="pr_owner_selection").update(created_at=timezone.now() - timedelta(minutes=11))
        github.list_team_members.return_value = {"success": True, "logins": ["current-owner"]}
        assert self.run_assignment(report, github, model) == ["current-owner"]
        model.assert_called_once()
        assert report.artefacts.filter(type="pr_owner_selection").count() == 2

    @pytest.mark.parametrize("change", ["human_edit", "head", "base", "claim", "access", "disabled"])
    def test_change_during_selection_rejects_old_decision(self, org_and_team, change):
        org, team = org_and_team
        report, github = self.setup_report(org, team)
        output = self.decision("current-owner")
        model = self.model(output)
        original_check = github.is_assignable.side_effect

        def change_state(*_args):
            if change == "human_edit":
                editor = User.objects.get(email="prolific@example.com")
                ReportAssignmentService(team=team, report_id=str(report.id)).edit_reviewers(
                    SuggestedReviewers(root=[]), actor=ArtefactAttribution.from_user(editor.id)
                )
            elif change in ("head", "base"):
                github.get_pull_request.return_value[f"{change}_sha"] = "c" * 40
            elif change == "claim":
                claimant = User.objects.get(email="prolific@example.com")
                claim_report(
                    report=report,
                    actor=ArtefactAttribution.from_user(claimant.id),
                    user=claimant,
                    was_impersonated=False,
                )
            elif change == "disabled":
                selection_flag.return_value = False
            elif change == "access":
                User.objects.filter(email="current-owner@example.com").update(is_active=False)
            return {"success": True, "assignable": True}

        github.is_assignable.side_effect = change_state
        with patch(
            "products.signals.backend.reviewer_pr_assignment.team_research_reviewer_selection_enabled",
            return_value=True,
        ) as selection_flag:
            assert self.run_assignment(report, github, model) == []
        github.add_pull_request_assignees.assert_not_called()
        github.is_assignable.side_effect = original_check

    def test_retry_reuses_intent_and_remote_state_prevents_duplicate_effects(self, org_and_team):
        org, team = org_and_team
        report, github = self.setup_report(org, team)
        model = self.model(self.decision("current-owner"))
        github.is_assignable.return_value = {"success": False}
        assert self.run_assignment(report, github, model) == []
        github.get_pull_request.return_value["requested_reviewers"] = ["prolific", "current-owner"]
        github.is_assignable.return_value = {"success": True, "assignable": True}
        assert self.run_assignment(report, github, model) == ["current-owner"]
        github.get_pull_request.return_value["assignees"] = ["current-owner"]
        assert self.run_assignment(report, github, model) == []
        assert model.call_count == 1
        assert report.artefacts.filter(type="pr_owner_selection").count() == 1
        github.add_pull_request_assignees.assert_called_once()
        github.request_pull_request_reviews.assert_called_once()
