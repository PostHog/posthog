"""Eval-only patches applied to the Temporal worker process.

The synthetic GitHub integrations provisioned by the eval (config marker
``eval_synthetic``) have no real GitHub App installation behind them. The
implementation path force-refreshes installation tokens (`start_agent_server`,
`get_pr_context`), which 404s against GitHub and flips the integration into the
permanently-unavailable state, killing the run. For eval integrations only,
token refresh becomes a no-op and the unavailable flag is ignored — every other
integration behaves exactly as in production.

Never import this module outside the eval worker bootstrap (run_worker.py).
"""

import logging

logger = logging.getLogger(__name__)

EVAL_MARKER = "eval_synthetic"


def apply() -> None:
    import os
    from pathlib import Path

    # Force-set the repo bind-mount map from the authored task set — this is the one
    # place guaranteed to run inside the worker process, after all env layering.
    tasks_dir = Path(__file__).resolve().parents[1] / "tasks"
    workspace = Path(os.environ.get("SELFDRIVING_EVAL_WORKSPACE", "/tmp/selfdriving-eval-workspace"))
    entries = [
        f"acme/{p.name}:{workspace / 'repos' / p.name}"
        for p in sorted(tasks_dir.iterdir())
        if (p / "task.json").exists()
    ]
    os.environ["SANDBOX_REPO_MOUNT_MAP"] = ",".join(entries)
    logger.warning("eval worker patch: SANDBOX_REPO_MOUNT_MAP forced with %d entries", len(entries))

    # The user's .env pins SANDBOX_MCP_URL to the production MCP, which rejects local
    # tokens — the research agent then runs with no PostHog data access at all. Point
    # eval sandboxes at the local wrangler MCP dev server instead.
    from django.conf import settings

    local_mcp = "http://host.docker.internal:8787/mcp"
    if settings.SANDBOX_MCP_URL != local_mcp:
        logger.warning("eval worker patch: overriding SANDBOX_MCP_URL %s -> %s", settings.SANDBOX_MCP_URL, local_mcp)
        settings.SANDBOX_MCP_URL = local_mcp
        os.environ["SANDBOX_MCP_URL"] = local_mcp

    from posthog.models.github_integration_base import GitHubIntegrationBase

    original_refresh = GitHubIntegrationBase.refresh_access_token
    original_unavailable = GitHubIntegrationBase.installation_unavailable

    def refresh_access_token(self) -> None:  # type: ignore[no-untyped-def]
        if self.integration.config.get(EVAL_MARKER):
            logger.info("eval: skipping GitHub token refresh for synthetic integration %s", self.integration.id)
            return
        original_refresh(self)

    def installation_unavailable(self) -> bool:  # type: ignore[no-untyped-def]
        if self.integration.config.get(EVAL_MARKER):
            return False
        return original_unavailable(self)

    GitHubIntegrationBase.refresh_access_token = refresh_access_token  # type: ignore[method-assign]  # ty: ignore[invalid-assignment]
    GitHubIntegrationBase.installation_unavailable = installation_unavailable  # type: ignore[method-assign]  # ty: ignore[invalid-assignment]

    # Bind-mounted eval repos have no GitHub remote, so the signed-commit tool can't work;
    # allow plain `git commit` inside eval sandboxes so the patch lands as real commits.
    from products.tasks.backend.logic.services.docker_sandbox import DockerSandbox

    original_create = DockerSandbox.create

    def create(config):  # type: ignore[no-untyped-def]
        config.environment_variables = {
            **(config.environment_variables or {}),
            "POSTHOG_ALLOW_UNSIGNED_GIT": "1",
        }
        return original_create(config)

    DockerSandbox.create = staticmethod(create)  # type: ignore[method-assign]  # ty: ignore[invalid-assignment]
    logger.info("eval worker patch applied: synthetic GitHub integrations never refresh; unsigned git allowed")
