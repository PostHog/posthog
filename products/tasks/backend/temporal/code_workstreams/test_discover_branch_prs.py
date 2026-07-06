import random

import pytest
from unittest.mock import MagicMock, patch

from posthog.models import Integration, Organization, Team

from products.tasks.backend.models import Task, TaskRun
from products.tasks.backend.temporal.code_workstreams.activities.discover_branch_prs import (
    DiscoverBranchPrsInput,
    _collect_branch_candidates,
    discover_branch_prs,
)

_RESOLVE = "products.tasks.backend.temporal.code_workstreams.activities.discover_branch_prs.resolve_github_integration"


def _make_team():
    org = Organization.objects.create(name=f"DiscoverOrg-{random.randint(1, 99999)}")
    team = Team.objects.create(organization=org, name=f"DiscoverTeam-{random.randint(1, 99999)}")
    # A team-level GitHub integration so TeamIntegrationResolver resolves a usable id.
    Integration.objects.create(team=team, kind="github", config={}, sensitive_config={}, errors="")
    return team


def _run_on_branch(team, repository, branch, *, pr_url=None, status=TaskRun.Status.COMPLETED):
    task = Task.objects.create(
        team=team,
        title="t",
        description="d",
        origin_product=Task.OriginProduct.USER_CREATED,
        repository=repository,
    )
    return TaskRun.objects.create(
        task=task,
        team=team,
        status=status,
        branch=branch,
        output={"pr_url": pr_url} if pr_url else None,
    )


def _fake_integration(urls_by_branch):
    fake = MagicMock()
    fake.find_pull_request_urls_for_branch.side_effect = lambda repo, branch: urls_by_branch.get(branch, [])
    return fake


@pytest.mark.django_db(transaction=True)
def test_discovers_pr_for_branch_without_recorded_pr_url(activity_environment):
    team = _make_team()
    _run_on_branch(team, "acme/widgets", "posthog-code/feature-x")

    fake = _fake_integration({"posthog-code/feature-x": ["https://github.com/acme/widgets/pull/7"]})
    with patch(_RESOLVE, return_value=fake):
        result = activity_environment.run(
            discover_branch_prs,
            DiscoverBranchPrsInput(team_id=team.id, known_pr_urls=[], budget=50),
        )

    assert [ref.pr_url for ref in result.prs] == ["https://github.com/acme/widgets/pull/7"]
    fake.find_pull_request_urls_for_branch.assert_called_once_with("acme/widgets", "posthog-code/feature-x")


@pytest.mark.django_db(transaction=True)
def test_skips_pr_urls_already_known(activity_environment):
    team = _make_team()
    _run_on_branch(team, "acme/widgets", "posthog-code/feature-x")

    fake = _fake_integration({"posthog-code/feature-x": ["https://github.com/acme/widgets/pull/7"]})
    with patch(_RESOLVE, return_value=fake):
        result = activity_environment.run(
            discover_branch_prs,
            DiscoverBranchPrsInput(
                team_id=team.id,
                known_pr_urls=["https://github.com/acme/widgets/pull/7"],
                budget=50,
            ),
        )

    assert result.prs == []


@pytest.mark.django_db(transaction=True)
def test_respects_budget(activity_environment):
    team = _make_team()
    _run_on_branch(team, "acme/widgets", "branch-a")
    _run_on_branch(team, "acme/widgets", "branch-b")

    fake = _fake_integration(
        {
            "branch-a": ["https://github.com/acme/widgets/pull/1"],
            "branch-b": ["https://github.com/acme/widgets/pull/2"],
        }
    )
    with patch(_RESOLVE, return_value=fake):
        result = activity_environment.run(
            discover_branch_prs,
            DiscoverBranchPrsInput(team_id=team.id, known_pr_urls=[], budget=1),
        )

    assert len(result.prs) == 1


@pytest.mark.django_db(transaction=True)
def test_zero_budget_makes_no_github_calls(activity_environment):
    team = _make_team()
    _run_on_branch(team, "acme/widgets", "posthog-code/feature-x")

    fake = _fake_integration({"posthog-code/feature-x": ["https://github.com/acme/widgets/pull/7"]})
    with patch(_RESOLVE, return_value=fake) as resolve:
        result = activity_environment.run(
            discover_branch_prs,
            DiscoverBranchPrsInput(team_id=team.id, known_pr_urls=[], budget=0),
        )

    assert result.prs == []
    resolve.assert_not_called()


@pytest.mark.django_db(transaction=True)
def test_collect_candidates_dedupes_repo_branch_and_skips_base_and_repoless():
    team = _make_team()
    # Same (repo, branch) twice, plus a case-only repo variant — all one candidate.
    _run_on_branch(team, "acme/widgets", "posthog-code/feature-x")
    _run_on_branch(team, "acme/widgets", "posthog-code/feature-x")
    _run_on_branch(team, "AcMe/Widgets", "posthog-code/feature-x")
    _run_on_branch(team, "acme/widgets", "main")  # base branch: skipped
    _run_on_branch(team, None, "posthog-code/feature-y")  # no repo: skipped
    _run_on_branch(team, "acme/widgets", "posthog-code/feature-z")

    candidates = _collect_branch_candidates(team.id)

    pairs = sorted((c.repository.casefold(), c.branch) for c in candidates)
    assert pairs == [
        ("acme/widgets", "posthog-code/feature-x"),
        ("acme/widgets", "posthog-code/feature-z"),
    ]


@pytest.mark.django_db(transaction=True)
def test_collect_candidates_requires_an_integration():
    org = Organization.objects.create(name=f"NoIntOrg-{random.randint(1, 99999)}")
    team = Team.objects.create(organization=org, name=f"NoIntTeam-{random.randint(1, 99999)}")
    # No integration to authenticate with ⇒ no candidate.
    _run_on_branch(team, "acme/widgets", "posthog-code/feature-x")

    assert _collect_branch_candidates(team.id) == []
