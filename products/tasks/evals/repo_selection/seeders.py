"""Install the synthetic repository catalog into one case's isolated team.

The seeded team-level GitHub integration carries a placeholder token and a fresh light and heavy
cache, so the production selector reads the fixture instead of GitHub: `sync_full_cache` takes its
TTL fast path, and the agent's `execute-sql` queries see only these rows.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from django.utils import timezone

from posthog.integrations import IntegrationManager
from posthog.models.integration_repository_cache import IntegrationRepositoryCacheEntry, summarize_tree
from posthog.models.repo_routing_rule import RepoRoutingRule

from products.tasks.backend.facade.agents import CustomPromptSandboxContext

from .fixtures import FIXTURE_VERSION, ORG, REPOSITORIES, FixtureRepository, RepoSelectionScenario, fixture_fingerprint

# Not a credential. GitHub rejects it, so a `gh api` call from the sandbox cannot reach real repositories.
PLACEHOLDER_GITHUB_TOKEN = "fixture-token-not-a-github-credential"


def _cache_entry(
    integration_id: int, team_id: int, repo: FixtureRepository, now: datetime
) -> IntegrationRepositoryCacheEntry:
    tree_paths = "\n".join(repo.tree_paths)
    tree = summarize_tree(tree_paths)
    return IntegrationRepositoryCacheEntry(
        integration_id=integration_id,
        team_id=team_id,
        full_name=repo.full_name.lower(),
        description=repo.description,
        topics=list(repo.topics),
        archived=repo.archived,
        primary_language=repo.primary_language,
        default_branch="main",
        default_branch_sha=repo.default_branch_sha,
        readme=repo.readme,
        tree_paths=tree_paths,
        tree_truncated=False,
        file_count=tree.file_count,
        top_extensions=list(tree.top_extensions),
        tree_hash=tree.tree_hash,
        commits_last_30_days=repo.commits_last_30_days,
        recent_author_count=repo.recent_author_count,
        merged_pull_request_count=repo.merged_pull_request_count,
        # Fresh, so the selector does not enqueue an activity refresh that would call GitHub.
        activity_updated_at=now,
    )


def install_repository_catalog(team_id: int, user_id: int, scenario: RepoSelectionScenario) -> dict[str, Any]:
    now = timezone.now()
    record = IntegrationManager.github.oauth.create(
        team_id,
        external_id=f"eval-fixture-{team_id}",
        config={"installation_id": f"eval-fixture-{team_id}", "account": {"type": "Organization", "name": ORG}},
        sensitive_config={"access_token": PLACEHOLDER_GITHUB_TOKEN},
        created_by_id=user_id,
    )
    # Production fills the cache from GitHub. The fixture stores a synthetic listing, so the selector never calls GitHub.
    IntegrationManager.github.oauth.set_repository_cache(
        team_id,
        record.id,
        repositories=[
            {
                "id": index,
                "name": repo.name,
                "full_name": repo.full_name,
                "private": repo.private,
                "archived": repo.archived,
                "language": repo.primary_language,
                "default_branch": "main",
            }
            for index, repo in enumerate(REPOSITORIES, start=1)
        ],
        updated_at=now,
    )
    IntegrationRepositoryCacheEntry.objects.bulk_create(
        [_cache_entry(record.id, team_id, repo, now) for repo in REPOSITORIES]
    )
    RepoRoutingRule.objects.bulk_create(
        [
            RepoRoutingRule(
                team_id=team_id,
                rule_text=rule.rule_text,
                repository=rule.repository,
                priority=priority,
                created_by_id=user_id,
            )
            for priority, rule in enumerate(scenario.routing_rules)
        ]
    )
    return {
        "fixture_version": FIXTURE_VERSION,
        "fixture_fingerprint": fixture_fingerprint(),
        "candidate_repositories": sorted(repo.full_name.lower() for repo in REPOSITORIES if not repo.archived),
        "routing_rules": [f"{rule.rule_text} → {rule.repository}" for rule in scenario.routing_rules],
    }


def scenario_seeder(scenario: RepoSelectionScenario) -> Callable[[CustomPromptSandboxContext], dict[str, Any]]:
    def seed(context: CustomPromptSandboxContext) -> dict[str, Any]:
        return install_repository_catalog(context.team_id, context.user_id, scenario)

    seed.__name__ = f"seed_{scenario.name}"
    return seed
