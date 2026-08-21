from __future__ import annotations

from datetime import UTC, datetime, timedelta

from django.utils import timezone

from posthog.models.integration import Integration
from posthog.models.integration_repository_cache import IntegrationRepositoryCacheEntry

from products.signals.evals.agentic.repos import REGISTRY
from products.tasks.backend.facade.agents import CustomPromptSandboxContext


def seed_research_sessions(context: CustomPromptSandboxContext) -> dict[str, object]:
    from posthog.session_recordings.queries.test.session_replay_sql import produce_replay_summary

    from products.signals.evals.agentic.cases.research import SESSION_IDS

    now = datetime.now(UTC)
    for index, session_id in enumerate(SESSION_IDS):
        first_timestamp = now - timedelta(days=index + 1, minutes=10)
        produce_replay_summary(
            team_id=context.team_id,
            session_id=session_id,
            distinct_id=f"signals-eval-session-{index + 1}",
            first_timestamp=first_timestamp,
            last_timestamp=first_timestamp + timedelta(minutes=10),
            first_url="https://app.hedgebox.test/app/files",
            all_urls=["https://app.hedgebox.test/app/files"],
            click_count=4,
            keypress_count=2,
            mouse_activity_count=8,
            active_milliseconds=180_000,
            snapshot_source="web",
            snapshot_library="web",
        )
    return {"session_ids": list(SESSION_IDS)}


def seed_repository_catalog(context: CustomPromptSandboxContext) -> dict[str, object]:
    repositories = [
        {"id": index, "name": repo.repo, "full_name": repo.full_name}
        for index, repo in enumerate(REGISTRY.values(), start=1)
    ]
    integration = Integration.objects.create(
        team_id=context.team_id,
        kind="github",
        integration_id=f"eval-{context.team_id}",
        config={"installation_id": f"eval-{context.team_id}"},
        sensitive_config={},
        repository_cache=repositories,
        repository_cache_updated_at=timezone.now(),
    )
    IntegrationRepositoryCacheEntry.objects.bulk_create(
        [
            IntegrationRepositoryCacheEntry(
                integration=integration,
                team_id=context.team_id,
                full_name=repo.full_name,
                description=repo.domain,
                topics=[],
                archived=False,
                fork=False,
                primary_language=repo.primary_language,
                default_branch="main",
                default_branch_sha="0" * 40,
                readme=repo.domain,
                tree_paths="README.md\nsrc/index.ts",
            )
            for repo in REGISTRY.values()
        ]
    )
    return {"integration_id": integration.id, "repository_count": len(repositories)}
