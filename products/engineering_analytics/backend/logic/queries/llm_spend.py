"""Coding-agent LLM token spend attributed to PRs, read from the ``events`` table.

Attribution is by the ``$ai_git_branch`` stamp and the AI session, never by head SHA, because the PR
snapshot keeps only the latest head (SPEC §6).
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

# Tokens are spent before a PR opens, so the window reaches back this far from created_at. A branch
# name is reused across PRs, so the window ends when the PR merges or closes, to limit how much of
# another PR's spend a recycled branch pulls in.
_LEAD_DAYS = 14

_HEADER = pr_header_query("head_branch, base_branch, created_at, merged_at, closed_at")

# argMax skips a NULL argument, so a reopened PR would keep an older snapshot's closure date. Taking
# the whole row as one tuple keeps the newest snapshot's NULLs.
# __PR_FILTER__ prunes raw snapshots and must test only immutable columns. __PR_WINDOW__ tests the
# newest snapshot, because an older open snapshot of a since-closed PR would pass a window check
# that its current row fails.
# A PR whose head is its own base (a fork PR from default to default) is dropped, because the direct
# stamp rule would credit it every default-branch generation in the window.
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

# The repo guard keeps events that stamped no $ai_git_repo and rejects a same-named branch in another
# repo once the repo is stamped. The compare is case-insensitive, because the stamped slug comes from
# a clone URL whose casing need not match GitHub's full_name.
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

# One row per (group, PR) where the group stamps the PR's head inside the PR's window. A group is one
# AI session. `feature` is the first stamp whose branch is not the PR's base ref.
# Stamps outside the window are cut before `feature` is picked, because a batch scan spans every
# requested PR and an out-of-window feature stamp would stop this PR's in-window base-ref events
# from counting.
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

# Each candidate yields up to two attribution keys of (branch, PR number).
# The first is its own stamp, valid for any PR with that head (number 0).
# The second is derived per PR its group was evaluated for. An event before the first feature stamp
# that is unstamped or stamped with the base ref counts for the feature branch, because an agent
# explores on the base branch before it creates the feature branch. An unstamped event at or after
# the first feature stamp counts for the most recently stamped branch.
# A base-ref stamp at or after the first feature stamp counts for no PR. An event with no session and
# no trace id matches only by its own stamp. The DISTINCT collapses the copies a candidate gets from
# being evaluated for several PRs, so each event counts once per PR.
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
