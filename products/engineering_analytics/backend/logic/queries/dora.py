"""Curated query: DORA-style deploy metrics over the GitHub deployments pair.

Four quadrants, honestly named (SPEC §4):

- Deployment frequency: deployments whose first ``success`` status landed in the
  window, within the environment scope. Computed directly.
- Lead time: ``merge_to_deploy_seconds`` — a merged PR's wait until the first
  successful deployment that *contains* its merge. Containment is resolved through
  the deploy's head commit: the deploy's SHA is some merged PR's ``merge_commit_sha``,
  and every merge at or before that head merge is on board. Success time alone
  cannot decide this — deploys ship pre-built images, so a deploy routinely
  succeeds *after* a merge it does not contain. The field name says merge-to-deploy,
  not the full commit-to-deploy DORA definition (pre-merge time is measured elsewhere).
- Change failure: ``failed_deployment_share`` — deployments with a failure/error
  status over deployments that reached any outcome. A proxy: no incident link, so
  a deploy that succeeded but broke production is invisible.
- Restore: ``median_failed_deploy_to_next_success_seconds`` — first failure status
  to the next successful deployment in the same environment. A proxy: recovery by
  anything other than a deploy is invisible, and unrecovered failures are excluded.

The PR-scoped lead-time reads follow the locked cycle-time recipe (bots and drafts
excluded) and accept the ``team_members`` join for a GitHub-team filter — a team
surface, aggregates only (SPEC §6). Deploy counts are repo events and ignore the
team filter by design.
"""

from datetime import datetime, timedelta
from typing import Any

from posthog.schema import HogQLQueryResponse

from posthog.hogql import ast

from posthog.dataclasses import frozen

from products.engineering_analytics.backend.facade.contracts import (
    DeploymentFrequencyBucket,
    DoraOverview,
    MergeToDeployBucket,
)
from products.engineering_analytics.backend.logic.queries._buckets import (
    Granularity,
    bucket_expr,
    normalize_bucket,
    pick_granularity,
    window_buckets,
)
from products.engineering_analytics.backend.logic.queries._curated import CuratedGitHubSource, opt_float
from products.engineering_analytics.backend.logic.queries._workflow_filters import window_pair_predicates

# PRs merged this long before the scan window are outside lead-time attribution: the PR snapshot
# holds every PR ever, so the deployed-PR join needs a floor. On a continuous-deploy repo a merge
# waits minutes-to-hours for its deploy, so the bound is generous; a merge deployed more than this
# much later is dropped rather than scanning the whole snapshot.
_MERGE_SCAN_LOOKBACK = timedelta(days=30)

# Slack below the scan window so a deployment created before the window still counts when its
# outcome lands inside it. A week covers even a badly stalled rollout; the deploy tables are
# per-repo and small enough that the wider floor costs nothing measurable.
_DEPLOY_SCAN_SLACK = timedelta(days=7)

_ENVIRONMENTS_LIMIT = 100
_TEAMS_LIMIT = 500

# One row per deployment with its outcome timestamps: statuses are append-only transitions, so the
# first success / first failure are the outcome edges every read keys on. INNER JOIN drops
# deployments with no status rows — they never reached an outcome. __ENV_PREDICATE__ is one of the
# trusted variants below (never user input; the exact-match variant reads a placeholder).
# Assumes one deployment id per attempt (GitHub's normal shape): a deployment carrying both a
# failure and a later success status on the same id would count toward both outcomes and could
# pair with itself in the restore self-join.
_DEPLOYS_CTE = """
    deploys AS (
        SELECT
            d.id AS id,
            any(d.sha) AS sha,
            any(d.environment) AS environment,
            minIf(s.created_at, s.state = 'success') AS first_success_at,
            minIf(s.created_at, s.state IN ('failure', 'error')) AS first_failure_at
        FROM __DEPLOYMENTS_SOURCE__ AS d
        INNER JOIN __STATUSES_SOURCE__ AS s ON s.deployment_id = d.id
        WHERE d.created_at >= {deploy_scan_floor} AND __ENV_PREDICATE__
        GROUP BY d.id
    )
"""

# Outcome counts, the restore proxy, and the data-freshness edge in ONE round trip: every half
# aggregates to a single row, so the CROSS JOINs just glue the rows side by side and the deploys
# CTE is scanned once instead of twice.
#
# The restore half measures recovery per failed deployment: the next successful deployment in the
# SAME environment. The self-join fans out and the min collapses it back to one row per failure;
# deploy tables are small (per-repo, windowed) so the quadratic pairing stays cheap.
# __DATE_TO_RECOVERY__ bounds the recovery to the requested horizon, so a historical report's
# "no recovery" doesn't flip to recovered once a later, out-of-range deployment succeeds.
_OUTCOMES_SELECT = """
    SELECT
        outcomes.deployment_count,
        outcomes.deployment_count_prev,
        outcomes.failed_count,
        outcomes.failed_count_prev,
        outcomes.outcome_count,
        outcomes.outcome_count_prev,
        restore.restore_median_cur,
        restore.restore_median_prev,
        freshness.latest_status_at
    FROM (
        SELECT
            countIf(first_success_at IS NOT NULL AND __CUR_SUCCESS__) AS deployment_count,
            countIf(first_success_at IS NOT NULL AND __PREV_SUCCESS__) AS deployment_count_prev,
            countIf(first_failure_at IS NOT NULL AND __CUR_FAILURE__) AS failed_count,
            countIf(first_failure_at IS NOT NULL AND __PREV_FAILURE__) AS failed_count_prev,
            countIf((first_success_at IS NOT NULL AND __CUR_SUCCESS__)
                OR (first_failure_at IS NOT NULL AND __CUR_FAILURE__)) AS outcome_count,
            countIf((first_success_at IS NOT NULL AND __PREV_SUCCESS__)
                OR (first_failure_at IS NOT NULL AND __PREV_FAILURE__)) AS outcome_count_prev
        FROM deploys
    ) AS outcomes
    CROSS JOIN (
        SELECT
            quantileIf(0.5)(recovery_seconds, __CUR_FAILURE__) AS restore_median_cur,
            quantileIf(0.5)(recovery_seconds, __PREV_FAILURE__) AS restore_median_prev
        FROM (
            SELECT
                f.first_failure_at AS first_failure_at,
                dateDiff('second', f.first_failure_at, min(r.first_success_at)) AS recovery_seconds
            FROM deploys AS f
            INNER JOIN deploys AS r ON r.environment = f.environment
            WHERE f.first_failure_at IS NOT NULL
                AND r.first_success_at IS NOT NULL
                AND r.first_success_at >= f.first_failure_at
                __DATE_TO_RECOVERY__
            GROUP BY f.id, f.first_failure_at
        )
    ) AS restore
    CROSS JOIN (
        SELECT max(created_at) AS latest_status_at FROM __STATUSES_SOURCE__ AS ls
    ) AS freshness
"""

_FREQUENCY_SERIES_SELECT = """
    SELECT __BUCKET_FN__ AS bucket_start, count() AS deployment_count
    FROM deploys
    WHERE first_success_at IS NOT NULL AND first_success_at >= {date_from} __DATE_TO_SUCCESS__
    GROUP BY bucket_start
    LIMIT 40000
"""

# Each successful deployment's head merge time: the deploy's SHA is the merge commit of some
# merged PR, and that PR's merged_at says which merges the deploy contains. The sanctioned
# merge_commit_sha exception (SPEC §6): gated on merged_at (an open PR carries a throwaway
# test-merge SHA) and collapsed to one row per deployment (min breaks a shared-SHA tie).
# Deploys whose SHA is no PR's merge commit (direct pushes) resolve no head and attribute nothing.
# Bot merges stay in as heads on purpose: a bot's merge commit still names what a deploy contains.
_DEPLOY_HEADS_CTE = """
    deploy_heads AS (
        SELECT
            d.id AS id,
            any(d.first_success_at) AS first_success_at,
            min(hp.merged_at) AS head_merged_at
        FROM deploys AS d
        INNER JOIN __PR_SOURCE__ AS hp ON hp.merge_commit_sha = d.sha
        WHERE d.first_success_at IS NOT NULL
            AND d.sha != ''
            AND hp.merged_at IS NOT NULL
            AND hp.merged_at >= {merge_scan_floor}
        GROUP BY d.id
    )
"""

# Each merged PR's first successful deployment that CONTAINS it: the deploy's head merge is at or
# after the PR's merge. Ground-truthed against deploys whose SHA is exactly a PR's merge commit:
# this rule agrees on 99.7% of them with a 0-minute median error, where pairing on the deploy's
# success time instead picked an in-flight deploy built before the merge for roughly half.
# CROSS JOIN + the WHERE range condition is the attribution: HogQL joins take equality keys only,
# and the windowed populations are small enough that the pairing stays cheap. The locked
# cycle-time recipe applies (bots/drafts excluded).
_DEPLOYED_PRS_CTE = """
    deployed_prs AS (
        SELECT
            pr.number AS number,
            pr.merged_at AS merged_at,
            min(h.first_success_at) AS deployed_at
        FROM __PR_SOURCE__ AS pr
        CROSS JOIN deploy_heads AS h
        WHERE pr.merged_at IS NOT NULL
            AND pr.merged_at >= {merge_scan_floor}
            AND NOT pr.is_bot
            AND NOT pr.is_draft
            __TEAM_FILTER__
            AND h.head_merged_at >= pr.merged_at
        GROUP BY pr.number, pr.merged_at
    )
"""

_LEAD_TIME_INNER = "SELECT deployed_at, dateDiff('second', merged_at, deployed_at) AS lead_seconds FROM deployed_prs"

# The two one-row CROSS JOIN halves put attribution coverage on the same round trip: how many
# PRs merged in the window at all (same bot/draft/team recipe), and how many of those an
# in-scope deployment attributed — the honest denominator behind unattributed_merged_pr_share.
_LEAD_TIME_HEADLINE_SELECT = f"""
    SELECT
        lead.deployed_cur,
        lead.deployed_prev,
        lead.median_cur,
        lead.median_prev,
        attributed.attributed_cur,
        merged.merged_cur
    FROM (
        SELECT
            countIf(__CUR_DEPLOYED__) AS deployed_cur,
            countIf(__PREV_DEPLOYED__) AS deployed_prev,
            quantileIf(0.5)(lead_seconds, __CUR_DEPLOYED__) AS median_cur,
            quantileIf(0.5)(lead_seconds, __PREV_DEPLOYED__) AS median_prev
        FROM ({_LEAD_TIME_INNER})
    ) AS lead
    CROSS JOIN (
        SELECT countIf(__CUR_MERGED__) AS attributed_cur FROM deployed_prs
    ) AS attributed
    CROSS JOIN (
        SELECT countIf(__CUR_MERGED__) AS merged_cur
        FROM __PR_SOURCE__ AS pr
        WHERE pr.merged_at IS NOT NULL
            AND pr.merged_at >= {{merge_scan_floor}}
            AND NOT pr.is_bot
            AND NOT pr.is_draft
            __TEAM_FILTER__
    ) AS merged
"""

_LEAD_TIME_SERIES_SELECT = f"""
    SELECT
        __BUCKET_FN__ AS bucket_start,
        count() AS deployed_pr_count,
        min(lead_seconds) AS min_seconds,
        quantile(0.25)(lead_seconds) AS p25_seconds,
        quantile(0.5)(lead_seconds) AS p50_seconds,
        avg(lead_seconds) AS mean_seconds,
        quantile(0.75)(lead_seconds) AS p75_seconds,
        max(lead_seconds) AS max_seconds
    FROM ({_LEAD_TIME_INNER})
    WHERE deployed_at >= {{date_from}} __DATE_TO_DEPLOYED__
    GROUP BY bucket_start
    LIMIT 40000
"""

# Transient environments (ephemeral per-PR previews on this repo) are excluded from the picker
# options and the default scope: a busy repo deploys previews hundreds of times a week, which
# would swamp every deploy count. An exact ``environment`` filter can still reach one by name.
_ENVIRONMENTS_SELECT = f"""
    SELECT environment, max(is_production_environment) AS is_production, count() AS n
    FROM __DEPLOYMENTS_SOURCE__ AS d
    WHERE d.created_at >= {{prev_from}} AND NOT d.is_transient_environment __DATE_TO_CREATED__
    GROUP BY environment
    ORDER BY n DESC, environment ASC
    LIMIT {_ENVIRONMENTS_LIMIT}
"""

_TEAMS_SELECT = f"""
    SELECT DISTINCT team_slug
    FROM __MEMBERS_SOURCE__ AS m
    WHERE team_slug != ''
    ORDER BY team_slug ASC
    LIMIT {_TEAMS_LIMIT}
"""

_TEAM_FILTER = (
    "AND pr.author_handle IN (SELECT member_handle FROM __MEMBERS_SOURCE__ AS m WHERE m.team_slug = {github_team})"
)


def _date_to_clause(date_to: datetime | None, column: str) -> str:
    """The optional window-end clause on ``column``; empty when the window is open-ended."""
    return f"AND {column} <= {{date_to}}" if date_to is not None else ""


@frozen
class _EnvironmentScope:
    # 'production', 'persistent', or the exact environment the caller passed (see DoraOverview).
    scope: str
    # The trusted SQL predicate variant for the deploys CTE.
    predicate: str


@frozen
class _DoraScan:
    """One request's bound scan state — the curated handle, the environment-scoped deploys CTE,
    the shared placeholder registry, and the window — composed by every deploy sub-query."""

    curated: CuratedGitHubSource
    deploys_cte: str
    statuses_source: str
    placeholders: dict[str, ast.Expr]
    date_from: datetime
    date_to: datetime | None
    granularity: Granularity

    def run(self, sql: str, *, query_type: str) -> HogQLQueryResponse:
        return self.curated.run(sql, query_type=query_type, placeholders=self.placeholders)

    def date_to_filter(self, column: str) -> str:
        return _date_to_clause(self.date_to, column)

    def window_buckets(self) -> list[datetime]:
        return window_buckets(self.date_from, self.date_to, self.granularity)


def _resolve_environment_scope(environment: str | None, environments: list[tuple[str, bool]]) -> _EnvironmentScope:
    """Pick the deploy population: the caller's exact environment when given; otherwise the
    deployments GitHub marks production; otherwise the single busiest persistent environment,
    so a repo that never sets the production flag still gets numbers instead of a false zero.
    Busiest-single, not every-persistent: a multi-region repo deploys each merge to several
    persistent environments (and to dev, package registries, ...), which would multiply every
    deploy count and hand lead time to whichever region deploys first. 'persistent' survives
    only when the window has no persistent environment at all. Transient environments never
    join a default scope: they are ephemeral per-PR previews, and on this repo they outnumber
    real deploys by an order of magnitude."""
    if environment:
        return _EnvironmentScope(scope=environment, predicate="d.environment = {environment}")
    if any(is_production for _, is_production in environments):
        return _EnvironmentScope(scope="production", predicate="d.is_production_environment")
    if environments:
        return _EnvironmentScope(scope=environments[0][0], predicate="d.environment = {environment}")
    return _EnvironmentScope(scope="persistent", predicate="NOT d.is_transient_environment")


def _empty_overview(
    *,
    deploy_data_available: bool,
    environment_scope: str,
    environments: list[str],
    has_membership_data: bool,
    github_teams: list[str],
    granularity: Granularity,
) -> DoraOverview:
    return DoraOverview(
        deploy_data_available=deploy_data_available,
        environment_scope=environment_scope,
        environments=environments,
        has_membership_data=has_membership_data,
        github_teams=github_teams,
        deployment_count=0,
        deployment_count_prev=0,
        deployments_per_day=None,
        deployments_per_day_prev=None,
        median_merge_to_deploy_seconds=None,
        median_merge_to_deploy_seconds_prev=None,
        deployed_pr_count=0,
        deployed_pr_count_prev=0,
        failed_deployment_count=0,
        failed_deployment_count_prev=0,
        failed_deployment_share=None,
        failed_deployment_share_prev=None,
        median_failed_deploy_to_next_success_seconds=None,
        median_failed_deploy_to_next_success_seconds_prev=None,
        merged_pr_count=0,
        unattributed_merged_pr_share=None,
        latest_deploy_status_at=None,
        deployment_frequency_series=[],
        merge_to_deploy_series=[],
        series_granularity=granularity,
    )


@frozen
class _DeployOutcomes:
    """Deploy outcome counts and the restore-proxy medians over the window pair, straight off
    the deploys rollup."""

    deployment_count: int
    deployment_count_prev: int
    failed_count: int
    failed_count_prev: int
    outcome_count: int
    outcome_count_prev: int
    # Median failed-deploy-to-next-success seconds (the restore proxy); None when nothing recovered.
    restore_median_seconds: float | None
    restore_median_seconds_prev: float | None
    # The newest status row synced, any environment — how fresh the deploy data is.
    latest_status_at: datetime | None

    @property
    def failed_share(self) -> float | None:
        return self.failed_count / self.outcome_count if self.outcome_count else None

    @property
    def failed_share_prev(self) -> float | None:
        return self.failed_count_prev / self.outcome_count_prev if self.outcome_count_prev else None


def _query_deploy_outcomes(scan: _DoraScan) -> _DeployOutcomes:
    success = window_pair_predicates("first_success_at", date_to=scan.date_to)
    failure = window_pair_predicates("first_failure_at", date_to=scan.date_to)
    sql = f"WITH {scan.deploys_cte} " + (
        _OUTCOMES_SELECT.replace("__CUR_SUCCESS__", success.current)
        .replace("__PREV_SUCCESS__", success.previous)
        .replace("__CUR_FAILURE__", failure.current)
        .replace("__PREV_FAILURE__", failure.previous)
        .replace("__DATE_TO_RECOVERY__", scan.date_to_filter("r.first_success_at"))
        .replace("__STATUSES_SOURCE__", scan.statuses_source)
    )
    response = scan.run(sql, query_type="engineering_analytics.dora_deploys")
    deploy_count, deploy_count_prev, failed, failed_prev, outcome, outcome_prev, restore_cur, restore_prev, latest = (
        response.results[0] if response.results else (0, 0, 0, 0, 0, 0, None, None, None)
    )
    return _DeployOutcomes(
        deployment_count=int(deploy_count or 0),
        deployment_count_prev=int(deploy_count_prev or 0),
        failed_count=int(failed or 0),
        failed_count_prev=int(failed_prev or 0),
        outcome_count=int(outcome or 0),
        outcome_count_prev=int(outcome_prev or 0),
        restore_median_seconds=opt_float(restore_cur),
        restore_median_seconds_prev=opt_float(restore_prev),
        latest_status_at=latest if isinstance(latest, datetime) else None,
    )


def _query_frequency_series(scan: _DoraScan) -> list[DeploymentFrequencyBucket]:
    """Successful deployments per bucket across the window, oldest first, zero-filled."""
    sql = f"WITH {scan.deploys_cte} " + (
        _FREQUENCY_SERIES_SELECT.replace("__BUCKET_FN__", bucket_expr(scan.granularity, "first_success_at")).replace(
            "__DATE_TO_SUCCESS__", scan.date_to_filter("first_success_at")
        )
    )
    response = scan.run(sql, query_type="engineering_analytics.dora_frequency")
    count_by_bucket = {
        normalize_bucket(bucket_start, scan.granularity): int(count or 0)
        for bucket_start, count in response.results or []
    }
    return [
        DeploymentFrequencyBucket(bucket_start=bucket, deployment_count=count_by_bucket.get(bucket, 0))
        for bucket in scan.window_buckets()
    ]


@frozen
class _LeadTime:
    """The PR-scoped merge-to-deploy figures: window-pair counts and medians, attribution
    coverage, plus the box-plot series."""

    deployed_count: int
    deployed_count_prev: int
    median_seconds: float | None
    median_seconds_prev: float | None
    # PRs merged in the window (the locked recipe), and how many of those a deploy attributed.
    merged_count: int
    attributed_count: int
    series: list[MergeToDeployBucket]

    @property
    def unattributed_share(self) -> float | None:
        return 1 - self.attributed_count / self.merged_count if self.merged_count else None


_EMPTY_LEAD_TIME = _LeadTime(
    deployed_count=0,
    deployed_count_prev=0,
    median_seconds=None,
    median_seconds_prev=None,
    merged_count=0,
    attributed_count=0,
    series=[],
)


def _query_lead_time(scan: _DoraScan, *, github_team: str | None, members_source: str | None) -> _LeadTime:
    # A team filter without membership data cannot be honored: empty lead-time figures, never
    # silently unfiltered ones.
    if github_team and members_source is None:
        return _EMPTY_LEAD_TIME
    team_filter = ""
    if github_team and members_source is not None:
        scan.placeholders["github_team"] = ast.Constant(value=github_team)
        team_filter = _TEAM_FILTER.replace("__MEMBERS_SOURCE__", members_source)
    pr_source = scan.curated.pr_source()
    attribution_ctes = f"{scan.deploys_cte}, {_DEPLOY_HEADS_CTE}, {_DEPLOYED_PRS_CTE}".replace(
        "__PR_SOURCE__", pr_source
    ).replace("__TEAM_FILTER__", team_filter)

    windows = window_pair_predicates("deployed_at", date_to=scan.date_to)
    merged_window = window_pair_predicates("merged_at", date_to=scan.date_to)
    headline_sql = f"WITH {attribution_ctes} " + (
        _LEAD_TIME_HEADLINE_SELECT.replace("__CUR_DEPLOYED__", windows.current)
        .replace("__PREV_DEPLOYED__", windows.previous)
        .replace("__CUR_MERGED__", merged_window.current)
        .replace("__PR_SOURCE__", pr_source)
        .replace("__TEAM_FILTER__", team_filter)
    )
    headline = scan.run(headline_sql, query_type="engineering_analytics.dora_lead_time")
    deployed_cur, deployed_prev, median_cur, median_prev, attributed_cur, merged_cur = (
        headline.results[0] if headline.results else (0, 0, None, None, 0, 0)
    )

    series_sql = f"WITH {attribution_ctes} " + (
        _LEAD_TIME_SERIES_SELECT.replace("__BUCKET_FN__", bucket_expr(scan.granularity, "deployed_at")).replace(
            "__DATE_TO_DEPLOYED__", scan.date_to_filter("deployed_at")
        )
    )
    rows = scan.run(series_sql, query_type="engineering_analytics.dora_lead_time_series")
    stats_by_bucket = {normalize_bucket(row[0], scan.granularity): row[1:] for row in (rows.results or [])}
    return _LeadTime(
        deployed_count=int(deployed_cur or 0),
        deployed_count_prev=int(deployed_prev or 0),
        median_seconds=opt_float(median_cur),
        median_seconds_prev=opt_float(median_prev),
        merged_count=int(merged_cur or 0),
        attributed_count=int(attributed_cur or 0),
        series=[_lead_time_bucket(bucket, stats_by_bucket.get(bucket)) for bucket in scan.window_buckets()],
    )


def query_dora_overview(
    *,
    curated: CuratedGitHubSource,
    date_from: datetime,
    date_to: datetime | None,
    environment: str | None = None,
    github_team: str | None = None,
) -> DoraOverview:
    granularity = pick_granularity(date_from, date_to)
    deploy_sources = curated.deploy_sources()
    members_source = curated.members_source()
    has_membership_data = members_source is not None
    github_teams = _query_github_teams(curated, members_source)

    if deploy_sources is None:
        return _empty_overview(
            deploy_data_available=False,
            environment_scope=environment or "persistent",
            environments=[],
            has_membership_data=has_membership_data,
            github_teams=github_teams,
            granularity=granularity,
        )

    end = date_to or datetime.now(tz=date_from.tzinfo)
    prev_from = date_from - (end - date_from)
    window_days = max((end - date_from).total_seconds() / 86400, 1 / 24)

    placeholders: dict[str, ast.Expr] = {
        "date_from": ast.Constant(value=date_from),
        "prev_from": ast.Constant(value=prev_from),
        "deploy_scan_floor": ast.Constant(value=prev_from - _DEPLOY_SCAN_SLACK),
        "merge_scan_floor": ast.Constant(value=prev_from - _MERGE_SCAN_LOOKBACK),
    }
    if date_to is not None:
        placeholders["date_to"] = ast.Constant(value=date_to)

    environments = _query_environments(
        curated,
        deploy_sources.deployments,
        placeholders=placeholders,
        date_to_filter=_date_to_clause(date_to, "d.created_at"),
    )
    env_scope = _resolve_environment_scope(environment, environments)
    # The busiest-environment fallback binds the same placeholder as an explicit filter: either
    # way the scope string IS the environment the predicate matches.
    if "{environment}" in env_scope.predicate:
        placeholders["environment"] = ast.Constant(value=env_scope.scope)

    scan = _DoraScan(
        curated=curated,
        deploys_cte=(
            _DEPLOYS_CTE.replace("__DEPLOYMENTS_SOURCE__", deploy_sources.deployments)
            .replace("__STATUSES_SOURCE__", deploy_sources.statuses)
            .replace("__ENV_PREDICATE__", env_scope.predicate)
        ),
        statuses_source=deploy_sources.statuses,
        placeholders=placeholders,
        date_from=date_from,
        date_to=date_to,
        granularity=granularity,
    )
    outcomes = _query_deploy_outcomes(scan)
    lead = _query_lead_time(scan, github_team=github_team, members_source=members_source)

    return DoraOverview(
        deploy_data_available=True,
        environment_scope=env_scope.scope,
        environments=[name for name, _ in environments],
        has_membership_data=has_membership_data,
        github_teams=github_teams,
        deployment_count=outcomes.deployment_count,
        deployment_count_prev=outcomes.deployment_count_prev,
        deployments_per_day=outcomes.deployment_count / window_days,
        deployments_per_day_prev=outcomes.deployment_count_prev / window_days,
        median_merge_to_deploy_seconds=lead.median_seconds,
        median_merge_to_deploy_seconds_prev=lead.median_seconds_prev,
        deployed_pr_count=lead.deployed_count,
        deployed_pr_count_prev=lead.deployed_count_prev,
        failed_deployment_count=outcomes.failed_count,
        failed_deployment_count_prev=outcomes.failed_count_prev,
        failed_deployment_share=outcomes.failed_share,
        failed_deployment_share_prev=outcomes.failed_share_prev,
        median_failed_deploy_to_next_success_seconds=outcomes.restore_median_seconds,
        median_failed_deploy_to_next_success_seconds_prev=outcomes.restore_median_seconds_prev,
        merged_pr_count=lead.merged_count,
        unattributed_merged_pr_share=lead.unattributed_share,
        latest_deploy_status_at=outcomes.latest_status_at,
        deployment_frequency_series=_query_frequency_series(scan),
        merge_to_deploy_series=lead.series,
        series_granularity=granularity,
    )


def _lead_time_bucket(bucket: datetime, stats: tuple[Any, Any, Any, Any, Any, Any, Any] | None) -> MergeToDeployBucket:
    if not stats:
        return MergeToDeployBucket(
            bucket_start=bucket,
            deployed_pr_count=0,
            min_seconds=None,
            p25_seconds=None,
            p50_seconds=None,
            mean_seconds=None,
            p75_seconds=None,
            max_seconds=None,
        )
    n, min_s, p25, p50, mean, p75, max_s = stats
    return MergeToDeployBucket(
        bucket_start=bucket,
        deployed_pr_count=int(n or 0),
        min_seconds=opt_float(min_s),
        p25_seconds=opt_float(p25),
        p50_seconds=opt_float(p50),
        mean_seconds=opt_float(mean),
        p75_seconds=opt_float(p75),
        max_seconds=opt_float(max_s),
    )


def _query_environments(
    curated: CuratedGitHubSource,
    deployments_source: str,
    *,
    placeholders: dict[str, ast.Expr],
    date_to_filter: str,
) -> list[tuple[str, bool]]:
    """``(environment, is_production)`` pairs deployed to in the scan window, most-deployed first."""
    sql = _ENVIRONMENTS_SELECT.replace("__DEPLOYMENTS_SOURCE__", deployments_source).replace(
        "__DATE_TO_CREATED__", date_to_filter
    )
    response = curated.run(sql, query_type="engineering_analytics.dora_environments", placeholders=placeholders)
    return [(str(name), bool(is_production)) for name, is_production, _ in (response.results or []) if name]


def _query_github_teams(curated: CuratedGitHubSource, members_source: str | None) -> list[str]:
    """Distinct GitHub team slugs from the membership snapshot — the team filter's options."""
    if members_source is None:
        return []
    response = curated.run(
        _TEAMS_SELECT.replace("__MEMBERS_SOURCE__", members_source),
        query_type="engineering_analytics.dora_github_teams",
    )
    return [str(slug) for (slug,) in (response.results or []) if slug]
