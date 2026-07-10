"""HogQL for the agent LLM token spend attributed to one PR.

Attribution is by git **branch**, not head SHA: a coding agent stamps ``$ai_git_branch`` on its
``$ai_generation`` events at capture time — before the PR exists — and the ``github_pull_requests``
snapshot keeps only the latest head, so a head-SHA join would drop every push but the last (SPEC §7).
Reads the ``events`` table directly (not the warehouse) through the same curated read handle, so the
team scope and warehouse ACL bypass rules stay in one place.

**Attribution rule (session propagation).** A per-event branch stamp alone under-counts: an agent
explores, runs tools, and thinks *before* it creates the feature branch, and those early generations
are stamped with whatever branch was checked out at the time — typically the base branch (agents stamp
every event, so pre-branch work carries the base ref, not a blank). To credit that lead-in to the PR
it became, spend is grouped by AI session (``$ai_session_id``, falling back to ``$ai_trace_id``) and,
for a session whose first non-base branch stamp is this PR's head ref H, the following count toward H:

1. any event stamped H directly (the plain branch rule, always preserved);
2. the prefix — events before that first feature stamp that are unstamped or stamped with the base ref
   M — because that is the pre-branch exploration that produced the branch (base-ref stamps are neutral
   here for exactly that reason: they are what an always-stamping agent writes before the branch exists);
3. carry-forward — an unstamped event after the first feature stamp counts for whichever branch was most
   recently stamped at-or-before it, covering generations the agent emits without re-stamping the branch.

Base-ref stamps at or after the first feature stamp are neutral, not credited: switching back to the
base branch ends attribution. Events stamped with any other branch never count toward H. Events with no
session and no trace id have no group, so they can only count via their own direct H stamp. The window
and repo guard stay the OUTER filter on every counted event: only in-window candidates form the groups.
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

_HEADER = pr_header_query("head_branch, base_branch, created_at, merged_at, closed_at")

# The repo guard keeps events that stamped no $ai_git_repo (older agents that only carried the branch)
# while still rejecting a same-named branch in a different repo once the repo is stamped. coalesce
# collapses both NULL (property absent) and '' to the pass-through case. The group key is the AI session,
# falling back to the trace id; empty properties are treated as absent everywhere (nullIf on '').
_CANDIDATES = """
    candidates AS (
        SELECT
            timestamp AS ts,
            coalesce(properties.$ai_git_branch, '') AS branch,
            coalesce(nullIf(properties.$ai_session_id, ''), nullIf(properties.$ai_trace_id, ''), '') AS group_key,
            toFloat(properties.$ai_total_cost_usd) AS cost,
            toInt(properties.$ai_input_tokens) AS input_tokens,
            toInt(properties.$ai_output_tokens) AS output_tokens
        FROM events
        WHERE event = '$ai_generation'
            AND (coalesce(properties.$ai_git_repo, '') = '' OR properties.$ai_git_repo = {repo_full})
            AND timestamp >= {window_start}
            AND timestamp <= {window_end}
    )
"""

# Eligible groups only: a group counts toward H once it holds at least one H stamp (the HAVING). Per
# group, `stamps` is the timestamp-sorted array of (ts, branch) for its stamped events; `feature` is
# the first stamp whose branch is not the base ref M — the "first feature stamp" that anchors the
# prefix (before it) and the carry-forward (at/after it).
_GROUP_STAMPS = """
    group_stamps AS (
        SELECT
            group_key,
            stamps,
            tupleElement(feature, 1) AS feature_ts,
            tupleElement(feature, 2) AS feature_branch
        FROM (
            SELECT
                group_key,
                arraySort(x -> tupleElement(x, 1), groupArray(tuple(ts, branch))) AS stamps,
                arrayFirst(s -> tupleElement(s, 2) != {base}, stamps) AS feature
            FROM candidates
            WHERE branch != '' AND group_key != ''
            GROUP BY group_key
            HAVING countIf(branch = {branch}) > 0
        )
    )
"""

# One pass over candidates (ClickHouse re-evaluates a WITH subquery per reference, so a UNION of
# candidate scans would read events once per arm). Each candidate row counts at most once, when any
# rule matches: its own H stamp (rule 1), or — via its eligible group's stamps — the prefix (rule 2)
# or the carry-forward (rule 3). LEFT ANY JOIN because group_stamps is unique per key; ungrouped rows
# and rows in ineligible groups join to nothing (g.group_key = ''), so only rule 1 can pass for them.
# Every counted event flows from `candidates`, which already pins the window and repo guard.
_SPEND = """
    WITH
        __CANDIDATES__,
        __GROUP_STAMPS__
    SELECT
        sum(c.cost) AS cost_usd,
        sum(c.input_tokens) AS input_tokens,
        sum(c.output_tokens) AS output_tokens,
        count() AS generations
    FROM candidates AS c
    LEFT ANY JOIN group_stamps AS g ON c.group_key = g.group_key
    WHERE c.branch = {branch}
        OR (g.group_key != ''
            AND (
                ((c.branch = '' OR c.branch = {base}) AND c.ts < g.feature_ts AND g.feature_branch = {branch})
                OR (c.branch = '' AND c.ts >= g.feature_ts
                    AND tupleElement(arrayLast(s -> tupleElement(s, 1) <= c.ts, g.stamps), 2) = {branch})
            ))
""".replace("__CANDIDATES__", _CANDIDATES).replace("__GROUP_STAMPS__", _GROUP_STAMPS)


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
    head_branch, base_branch, created_at, merged_at, closed_at = header.results[0]
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
            # base_branch can be empty on a malformed snapshot; '' is a branch no event ever stamps, so
            # the base-neutral prefix rule simply falls back to "unstamped only", never mis-crediting.
            "base": ast.Constant(value=base_branch or ""),
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
