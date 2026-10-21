import json
from datetime import timedelta
from typing import Literal

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from django.utils import timezone

from asgiref.sync import sync_to_async

from posthog.constants import AvailableFeature
from posthog.egress.limiter.policies import Priority
from posthog.models import Organization, Team, User
from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.integration import GitHubIntegration

from products.access_control.backend.models.access_control import AccessControl
from products.signals.backend.artefact_attribution import ArtefactAttribution
from products.signals.backend.artefact_schemas import (
    PROwnerSelection,
    ReviewerEdit,
    SuggestedReviewerEntry,
    SuggestedReviewers,
)
from products.signals.backend.models import (
    SignalReport,
    SignalReportArtefact,
    SignalRepositoryAreaActivity,
    SignalUserAutonomyConfig,
)
from products.signals.backend.pr_owner_decisions import PROwnerDecisionService
from products.signals.backend.pr_owning_team import OwningTeam
from products.signals.backend.report_assignments import claim_report
from products.signals.backend.report_generation.repo_activity import area_for_path
from products.signals.backend.report_generation.resolve_reviewers import resolve_org_github_login_to_users
from products.signals.backend.reviewer_pr_assignment import assign_reviewers_to_pull_request
from products.signals.backend.reviewer_rules import ReviewerRules
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
            patch("products.signals.backend.reviewer_rules.assignment_writer_enabled", return_value=True),
            patch("products.signals.backend.reviewer_rules.assignment_side_effects_enabled", return_value=False),
            patch("products.signals.backend.reviewer_pr_assignment.assignment_side_effects_allowed", return_value=True),
            patch(
                "products.signals.backend.reviewer_pr_assignment.team_research_reviewer_selection_enabled",
                return_value=True,
            ),
            patch("products.signals.backend.pr_owner_evidence.AuthenticatedRepoFiles") as files,
        ):
            files.return_value.read.side_effect = lambda path: (
                "version: 1\nowners: [payments]\n" if path == "owners.yaml" else None
            )
            yield files.return_value

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

    def edit_reviewers(
        self, report: SignalReport, action: Literal["add", "remove", "replace", "confirm"], *logins: str
    ) -> None:
        editor = User.objects.get(email="prolific@example.com")
        snapshot = ReviewerRules.read_for_report(team_id=report.team_id, report_id=str(report.id))
        SignalReportArtefact.append_status(
            team_id=report.team_id,
            report_id=str(report.id),
            content=SuggestedReviewers(root=[SuggestedReviewerEntry(github_login=login) for login in logins]),
            attribution=ArtefactAttribution.from_user(editor.id),
            reviewer_edit=ReviewerEdit(action=action, expected_state=snapshot.state),
        )

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

    @pytest.mark.parametrize("candidate_count", [1, 5])
    def test_saved_github_only_candidates_use_current_accounts(self, org_and_team, candidate_count):
        org, team = org_and_team
        report, github = self.setup_report(org, team)
        logins = [f"newly-linked-{index}" for index in range(candidate_count)]
        github.list_team_members.return_value = {"success": True, "logins": logins}
        model = self.model(self.decision("current-owner", *logins))
        assert self.run_assignment(report, github, model) == ["current-owner"]
        saved = PROwnerSelection.model_validate_json(report.artefacts.get(type="pr_owner_selection").content)
        assert all(identity.user_uuid is None for identity in saved.inputs.identities if identity.login in logins)
        for login in logins:
            _make_reviewer(org, login, opted_in=True)
        service = PROwnerDecisionService(team_id=team.id, report_id=str(report.id), github=github)
        with patch(
            "products.signals.backend.pr_owner_decisions.resolve_org_github_login_to_users",
            wraps=resolve_org_github_login_to_users,
        ) as resolve:
            eligible = service.eligible_logins(saved)
        resolve.assert_called_once_with(team.id, set(logins))
        assert eligible.opted_in == frozenset(logins)
        assert self.run_assignment(report, github, model) == [logins[0]]
        assert model.call_count == 2

    @pytest.mark.parametrize("change", ["inactive", "no_project_access"])
    def test_newly_linked_ineligible_account_cannot_use_github_team_fallback(self, org_and_team, change):
        org, team = org_and_team
        report, github = self.setup_report(org, team)
        model = self.model(self.decision("github-only"))
        assert self.run_assignment(report, github, model) == ["github-only"]
        user = _make_reviewer(org, "github-only", opted_in=True)
        if change == "inactive":
            user.is_active = False
            user.save(update_fields=["is_active"])
        else:
            org.available_product_features = [{"key": AvailableFeature.ACCESS_CONTROL, "name": "Access control"}]
            org.save(update_fields=["available_product_features"])
            AccessControl.objects.create(team=team, resource="project", resource_id=str(team.id), access_level="none")
        github.add_pull_request_assignees.reset_mock()
        github.list_team_members.reset_mock()
        assert self.run_assignment(report, github, model) == []
        github.add_pull_request_assignees.assert_not_called()
        github.list_team_members.assert_called_once_with("PostHog", "payments", max_members=200)
        assert model.call_count == 2

    @pytest.mark.parametrize("ownerless_rule", ["src/payments.py", "src/payments.py # No owner"])
    def test_ownerless_codeowners_rule_clears_previous_owners(self, org_and_team, selection_enabled, ownerless_rule):
        org, team = org_and_team
        report, github = self.setup_report(org, team)
        selection_enabled.read.side_effect = lambda path: (
            f"* @PostHog/payments @stale-owner\n{ownerless_rule}\n" if path == ".github/CODEOWNERS" else None
        )
        _make_reviewer(org, "stale-owner", opted_in=False)

        assert self.run_assignment(report, github, self.model(self.decision())) == []

        saved = PROwnerSelection.model_validate_json(report.artefacts.get(type="pr_owner_selection").content)
        ownership = next(entry for entry in saved.inputs.evidence if entry.ref == ".github/CODEOWNERS")
        assert json.loads(ownership.content) == {"src/payments.py": []}
        assert {identity.login for identity in saved.inputs.identities} == {"prolific", "current-owner"}
        github.list_team_members.assert_not_called()

    @pytest.mark.parametrize("chosen", ["support-owner", "specialist"])
    def test_all_declared_owners_can_reach_assignment(self, org_and_team, selection_enabled, chosen):
        org, team = org_and_team
        report, github = self.setup_report(org, team)
        _make_reviewer(org, "specialist", opted_in=False)
        selection_enabled.read.side_effect = lambda path: (
            "version: 1\nowners: [payments, support, '@specialist']\n" if path == "owners.yaml" else None
        )
        github.list_team_members.side_effect = lambda _org, slug, **kwargs: {
            "success": True,
            "logins": {"payments": ["current-owner"], "support": ["support-owner"]}[slug],
        }

        assert self.run_assignment(report, github, self.model(self.decision(chosen))) == [chosen]

        saved = PROwnerSelection.model_validate_json(report.artefacts.get(type="pr_owner_selection").content)
        ownership = next(entry for entry in saved.inputs.evidence if entry.ref == "owners.yaml")
        assert json.loads(ownership.content) == {"src/payments.py": ["payments", "support", "@specialist"]}
        assert {identity.login for identity in saved.inputs.identities} == {
            "prolific",
            "current-owner",
            "support-owner",
            "specialist",
        }
        github.add_pull_request_assignees.assert_called_once_with("PostHog/posthog", 123, [chosen])

    @pytest.mark.parametrize("candidate_count", [1, 5])
    def test_candidate_identity_queries_are_batched(self, org_and_team, django_assert_num_queries, candidate_count):
        org, team = org_and_team
        report, github = self.setup_report(org, team)
        logins = [f"candidate-{index}" for index in range(candidate_count)]
        for login in logins:
            _make_reviewer(org, login, opted_in=True)
        github.list_team_members.return_value = {"success": True, "logins": logins}
        assert self.run_assignment(report, github, self.model(self.decision(*logins))) == [logins[0]]
        saved = PROwnerSelection.model_validate_json(report.artefacts.get(type="pr_owner_selection").content)
        service = PROwnerDecisionService(team_id=team.id, report_id=str(report.id), github=github)

        with django_assert_num_queries(10):
            eligible = service.eligible_logins(saved)

        assert eligible.logins == frozenset(logins)
        assert eligible.opted_in == frozenset(logins)

    def test_large_team_stops_fetching_and_records_failed_lookup(self, org_and_team):
        org, team = org_and_team
        report, github = self.setup_report(org, team)
        roster_github = GitHubIntegration(MagicMock(kind="github"), source="test", priority=Priority.BATCH)
        github.list_team_members.side_effect = roster_github.list_team_members
        page = MagicMock(
            status_code=200,
            links={"next": {"url": "https://api.github.com/orgs/PostHog/teams/payments/members?page=2"}},
        )
        page.json.return_value = [{"login": f"owner-{index}"} for index in range(100)]
        second_page = MagicMock(
            status_code=200,
            links={"next": {"url": "https://api.github.com/orgs/PostHog/teams/payments/members?page=3"}},
        )
        second_page.json.return_value = [{"login": f"owner-{index}"} for index in range(100, 200)]
        model = self.model(self.decision("current-owner"))

        with patch.object(roster_github, "api_request", side_effect=[page, second_page]) as request:
            assert self.run_assignment(report, github, model) == []

        assert request.call_count == 2
        model.assert_not_called()
        github.add_pull_request_assignees.assert_not_called()
        saved = PROwnerSelection.model_validate_json(report.artefacts.get(type="pr_owner_selection").content)
        assert saved.decision.outcome == "lookup_failed"

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

    @pytest.mark.parametrize("choice", ["assigned", "unassigned", "claim", "ineligible_claim", "unrecovered_edit"])
    def test_existing_human_choice_prevents_selection(self, org_and_team, choice):
        org, team = org_and_team
        report, github = self.setup_report(org, team)
        if choice == "assigned":
            github.get_pull_request.return_value["assignees"] = ["prolific"]
        elif choice == "unassigned":
            github.was_ever_unassigned.return_value = {"success": True, "unassigned": True}
        elif choice == "unrecovered_edit":
            with patch("products.signals.backend.reviewer_rules.assignment_writer_enabled", return_value=False):
                self.edit_reviewers(report, "remove", "prolific")
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
        if choice == "unrecovered_edit":
            assert not report.artefacts.filter(type="reviewer_corrections").exists()
            github.add_pull_request_assignees.assert_not_called()
        if choice == "ineligible_claim":
            github.is_assignable.assert_called_once_with("PostHog/posthog", "prolific")

    @pytest.mark.parametrize("refresh", [False, True])
    def test_human_edit_while_model_runs_discards_decision(self, org_and_team, refresh):
        org, team = org_and_team
        report, github = self.setup_report(org, team)
        if refresh:
            github.is_assignable.return_value = {"success": False}
            assert self.run_assignment(report, github, self.model(self.decision("current-owner"))) == []
            report.artefacts.filter(type="pr_owner_selection").update(created_at=timezone.now() - timedelta(minutes=11))
            github.is_assignable.return_value = {"success": True, "assignable": True}

        async def edit_then_select(**kwargs):
            await sync_to_async(self.edit_reviewers)(report, "add", "prolific")
            return kwargs["validate"](json.dumps(self.decision("current-owner")))

        model = AsyncMock(side_effect=edit_then_select)
        assert self.run_assignment(report, github, model) == []
        model.assert_called_once()
        assert ReviewerRules.read_for_report(team_id=team.id, report_id=str(report.id)).corrections.pinned
        assert report.artefacts.filter(type="pr_owner_selection").count() == int(refresh)
        github.add_pull_request_assignees.assert_not_called()

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
    def test_confirmed_list_restricts_pr_selection(self, org_and_team, keep, enabled):
        org, team = org_and_team
        report, github = self.setup_report(org, team)
        self.edit_reviewers(report, "replace", *keep)
        self.edit_reviewers(report, "confirm")
        before = ReviewerRules.read_for_report(team_id=team.id, report_id=str(report.id))
        model = self.model(self.decision("current-owner", "prolific"))
        with patch(
            "products.signals.backend.reviewer_pr_assignment.team_research_reviewer_selection_enabled",
            return_value=enabled,
        ):
            assert self.run_assignment(report, github, model) == keep
        assert ReviewerRules.read_for_report(team_id=team.id, report_id=str(report.id)) == before

    def test_pin_does_not_force_pr_ownership(self, org_and_team):
        org, team = org_and_team
        report, github = self.setup_report(org, team)
        self.edit_reviewers(report, "add", "prolific")
        model = self.model(self.decision("current-owner"))
        assert self.run_assignment(report, github, model) == ["current-owner"]
        model.assert_called_once()

    @pytest.mark.parametrize("enabled", [True, False])
    def test_exclusion_blocks_pr_owner_in_both_policies(self, org_and_team, enabled):
        org, team = org_and_team
        report, github = self.setup_report(org, team)
        self.edit_reviewers(report, "remove", "prolific")
        model = self.model(self.decision("prolific", "current-owner"))
        with (
            patch(
                "products.signals.backend.reviewer_pr_assignment.team_research_reviewer_selection_enabled",
                return_value=enabled,
            ),
            patch(
                "products.signals.backend.reviewer_pr_assignment._owning_team",
                return_value=OwningTeam(slug="payments", logins=("prolific", "current-owner")),
            ),
        ):
            assert self.run_assignment(report, github, model) == ["current-owner"]

    def test_excluded_claimant_does_not_select_an_alternative(self, org_and_team):
        org, team = org_and_team
        report, github = self.setup_report(org, team)
        claimant = User.objects.get(email="prolific@example.com")
        claim_report(
            report=report, actor=ArtefactAttribution.from_user(claimant.id), user=claimant, was_impersonated=False
        )
        self.edit_reviewers(report, "remove", "prolific")
        model = self.model(self.decision("current-owner"))
        assert self.run_assignment(report, github, model) == []
        model.assert_not_called()
        github.add_pull_request_assignees.assert_not_called()

    def test_incomplete_human_history_stops_pr_selection(self, org_and_team):
        org, team = org_and_team
        report, github = self.setup_report(org, team)
        editor = User.objects.get(email="prolific@example.com")
        report.artefacts.filter(type="suggested_reviewers").update(actor_kind="user", created_by=editor)
        model = self.model(self.decision("current-owner"))
        assert self.run_assignment(report, github, model) == []
        model.assert_not_called()
        github.add_pull_request_assignees.assert_not_called()

    def test_exclusion_follows_current_github_identity(self, org_and_team):
        org, team = org_and_team
        report, github = self.setup_report(org, team)
        self.edit_reviewers(report, "remove", "prolific")
        user = User.objects.get(email="prolific@example.com")
        user.social_auth.filter(provider="github").update(extra_data={"login": "renamed-owner"})
        github.list_team_members.return_value = {"success": True, "logins": ["renamed-owner", "current-owner"]}
        model = self.model(self.decision("renamed-owner", "current-owner"))
        assert self.run_assignment(report, github, model) == ["current-owner"]

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

    @pytest.mark.parametrize("change", ["ownership", "team"])
    def test_changed_evidence_reassesses_owner_without_report_or_pr_change(
        self, org_and_team, selection_enabled, change
    ):
        org, team = org_and_team
        report, github = self.setup_report(org, team)
        github.is_assignable.return_value = {"success": False}
        model = self.model(self.decision("current-owner"))
        assert self.run_assignment(report, github, model) == []

        if change == "ownership":
            selection_enabled.read.side_effect = lambda path: (
                "version: 1\nowners: [billing]\n" if path == "owners.yaml" else None
            )
        else:
            github.list_team_members.return_value = {"success": True, "logins": ["prolific"]}
        model.side_effect = lambda **kwargs: kwargs["validate"](json.dumps(self.decision("prolific")))
        github.is_assignable.return_value = {"success": True, "assignable": True}

        assert self.run_assignment(report, github, model) == ["prolific"]
        assert model.call_count == 2
        assert report.artefacts.filter(type="pr_owner_selection").count() == 2

    @pytest.mark.parametrize("outcome", ["selected", "no_suitable_owner", "lookup_failed"])
    def test_decision_expires_even_with_unchanged_evidence(self, org_and_team, outcome):
        org, team = org_and_team
        report, github = self.setup_report(org, team)
        github.is_assignable.return_value = {"success": False}
        output = self.decision("current-owner") if outcome == "selected" else {**self.decision(), "outcome": outcome}
        model = self.model(output)
        assert self.run_assignment(report, github, model) == []
        report.artefacts.filter(type="pr_owner_selection").update(created_at=timezone.now() - timedelta(minutes=11))

        model.side_effect = lambda **kwargs: kwargs["validate"](json.dumps(self.decision("prolific")))
        github.is_assignable.return_value = {"success": True, "assignable": True}
        assert self.run_assignment(report, github, model) == ["prolific"]
        assert model.call_count == 2
        assert report.artefacts.filter(type="pr_owner_selection").count() == 2

    def test_failed_evidence_refresh_does_not_reuse_an_older_success(self, org_and_team):
        org, team = org_and_team
        report, github = self.setup_report(org, team)
        github.is_assignable.return_value = {"success": False}
        model = self.model(self.decision("current-owner"))
        assert self.run_assignment(report, github, model) == []
        github.is_assignable.return_value = {"success": True, "assignable": True}

        github.list_pull_request_files.return_value = {"success": False}
        for _ in range(2):
            assert self.run_assignment(report, github, model) == []
        github.add_pull_request_assignees.assert_not_called()
        assert model.call_count == 1
        assert report.artefacts.filter(type="pr_owner_selection").count() == 2

        github.list_pull_request_files.return_value = {"success": True, "paths": ["src/payments.py"]}
        model.side_effect = lambda **kwargs: kwargs["validate"](json.dumps(self.decision("prolific")))
        assert self.run_assignment(report, github, model) == ["prolific"]
        assert model.call_count == 2
        assert report.artefacts.filter(type="pr_owner_selection").count() == 3

    @pytest.mark.parametrize("change", ["human_edit", "head", "base", "claim", "access", "disabled"])
    def test_change_during_selection_rejects_old_decision(self, org_and_team, change):
        org, team = org_and_team
        report, github = self.setup_report(org, team)
        output = self.decision("current-owner")
        model = self.model(output)
        original_check = github.is_assignable.side_effect

        def change_state(*_args):
            if change == "human_edit":
                self.edit_reviewers(report, "remove", "current-owner")
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
        assert github.list_pull_request_files.call_count == 2
        assert report.artefacts.filter(type="pr_owner_selection").count() == 1
        github.add_pull_request_assignees.assert_called_once()
        github.request_pull_request_reviews.assert_called_once()
