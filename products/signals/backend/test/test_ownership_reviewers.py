from types import SimpleNamespace

import pytest
from unittest.mock import MagicMock, patch

from posthog.models import User
from posthog.models.organization import OrganizationMembership
from posthog.ownership.paths import PathOwnership

from products.signals.backend.artefact_attribution import ArtefactAttribution
from products.signals.backend.artefact_schemas import SignalFinding, SuggestedReviewers
from products.signals.backend.models import SignalReport, SignalReportArtefact
from products.signals.backend.report_generation.ownership_reviewers import (
    OwnershipReviewer,
    _codeowners_for_paths,
    suggest_repository_owners,
)
from products.signals.backend.report_generation.resolve_reviewers import _ResolvedReviewer
from products.signals.backend.temporal.agentic.report import (
    ArtefactDraft,
    _append_agentic_report_artefacts,
    _build_reviewers_content,
)


def test_codeowners_uses_first_file_and_last_matching_rule():
    github = MagicMock()
    github.get_file_contents.side_effect = lambda _repo, location: (
        {"content": "*.py @example/old\n/src/ @example/current\n/src/generated.py\n*** @example/invalid\n"}
        if location == ".github/CODEOWNERS"
        else {"content": "* @example/ignored"}
    )

    matches = _codeowners_for_paths(github, "example/app", ["src/app.py", "src/generated.py", "lib/app.py"])

    assert matches == {
        "src/app.py": ("@example/current",),
        "src/generated.py": (),
        "lib/app.py": ("@example/old",),
    }
    github.get_file_contents.assert_called_once_with("example/app", ".github/CODEOWNERS")


def test_codeowners_uses_root_when_github_file_is_absent():
    github = MagicMock()
    github.get_file_contents.side_effect = [None, {"content": "*.py @author"}]

    assert _codeowners_for_paths(github, "example/app", ["src/app.py"]) == {"src/app.py": ("@author",)}


@pytest.mark.django_db
def test_owners_yaml_precedes_a_different_codeowner(team):
    project_members = {}
    for login in ("primary", "backup", "secondary"):
        member = User.objects.create(email=f"{login}@example.com")
        OrganizationMembership.objects.create(organization=team.organization, user=member)
        project_members[login] = member
    github = MagicMock()
    github.get_file_contents.side_effect = [{"content": "/src/ @example/main @example/other\n"}]
    github.list_team_members.side_effect = lambda _org, slug: {
        "success": True,
        "logins": ["primary", "backup"] if slug == "main" else ["secondary", "outside"],
    }
    with (
        patch(
            "products.signals.backend.report_generation.ownership_reviewers.GitHubIntegration.first_for_team_repository",
            return_value=github,
        ),
        patch(
            "products.signals.backend.report_generation.ownership_reviewers.resolve_path_owners",
            return_value=PathOwnership(team_by_path={"src/app.py": "main"}, registry={}, resolved=True),
        ),
        patch(
            "products.signals.backend.report_generation.ownership_reviewers.resolve_org_github_login_to_users",
            return_value=project_members,
        ),
    ):
        reviewers = suggest_repository_owners(team.id, "example/app", ["src/app.py"], ["secondary"])

    assert reviewers == [
        OwnershipReviewer(login="backup", reason="owners.yaml: src/app.py"),
        OwnershipReviewer(login="secondary", reason="CODEOWNERS: src/app.py"),
    ]


@pytest.mark.django_db
def test_only_one_reviewer_per_ownership_source_across_paths(team):
    members = {}
    for login in ("first", "second", "third", "fourth"):
        member = User.objects.create(email=f"{login}@example.com")
        OrganizationMembership.objects.create(organization=team.organization, user=member)
        members[login] = member
    github = MagicMock()
    github.get_file_contents.return_value = {"content": "/src/a.py @third\n/src/b.py @fourth\n"}
    github.list_team_members.side_effect = lambda _org, slug: {
        "success": True,
        "logins": ["first"] if slug == "one" else ["second"],
    }
    with (
        patch(
            "products.signals.backend.report_generation.ownership_reviewers.GitHubIntegration.first_for_team_repository",
            return_value=github,
        ),
        patch(
            "products.signals.backend.report_generation.ownership_reviewers.resolve_path_owners",
            return_value=PathOwnership(team_by_path={"src/a.py": "one", "src/b.py": "two"}, registry={}, resolved=True),
        ),
        patch(
            "products.signals.backend.report_generation.ownership_reviewers.resolve_org_github_login_to_users",
            return_value=members,
        ),
    ):
        reviewers = suggest_repository_owners(team.id, "example/app", ["src/a.py", "src/b.py"], [])

    assert reviewers == [
        OwnershipReviewer(login="first", reason="owners.yaml: src/a.py"),
        OwnershipReviewer(login="third", reason="CODEOWNERS: src/a.py"),
    ]


@pytest.mark.django_db
def test_codeowners_email_matches_a_project_member_with_a_github_identity(team):
    member = User.objects.create(email="owner@example.com")
    OrganizationMembership.objects.create(organization=team.organization, user=member)
    github = MagicMock()
    github.get_file_contents.return_value = {"content": "*.py OWNER@EXAMPLE.COM\n"}
    with (
        patch(
            "products.signals.backend.report_generation.ownership_reviewers.GitHubIntegration.first_for_team_repository",
            return_value=github,
        ),
        patch(
            "products.signals.backend.report_generation.ownership_reviewers.resolve_path_owners",
            return_value=PathOwnership(team_by_path={}, registry={}, resolved=False),
        ),
        patch(
            "products.signals.backend.report_generation.ownership_reviewers.resolve_org_github_login_to_users",
            return_value={"linked": member},
        ),
        patch.object(User, "get_github_login", return_value="linked"),
    ):
        reviewers = suggest_repository_owners(team.id, "example/app", ["src/app.py"], [])

    assert reviewers == [OwnershipReviewer(login="linked", reason="CODEOWNERS: src/app.py")]


@pytest.mark.django_db
def test_codeowners_routes_without_owners_yaml_only_to_a_project_member(team):
    member = User.objects.create(email="inside@example.com")
    OrganizationMembership.objects.create(organization=team.organization, user=member)
    github = MagicMock()
    github.get_file_contents.return_value = {"content": "/src/ @example/other @external\n"}
    github.list_team_members.return_value = {"success": True, "logins": ["outside", "inside"]}
    with (
        patch(
            "products.signals.backend.report_generation.ownership_reviewers.GitHubIntegration.first_for_team_repository",
            return_value=github,
        ),
        patch(
            "products.signals.backend.report_generation.ownership_reviewers.resolve_path_owners",
            return_value=PathOwnership(team_by_path={}, registry={}, resolved=False),
        ),
        patch(
            "products.signals.backend.report_generation.ownership_reviewers.resolve_org_github_login_to_users",
            return_value={"inside": member},
        ),
    ):
        reviewers = suggest_repository_owners(team.id, "example/app", ["src/app.py"], [])

    assert reviewers == [OwnershipReviewer(login="inside", reason="CODEOWNERS: src/app.py")]


def test_ownership_suggestions_follow_repository_owners_then_commit_authors():
    author = _ResolvedReviewer(login="author", name=None, commits=[], weight=1.0)
    resolution = SimpleNamespace(reviewers=[author], diagnostics=SimpleNamespace(outcome="resolved"))
    finding = SignalFinding(
        signal_id="sig-1",
        relevant_commit_hashes={"abcdef0": "fix"},
        relevant_code_paths=["src/app.py"],
        data_queried="",
        verified=True,
    )
    with (
        patch(
            "products.signals.backend.temporal.agentic.report.resolve_suggested_reviewers_with_diagnostics",
            return_value=resolution,
        ),
        patch(
            "products.signals.backend.temporal.agentic.report.suggest_repository_owners",
            return_value=[
                OwnershipReviewer(login="primary", reason="owners.yaml: src/app.py"),
                OwnershipReviewer(login="secondary", reason="CODEOWNERS: src/app.py"),
            ],
        ),
    ):
        reviewers = _build_reviewers_content(1, "example/app", [finding]).reviewers

    assert [entry["github_login"] for entry in reviewers] == ["primary", "secondary", "author"]
    assert reviewers[1]["reason"] == "CODEOWNERS: src/app.py"


@pytest.mark.django_db
def test_later_research_does_not_replace_a_human_reviewer_edit(team, user):
    report = SignalReport.objects.create(team=team, status=SignalReport.Status.IN_PROGRESS)
    manually_selected = SuggestedReviewers.model_validate([{"github_login": "chosen"}])
    SignalReportArtefact.append_status(
        team_id=team.id,
        report_id=str(report.id),
        content=manually_selected,
        attribution=ArtefactAttribution.from_user(user.id),
        reevaluate_autostart=False,
    )

    wrote_reviewers = _append_agentic_report_artefacts(
        team_id=team.id,
        report_id=str(report.id),
        artefacts=[
            ArtefactDraft(
                content=SuggestedReviewers.model_validate([{"github_login": "automatic"}]),
                attribution=ArtefactAttribution.system(),
            )
        ],
    )

    assert not wrote_reviewers
    assert (
        SignalReportArtefact.objects.filter(
            report=report, type=SignalReportArtefact.ArtefactType.SUGGESTED_REVIEWERS
        ).count()
        == 1
    )
