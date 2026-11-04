"""HogQL for the agent LLM token spend attributed to PRs.

Attribution is by git **branch**, not head SHA: a coding agent stamps ``$ai_git_branch`` on its
``$ai_generation`` events at capture time — before the PR exists — and the ``github_pull_requests``
snapshot keeps only the latest head, so a head-SHA join would drop every push but the last (SPEC §6).
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
and repo guard stay the OUTER filter on every counted event. Each PR evaluates a group over the stamps
inside its own window, so a batch read whose scan spans several PRs credits each PR exactly what its
single-PR read does.
"""

from collections.abc import Sequence
from datetime import datetime, timedelta

from django.utils import timezone

from posthog.hogql import ast

from products.engineering_analytics.backend.facade.contracts import (
    AuthorLLMSpendList,
    AuthorPRLLMSpend,
    LLMSpendCoverage,
    PRLLMSpend,
    PRState,
)
from products.engineering_analytics.backend.logic.queries._curated import CuratedGitHubSource
from products.engineering_analytics.backend.logic.queries._pr_header import pr_header_placeholders, pr_header_query

# Tokens are spent before a PR opens (the agent runs, then the PR is created), so the window reaches
# back this far from created_at. The tradeoff: head_branch is reused across PRs over time, so a
# recycled branch can pull in a neighbouring PR's spend — bounded by capping the window at the PR's
# own open→merge/close life (below).
_LEAD_DAYS = 14

_HEADER = pr_header_query("head_branch, base_branch, created_at, merged_at, closed_at")

# The newest snapshot row per PR, with the same tie-break as _pr_header (updated_at, then created_at).
# argMax skips a NULL argument, so a reopened PR would keep an older snapshot's closure date; taking the
# whole row as one tuple keeps the newest snapshot's NULLs. __PR_FILTER__ prunes raw snapshots and must
# only test immutable columns; __PR_WINDOW__ tests the newest snapshot, because an older open snapshot of
# a since-closed PR would otherwise pass a window check its current row fails.
# A PR is dropped when it has no branch to join on, no created_at to place the window (created_at comes
# from parseDateTimeBestEffort, which yields NULL on a malformed value), or a head that is its own base
# (a fork PR from default to default): the direct rule would sweep every default-branch generation in
# the window onto it, and no attribution beats wrong attribution. Open PRs are still accruing spend, so
# their window ends at now(); a closed/merged PR's ends at its close.
_PRS = """
    prs AS (
        SELECT
            number,
            head_branch,
            base_branch,
            opened_at - toIntervalDay({lead_days}) AS window_start,
            coalesce(ended_at, now()) AS window_end
        FROM (
            SELECT
                number,
                argMax(
                    tuple(pr.head_branch, pr.base_branch, pr.created_at, coalesce(pr.merged_at, pr.closed_at)),
                    version
                ) AS latest,
                tupleElement(latest, 1) AS head_branch,
                tupleElement(latest, 2) AS base_branch,
                tupleElement(latest, 3) AS opened_at,
                tupleElement(latest, 4) AS ended_at
            FROM (
                SELECT *, tuple(updated_at, created_at) AS version
                FROM __PR_SOURCE__
                WHERE lower(repo_owner) = {repo_owner} AND lower(repo_name) = {repo_name} AND __PR_FILTER__
            ) AS pr
            GROUP BY number
        )
        WHERE head_branch != '' AND head_branch != base_branch AND opened_at IS NOT NULL AND __PR_WINDOW__
    )
"""

# The repo guard keeps events that stamped no $ai_git_repo (older agents that only carried the branch)
# while still rejecting a same-named branch in a different repo once the repo is stamped. The compare
# is case-insensitive: GitHub repo names are, and the stamped slug comes from a clone URL whose casing
# need not match GitHub's canonical full_name. coalesce collapses both NULL (property absent) and ''
# to the pass-through case. The group key is the AI session, falling back to the trace id; empty
# properties are treated as absent everywhere (nullIf on '').
_CANDIDATES = """
    candidates AS (
        SELECT
            uuid,
            timestamp AS ts,
            coalesce(properties.$ai_git_branch, '') AS branch,
            lower(coalesce(properties.$ai_git_repo, '')) AS repo,
            coalesce(nullIf(properties.$ai_session_id, ''), nullIf(properties.$ai_trace_id, ''), '') AS group_key,
            toFloat(properties.$ai_total_cost_usd) AS cost,
            coalesce(toInt(properties.$ai_input_tokens), 0) AS input_tokens,
            coalesce(toInt(properties.$ai_output_tokens), 0) AS output_tokens,
            coalesce(toInt(properties.$ai_cache_read_input_tokens), 0) AS cache_read_input_tokens,
            coalesce(toInt(properties.$ai_cache_creation_input_tokens), 0) AS cache_creation_input_tokens
        FROM events
        WHERE event = '$ai_generation'
            AND (coalesce(properties.$ai_git_repo, '') = '' OR lower(properties.$ai_git_repo) = {repo_full})
            AND timestamp >= {scan_start}
            AND timestamp <= {scan_end}
    )
"""

# One row per (group, PR) where the group stamps the PR's head inside the PR's window. Per row, `stamps`
# is the timestamp-sorted array of (ts, branch) for the group's stamped events inside that window;
# `feature` is the first stamp whose branch is not the PR's base ref — the "first feature stamp" that
# anchors the prefix (before it) and the carry-forward (at/after it). Stamps outside the window are cut
# before `feature` is picked, because a batch scan spans every requested PR and an out-of-window feature
# stamp would otherwise turn this PR's in-window base-ref prefix neutral.
_GROUP_STAMPS = """
    group_stamps AS (
        SELECT
            group_key,
            number,
            base,
            stamps,
            tupleElement(feature, 1) AS feature_ts,
            tupleElement(feature, 2) AS feature_branch
        FROM (
            SELECT
                group_key,
                number,
                base,
                stamps,
                arrayFirst(s -> tupleElement(s, 2) != base, stamps) AS feature
            FROM (
                SELECT
                    g.group_key AS group_key,
                    p.number AS number,
                    p.head_branch AS head,
                    p.base_branch AS base,
                    arrayFilter(
                        s -> tupleElement(s, 1) >= p.window_start AND tupleElement(s, 1) <= p.window_end, g.stamps
                    ) AS stamps
                FROM (
                    SELECT group_key, stamps, arrayJoin(branches) AS stamped_branch
                    FROM (
                        SELECT
                            group_key,
                            arraySort(x -> tupleElement(x, 1), groupArray(tuple(ts, branch))) AS stamps,
                            groupUniqArray(branch) AS branches
                        FROM candidates
                        WHERE branch != '' AND group_key != ''
                        GROUP BY group_key
                    )
                ) AS g
                INNER JOIN prs AS p ON g.stamped_branch = p.head_branch
            )
            WHERE has(arrayMap(s -> tupleElement(s, 2), stamps), head)
        )
    )
"""

# Each candidate yields up to two attribution keys of (branch, PR number): its own stamp, valid for any
# PR with that head (rule 1, number 0), and, per PR its group was evaluated for, the branch the prefix
# (rule 2) or the carry-forward (rule 3) credits for that PR. The two keys never name the same PR for one
# event: the derived key is empty whenever the event is stamped with a non-base branch. Ungrouped
# candidates join to no group_stamps row (g.group_key = ''), so only their own stamp can match. The
# DISTINCT collapses the copies a candidate gets from being evaluated for several PRs, so each event
# counts once per PR. Every counted event flows from `candidates`, which already pins the scan window
# and repo guard; the PR's own window is checked here.
_MATCHED = """
    matched AS (
        SELECT DISTINCT
            p.number AS number,
            a.uuid AS uuid,
            a.cost AS cost,
            a.input_tokens AS input_tokens,
            a.output_tokens AS output_tokens,
            a.cache_read_input_tokens AS cache_read_input_tokens,
            a.cache_creation_input_tokens AS cache_creation_input_tokens
        FROM (
            SELECT
                c.uuid AS uuid,
                c.ts AS ts,
                c.cost AS cost,
                c.input_tokens AS input_tokens,
                c.output_tokens AS output_tokens,
                c.cache_read_input_tokens AS cache_read_input_tokens,
                c.cache_creation_input_tokens AS cache_creation_input_tokens,
                arrayJoin([
                    tuple(c.branch, 0),
                    tuple(
                        multiIf(
                            g.group_key = '', '',
                            (c.branch = '' OR c.branch = g.base) AND c.ts < g.feature_ts, g.feature_branch,
                            c.branch = '' AND c.ts >= g.feature_ts,
                                tupleElement(arrayLast(s -> tupleElement(s, 1) <= c.ts, g.stamps), 2),
                            ''
                        ),
                        g.number
                    )
                ]) AS attribution
            FROM candidates AS c
            LEFT JOIN group_stamps AS g ON c.group_key = g.group_key
        ) AS a
        INNER JOIN prs AS p ON tupleElement(a.attribution, 1) = p.head_branch
        WHERE (tupleElement(a.attribution, 2) = 0 OR tupleElement(a.attribution, 2) = p.number)
            AND a.ts >= p.window_start
            AND a.ts <= p.window_end
    )
"""

_WITH = "WITH " + ",".join([_PRS, _CANDIDATES, _GROUP_STAMPS, _MATCHED])

_SPEND_BY_PR = (
    _WITH
    + """
    SELECT
        m.number,
        sum(m.cost),
        sum(m.input_tokens),
        sum(m.output_tokens),
        sum(m.cache_read_input_tokens),
        sum(m.cache_creation_input_tokens),
        max(m.input_tokens + m.cache_read_input_tokens + m.cache_creation_input_tokens),
        count()
    FROM matched AS m
    GROUP BY m.number
    LIMIT {result_limit}
"""
)

_COVERAGE = (
    _WITH
    + """
    SELECT
        sum(c.cost),
        sumIf(c.cost, c.uuid IN (SELECT uuid FROM matched)),
        count(),
        countIf(c.uuid IN (SELECT uuid FROM matched))
    FROM candidates AS c
    WHERE c.repo = {repo_full}
"""
)

_AUTHOR_PRS = """
    SELECT number, title, state, head_branch, opened_at, ended_at
    FROM (
        SELECT
            number,
            argMax(
                tuple(pr.title, pr.state, pr.head_branch, pr.created_at, coalesce(pr.merged_at, pr.closed_at)),
                version
            ) AS latest,
            tupleElement(latest, 1) AS title,
            tupleElement(latest, 2) AS state,
            tupleElement(latest, 3) AS head_branch,
            tupleElement(latest, 4) AS opened_at,
            tupleElement(latest, 5) AS ended_at
        FROM (
            SELECT *, tuple(updated_at, created_at) AS version
            FROM __PR_SOURCE__
            WHERE lower(repo_owner) = {repo_owner} AND lower(repo_name) = {repo_name} AND author_handle = {author}
        ) AS pr
        GROUP BY number
    )
    WHERE opened_at IS NOT NULL AND opened_at <= {date_to} AND coalesce(ended_at, now()) >= {date_from}
    ORDER BY opened_at DESC, number DESC
    LIMIT {limit}
"""


def _attribution_placeholders(
    *, repo_owner: str, repo_name: str, scan_start: datetime, scan_end: datetime
) -> dict[str, ast.Expr]:
    return {
        "repo_owner": ast.Constant(value=repo_owner.lower()),
        "repo_name": ast.Constant(value=repo_name.lower()),
        "repo_full": ast.Constant(value=f"{repo_owner}/{repo_name}".lower()),
        "lead_days": ast.Constant(value=_LEAD_DAYS),
        "scan_start": ast.Constant(value=scan_start),
        "scan_end": ast.Constant(value=scan_end),
    }


def query_llm_spend_by_pr(
    *,
    curated: CuratedGitHubSource,
    repo_owner: str,
    repo_name: str,
    pr_numbers: Sequence[int],
    scan_start: datetime,
    scan_end: datetime,
) -> dict[int, PRLLMSpend]:
    if not pr_numbers:
        return {}
    placeholders = _attribution_placeholders(
        repo_owner=repo_owner, repo_name=repo_name, scan_start=scan_start, scan_end=scan_end
    )
    placeholders["pr_numbers"] = ast.Tuple(exprs=[ast.Constant(value=number) for number in pr_numbers])
    placeholders["result_limit"] = ast.Constant(value=len(pr_numbers))
    response = curated.run(
        _SPEND_BY_PR.replace("__PR_SOURCE__", curated.pr_source())
        .replace("__PR_FILTER__", "number IN {pr_numbers}")
        .replace("__PR_WINDOW__", "true"),
        query_type="engineering_analytics.pr_llm_spend",
        placeholders=placeholders,
    )
    spend: dict[int, PRLLMSpend] = {}
    for number, cost_usd, input_tokens, output_tokens, cache_read, cache_creation, peak, generations in (
        response.results or []
    ):
        if not generations:
            continue
        spend[int(number)] = PRLLMSpend(
            cost_usd=float(cost_usd or 0.0),
            input_tokens=int(input_tokens or 0),
            output_tokens=int(output_tokens or 0),
            generations=int(generations),
            cache_read_input_tokens=int(cache_read or 0),
            cache_creation_input_tokens=int(cache_creation or 0),
            peak_context_tokens=int(peak or 0),
        )
    return spend


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
    if not head_branch or created_at is None or head_branch == base_branch:
        return None
    # None when nothing matched, so the endpoint returns llm_spend=null and the UI hides the row.
    return query_llm_spend_by_pr(
        curated=curated,
        repo_owner=repo_owner,
        repo_name=repo_name,
        pr_numbers=[pr_number],
        scan_start=created_at - timedelta(days=_LEAD_DAYS),
        scan_end=merged_at or closed_at or timezone.now(),
    ).get(pr_number)


def query_author_llm_spend(
    *,
    curated: CuratedGitHubSource,
    author: str,
    repo_owner: str,
    repo_name: str,
    date_from: datetime,
    date_to: datetime,
    limit: int,
) -> AuthorLLMSpendList:
    response = curated.run(
        _AUTHOR_PRS.replace("__PR_SOURCE__", curated.pr_source()),
        query_type="engineering_analytics.author_llm_spend.prs",
        placeholders={
            "repo_owner": ast.Constant(value=repo_owner.lower()),
            "repo_name": ast.Constant(value=repo_name.lower()),
            "author": ast.Constant(value=author),
            "date_from": ast.Constant(value=date_from),
            "date_to": ast.Constant(value=date_to),
            "limit": ast.Constant(value=limit + 1),
        },
    )
    rows = list(response.results or [])
    truncated = len(rows) > limit
    rows = rows[:limit]
    if not rows:
        return AuthorLLMSpendList(items=[], truncated=False, limit=limit)

    now = timezone.now()
    spend = query_llm_spend_by_pr(
        curated=curated,
        repo_owner=repo_owner,
        repo_name=repo_name,
        pr_numbers=[row[0] for row in rows],
        scan_start=min(row[4] for row in rows) - timedelta(days=_LEAD_DAYS),
        scan_end=max(row[5] or now for row in rows),
    )
    return AuthorLLMSpendList(
        items=[
            AuthorPRLLMSpend(
                number=int(number),
                title=title or "",
                state=PRState(state),
                head_branch=head_branch or "",
                created_at=created_at,
                llm_spend=spend.get(int(number)),
            )
            for number, title, state, head_branch, created_at, _ended_at in rows
        ],
        truncated=truncated,
        limit=limit,
    )


def query_llm_spend_coverage(
    *,
    curated: CuratedGitHubSource,
    repo_owner: str,
    repo_name: str,
    date_from: datetime,
    date_to: datetime,
) -> LLMSpendCoverage:
    placeholders = _attribution_placeholders(
        repo_owner=repo_owner, repo_name=repo_name, scan_start=date_from, scan_end=date_to
    )
    placeholders["date_from"] = ast.Constant(value=date_from)
    placeholders["date_to"] = ast.Constant(value=date_to)
    response = curated.run(
        _COVERAGE.replace("__PR_SOURCE__", curated.pr_source())
        .replace("__PR_FILTER__", "created_at - toIntervalDay({lead_days}) <= {date_to}")
        .replace(
            "__PR_WINDOW__",
            "opened_at - toIntervalDay({lead_days}) <= {date_to} AND coalesce(ended_at, now()) >= {date_from}",
        ),
        query_type="engineering_analytics.llm_spend_coverage",
        placeholders=placeholders,
    )
    cost_usd, attributed_cost_usd, generations, attributed_generations = (response.results or [[0, 0, 0, 0]])[0]
    return LLMSpendCoverage(
        cost_usd=float(cost_usd or 0.0),
        attributed_cost_usd=float(attributed_cost_usd or 0.0),
        generations=int(generations or 0),
        attributed_generations=int(attributed_generations or 0),
    )
