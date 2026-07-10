"""HogQL for the agent LLM token spend attributed to one PR.

Attribution is by git **branch**, not head SHA: a coding agent stamps ``$ai_git_branch`` on its
``$ai_generation`` events at capture time — before the PR exists — and the ``github_pull_requests``
snapshot keeps only the latest head, so a head-SHA join would drop every push but the last (SPEC §7).
Reads the ``events`` table directly (not the warehouse) through the same curated read handle, so the
team scope and warehouse ACL bypass rules stay in one place.
"""

from datetime import timedelta

from django.utils import timezone

from posthog.hogql import ast

from products.engineering_analytics.backend.facade.contracts import PRLLMSpend
from products.engineering_analytics.backend.logic.queries._curated import CuratedGitHubSource
from products.engineering_analytics.backend.logic.queries._pr_header import pr_header_placeholders, pr_header_query

# Tokens are spent before a PR opens (the agent runs, then the PR is created), so the window reaches
# back this far from created_at. The tradeoff: head_branch is reused across PRs over time, so a
# recycled branch can pull in a neighbouring PR's spend — bounded by capping the window at the PR's
# own open→merge/close life (below).
_LEAD_DAYS = 14

_HEADER = pr_header_query("head_branch, created_at, merged_at, closed_at")

# The repo guard keeps events that stamped no $ai_git_repo (older agents that only carried the branch)
# while still rejecting a same-named branch in a different repo once the repo is stamped. coalesce
# collapses both NULL (property absent) and '' to the pass-through case.
_SPEND = """
    SELECT
        sum(toFloat(properties.$ai_total_cost_usd)) AS cost_usd,
        sum(toInt(properties.$ai_input_tokens)) AS input_tokens,
        sum(toInt(properties.$ai_output_tokens)) AS output_tokens,
        count() AS generations
    FROM events
    WHERE event = '$ai_generation'
        AND properties.$ai_git_branch = {branch}
        AND (coalesce(properties.$ai_git_repo, '') = '' OR properties.$ai_git_repo = {repo_full})
        AND timestamp >= {window_start}
        AND timestamp <= {window_end}
"""


def query_pr_llm_spend(
    *,
    curated: CuratedGitHubSource,
    pr_number: int,
    repo_owner: str,
    repo_name: str,
) -> PRLLMSpend | None:
    header = curated.run(
        _HEADER.replace("__PR_SOURCE__", curated.pr_source()),
        query_type="engineering_analytics.pr_llm_spend.header",
        placeholders=pr_header_placeholders(pr_number=pr_number, repo_owner=repo_owner, repo_name=repo_name),
    )
    if not header.results:
        return None
    head_branch, created_at, merged_at, closed_at = header.results[0]
    # No branch means nothing to join on; no created_at means the window can't be placed (created_at
    # comes from parseDateTimeBestEffort, which yields NULL on a malformed value).
    if not head_branch or created_at is None:
        return None

    # Open PRs are still accruing spend, so cap at now(); a closed/merged PR caps at its close.
    window_end = merged_at or closed_at or timezone.now()
    response = curated.run(
        _SPEND,
        query_type="engineering_analytics.pr_llm_spend",
        placeholders={
            "branch": ast.Constant(value=head_branch),
            "repo_full": ast.Constant(value=f"{repo_owner}/{repo_name}"),
            "window_start": ast.Constant(value=created_at - timedelta(days=_LEAD_DAYS)),
            "window_end": ast.Constant(value=window_end),
        },
    )
    rows = response.results or []
    if not rows:
        return None
    cost_usd, input_tokens, output_tokens, generations = rows[0]
    generations = int(generations or 0)
    # None when nothing matched, so the endpoint returns llm_spend=null and the UI hides the row.
    if generations == 0:
        return None
    return PRLLMSpend(
        cost_usd=float(cost_usd or 0.0),
        input_tokens=int(input_tokens or 0),
        output_tokens=int(output_tokens or 0),
        generations=generations,
    )
