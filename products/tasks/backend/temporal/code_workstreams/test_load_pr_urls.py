import random

import pytest

from posthog.models import Organization, Team

from products.tasks.backend.models import Task, TaskRun
from products.tasks.backend.temporal.code_workstreams.activities.load_pr_urls import (
    LoadTeamPrUrlsInput,
    _pr_url_belongs_to_task_repo,
    load_team_pr_urls,
)


@pytest.mark.parametrize(
    "pr_url,repository,expected",
    [
        ("https://github.com/acme/widgets/pull/12", "acme/widgets", True),
        # Repo names are case-insensitive on GitHub; the stored value is lowercased.
        ("https://github.com/AcMe/Widgets/pull/12", "acme/widgets", True),
        # Same repo name under a different owner must not match.
        ("https://github.com/evil/widgets/pull/12", "acme/widgets", False),
        # Same owner, different repo.
        ("https://github.com/acme/secrets/pull/12", "acme/widgets", False),
        # No configured repository ⇒ fail closed.
        ("https://github.com/acme/widgets/pull/12", None, False),
        ("https://github.com/acme/widgets/pull/12", "", False),
        # Not a parseable GitHub PR URL.
        ("https://github.com/acme/widgets", "acme/widgets", False),
        ("https://example.com/acme/widgets/pull/12", "acme/widgets", False),
        ("not-a-url", "acme/widgets", False),
    ],
)
def test_pr_url_belongs_to_task_repo(pr_url, repository, expected):
    assert _pr_url_belongs_to_task_repo(pr_url, repository) is expected


@pytest.mark.django_db(transaction=True)
def test_load_team_pr_urls_drops_cross_repo_pr_urls(activity_environment):
    org = Organization.objects.create(name=f"PrUrlsOrg-{random.randint(1, 99999)}")
    team = Team.objects.create(organization=org, name=f"PrUrlsTeam-{random.randint(1, 99999)}")

    def _run_with_pr(repository, pr_url):
        task = Task.objects.create(
            team=team,
            title="t",
            description="d",
            origin_product=Task.OriginProduct.USER_CREATED,
            repository=repository,
        )
        TaskRun.objects.create(
            task=task,
            team=team,
            status=TaskRun.Status.COMPLETED,
            output={"pr_url": pr_url},
        )

    _run_with_pr("acme/widgets", "https://github.com/acme/widgets/pull/1")
    # User-writable output.pr_url pointed at a repo the task never targeted.
    _run_with_pr("acme/widgets", "https://github.com/acme/secrets/pull/9")
    # Run without a configured repository must not leak its PR either.
    _run_with_pr(None, "https://github.com/acme/widgets/pull/2")

    result = activity_environment.run(load_team_pr_urls, LoadTeamPrUrlsInput(team_id=team.id))

    assert [ref.pr_url for ref in result.prs] == ["https://github.com/acme/widgets/pull/1"]
