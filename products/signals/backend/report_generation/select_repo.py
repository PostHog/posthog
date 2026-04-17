from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from posthog.models.integration import GitHubIntegration, Integration
from posthog.sync import database_sync_to_async

from products.signals.backend.temporal.types import SignalData, render_signals_to_text
from products.tasks.backend.services.custom_prompt_executor import run_sandbox_agent_get_structured_output
from products.tasks.backend.services.custom_prompt_runner import CustomPromptSandboxContext

if TYPE_CHECKING:
    from products.tasks.backend.services.custom_prompt_runner import OutputFn

logger = logging.getLogger(__name__)

# Small public repo to copy into the sandbox to init. Could be removed later when it's possible to create sandboxes without repos.
REPO_SELECTION_DUMMY_REPOSITORY = "PostHog/.github"


class RepoSelectionResult(BaseModel):
    repository: str | None = Field(
        description="Selected repository in 'owner/repo' format, or null if none of the candidates are relevant."
    )
    reason: str = Field(description="Why this repository was selected, or why none of the candidates matched.")


_MAX_GITHUB_REPOS = 500


def _list_candidate_repos(team_id: int) -> list[str]:
    """Fetch all repositories accessible via the team's GitHub integrations."""
    # Not cached: it's instant if 1 repo attached (should happen often). Caching the list of repos
    # doesn't make much sense (as we would need to provide these tokens inside the prompt anyway).
    # If >1 repo -> the research per-signal can't be cached, as we need to pick one.
    integrations = Integration.objects.filter(team_id=team_id, kind="github")
    repos: set[str] = set()
    for integration in integrations:
        github = GitHubIntegration(integration)
        repo_entries = github.list_all_repositories(max_repos=_MAX_GITHUB_REPOS)
        for repo in repo_entries:
            full_name = repo.get("full_name")
            if full_name:
                repos.add(full_name.lower())
                if len(repos) >= _MAX_GITHUB_REPOS:
                    logger.warning("repo_list_capped team_id=%s cap=%s", team_id, _MAX_GITHUB_REPOS)
                    return sorted(repos)
    return sorted(repos)


def _build_repo_selection_prompt(signals: list[SignalData], candidate_repos: list[str]) -> str:
    """Build the prompt for the sandbox agent to select the most relevant repository."""
    signals_text = render_signals_to_text(signals)
    schema_json = json.dumps(RepoSelectionResult.model_json_schema(), indent=2)

    repo_list = "\n".join(f"{i + 1}. `{repo}`" for i, repo in enumerate(candidate_repos))

    return f"""You are a repository selection agent. Your job is to determine which GitHub repository
is most relevant to a set of signals from PostHog's Signals product.

The signals below describe issues, feature requests, bugs, or observations reported by users.
You need to figure out which repository's codebase these signals are about — i.e., which repo
a developer would look at to investigate or fix the issues described.

## Signals

{signals_text}

## Candidate repositories

{repo_list}

## Instructions

1. For each candidate repository, run `gh repo view <repo> --json description,name,url` to understand
   what it contains.
2. If the signals mention specific code paths, files, features, or libraries, use
   `gh search code "<keyword>" --repo <repo> --limit 10` to check which repos contain matching code.
3. Pick the single repository whose codebase is most likely the **subject** of these signals —
   the repo where a developer would go to investigate or fix the issues described.
4. If none of the repositories are clearly relevant to the signals, return `repository: null`.
5. Do not guess — if you cannot determine relevance with reasonable confidence, return null.

## Output format

Respond with a JSON object matching this schema:

<jsonschema>
{schema_json}
</jsonschema>"""


async def select_repository_for_report(
    team_id: int,
    user_id: int,
    signals: list[SignalData],
    *,
    sandbox_environment_id: str | None = None,
    verbose: bool = False,
    output_fn: OutputFn = None,
) -> RepoSelectionResult:
    """Select the most relevant repository for a set of signals."""
    candidate_repos = await database_sync_to_async(_list_candidate_repos, thread_sensitive=False)(team_id)
    if len(candidate_repos) == 0:
        return RepoSelectionResult(
            repository=None,
            reason="No GitHub repositories connected to this team.",
        )
    if len(candidate_repos) == 1:
        return RepoSelectionResult(
            repository=candidate_repos[0],
            reason=f"Single repository connected: {candidate_repos[0]}",
        )
    if output_fn:
        output_fn(f"Selecting repository from {len(candidate_repos)} candidates...")
    prompt = _build_repo_selection_prompt(signals, candidate_repos)
    context = CustomPromptSandboxContext(
        team_id=team_id,
        user_id=user_id,
        repository=REPO_SELECTION_DUMMY_REPOSITORY,
        sandbox_environment_id=sandbox_environment_id,
        posthog_mcp_scopes=[],  # Only uses gh CLI — no PostHog MCP tools, only internal scopes (task:write, llm_gateway:read)
    )
    result = await run_sandbox_agent_get_structured_output(
        prompt=prompt,
        context=context,
        model_to_validate=RepoSelectionResult,
        step_name="repo_selection",
        verbose=verbose,
        output_fn=output_fn,
    )
    # Validate that the selected repo is actually in the candidate list
    if result.repository is not None:
        result.repository = result.repository.strip().lower()
    if result.repository is not None and result.repository not in candidate_repos:
        logger.warning(
            "repo selection agent returned unknown repository %s, treating as no match",
            result.repository,
        )
        return RepoSelectionResult(
            repository=None,
            reason=f"Agent selected '{result.repository}' which is not in the candidate list. Original reason: '{result.reason}'",
        )
    logger.info(
        "repo selection completed",
        extra={"repository": result.repository, "reason": result.reason, "candidates": len(candidate_repos)},
    )
    return result
