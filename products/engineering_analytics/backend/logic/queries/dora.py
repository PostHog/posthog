"""Curated query: DORA-style deploy metrics over the GitHub deployments pair.

Four quadrants, honestly named (SPEC §4):

- Deployment frequency: deployments whose first ``success`` status landed in the
  window, within the environment scope. Computed directly.
- Lead time: ``merge_to_deploy_seconds``, a merged PR's wait until the first
  successful deployment that *contains* its merge. Containment is resolved through
  the deploy's head commit: its SHA resolves to a merged PR through ``merge_commit_sha``
  or the workflow-run builder's ``commit_pr_number`` fallback. Every merge at or before
  that head merge is on board. Success time alone
  cannot decide this: deploys ship pre-built images, so a deploy routinely
  succeeds *after* a merge it does not contain. The field name says merge-to-deploy,
  not the full commit-to-deploy DORA definition (pre-merge time is measured elsewhere).
  ``open_to_deploy_seconds`` (open to first successful deploy over the same
  population) is the full-span headline the Health tile shows.
- Change failure: ``failed_deployment_share``, deployments with a failure/error
  status over deployments that reached any outcome. A proxy: no incident link, so
  a deploy that succeeded but broke production is invisible.
- Restore: ``median_failed_deploy_to_next_success_seconds``, first failure status
  to the next successful deployment in the same environment. A proxy: recovery by
  anything other than a deploy is invisible, and unrecovered failures are excluded.

The PR-scoped lead-time reads follow the locked cycle-time recipe (bots and drafts
excluded) and accept the ``team_members`` join for a GitHub-team filter, a team
surface with aggregates only (SPEC §6). Deploy counts are repo events and ignore the
team filter by design.
"""

from datetime import datetime, timedelta
from functools import cached_property
from typing import Any

from posthog.schema import HogQLQueryResponse

from posthog.hogql import ast

from posthog.dataclasses import frozen

from products.engineering_analytics.backend.facade.contracts import (
    DeliveryScopeKind,
    DeploymentFrequencyBucket,
    DoraOverview,
    LeadTimeBucket,
)
from products.engineering_analytics.backend.logic.delivery_scope import DeliveryScope
from products.engineering_analytics.backend.logic.queries._buckets import (
    Granularity,
    bucket_expr,
    normalize_bucket,
    pick_granularity,
    window_buckets,
)
from products.engineering_analytics.backend.logic.queries._curated import CuratedGitHubSource, DeploySources, opt_float
from products.engineering_analytics.backend.logic.queries._workflow_filters import (
    UNPAGED_SCAN_LIMIT,
    date_to_filter_clause,
    run_started_floor_constant,
    window_pair_predicates,
)

# PRs merged this long before the scan window are outside lead-time attribution: the PR snapshot
# holds every PR ever, so the deployed-PR join needs a floor. On a continuous-deploy repo a merge
# waits minutes-to-hours for its deploy, so the bound is generous; a merge deployed more than this
# much later is dropped rather than scanning the whole snapshot.
_MERGE_SCAN_LOOKBACK = timedelta(days=30)

# Slack below the scan window so a deployment created before the window still counts when its
# outcome lands inside it. A week covers even a badly stalled rollout; the deploy tables are
# per-repo and small enough that the wider floor costs nothing measurable.
_DEPLOY_SCAN_SLACK = timedelta(days=7)

_ENVIRONMENT_LOOKBACK = timedelta(days=30)

_ENVIRONMENTS_LIMIT = 100
_TEAMS_LIMIT = 500

# One row per deployment with its outcome timestamps: statuses are append-only transitions, so the
# first success / first failure are the outcome edges every read keys on. INNER JOIN drops
# deployments with no status rows, because they never reached an outcome. __ENV_PREDICATE__ is one of the
# trusted variants below (never user input; the exact-match variant reads a placeholder).
# Assumes one deployment id per attempt (GitHub's normal shape): a deployment carrying both a
# failure and a later success status on the same id would count toward both outcomes and could
# pair with itself in the restore self-join.
# minOrNullIf is required even when a source has non-null timestamps: minIf returns an epoch
# for a missing outcome, which would win every first-deployment attribution.
_DEPLOYS_CTE = """
    deploys AS (
        SELECT
            d.id AS id,
            any(d.sha) AS sha,
            any(d.environment) AS environment,
            any(d.created_at) AS created_at,
            minOrNullIf(s.created_at, s.state = 'success') AS first_success_at,
            minOrNullIf(s.created_at, s.state IN ('failure', 'error')) AS first_failure_at
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
# A deploy SHA with no merge_commit_sha match falls back to the workflow-run commit_pr_number on
# the same repo's default branch. The candidate PR must have no merge commit of its own, because
# one that names another commit means the (#N) suffix is wrong. It must merge into that branch,
# because a cherry-pick keeps a release-branch PR's subject. It must merge before the deployment
# was created, because GitHub fixes the deployed SHA at creation.
# Bot merges stay in as heads on purpose: a bot's merge commit still names what a deploy contains.
_DEPLOY_HEADS_CTE = """
    merge_heads AS (
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
    ),
    workflow_heads AS (
        SELECT
            d.id AS id,
            any(d.first_success_at) AS first_success_at,
            min(hp.merged_at) AS head_merged_at
        FROM deploys AS d
        INNER JOIN __RUNS_SOURCE__ AS r ON r.head_sha = d.sha
        INNER JOIN __PR_SOURCE__ AS hp ON hp.number = r.commit_pr_number
        WHERE d.first_success_at IS NOT NULL
            AND d.sha != ''
            AND d.id NOT IN (SELECT id FROM merge_heads)
            AND hp.merge_commit_sha = ''
            AND r.run_started_at >= {merge_scan_floor}
            AND NOT r.is_merge_queue
            AND hp.default_branch != ''
            AND r.head_branch = hp.default_branch
            AND hp.base_branch = r.head_branch
            AND r.repo_owner = hp.repo_owner AND r.repo_name = hp.repo_name
            AND hp.merged_at IS NOT NULL
            AND hp.merged_at >= {merge_scan_floor}
            AND hp.merged_at <= r.created_at
            AND hp.merged_at <= d.created_at
        GROUP BY d.id
        HAVING uniqExact(r.commit_pr_number) = 1
    ),
    deploy_heads AS (
        SELECT id, first_success_at, head_merged_at FROM merge_heads
        UNION ALL
        SELECT id, first_success_at, head_merged_at FROM workflow_heads
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
            pr.author_handle AS author_handle,
            pr.created_at AS created_at,
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
        GROUP BY pr.number, pr.author_handle, pr.created_at, pr.merged_at
    )
"""

# The three lead-time stages, one row per deployed PR. Every lead-time read selects from here, so the
# box-plot series and the delivery summary's rows measure the SAME population and stages, and
# open → merge and merge → deploy compose into open → deploy.
_LEAD_TIME_INNER = """
    SELECT
        number,
        author_handle,
        created_at,
        merged_at,
        deployed_at,
        dateDiff('second', merged_at, deployed_at) AS lead_seconds,
        dateDiff('second', created_at, merged_at) AS open_to_merge_seconds,
        dateDiff('second', created_at, deployed_at) AS open_to_deploy_seconds
    FROM deployed_prs
"""

# The two one-row CROSS JOIN halves put attribution coverage on the same round trip: how many
# PRs merged in the window at all (same bot/draft/team recipe), and how many an in-scope
# deployment attributed by the report horizon: the honest denominator behind unattributed_merged_pr_share.
_LEAD_TIME_HEADLINE_SELECT = f"""
    SELECT
        lead.deployed_cur,
        lead.deployed_prev,
        lead.median_cur,
        lead.median_prev,
        lead.otd_median_cur,
        lead.otd_median_prev,
        attributed.attributed_cur,
        merged.merged_cur
    FROM (
        SELECT
            countIf(__CUR_DEPLOYED__) AS deployed_cur,
            countIf(__PREV_DEPLOYED__) AS deployed_prev,
            quantileIf(0.5)(lead_seconds, __CUR_DEPLOYED__) AS median_cur,
            quantileIf(0.5)(lead_seconds, __PREV_DEPLOYED__) AS median_prev,
            quantileIf(0.5)(open_to_deploy_seconds, __CUR_DEPLOYED__) AS otd_median_cur,
            quantileIf(0.5)(open_to_deploy_seconds, __PREV_DEPLOYED__) AS otd_median_prev
        FROM ({_LEAD_TIME_INNER})
    ) AS lead
    CROSS JOIN (
        SELECT countIf(__CUR_ATTRIBUTED__) AS attributed_cur FROM deployed_prs
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


def _box_stat_columns(column: str, prefix: str) -> str:
    """The box-plot summary of ``column``, aliased under ``prefix``: the six-number summary
    plus p5/p95, the whisker pair the outlier-excluding view draws instead of min/max."""
    return (
        f"min({column}) AS {prefix}_min, quantile(0.05)({column}) AS {prefix}_p05, "
        f"quantile(0.25)({column}) AS {prefix}_p25, quantile(0.5)({column}) AS {prefix}_p50, "
        f"avg({column}) AS {prefix}_mean, quantile(0.75)({column}) AS {prefix}_p75, "
        f"quantile(0.95)({column}) AS {prefix}_p95, max({column}) AS {prefix}_max"
    )


# The three lead-time stages, in the order their six-stat columns appear in
# _LEAD_TIME_SERIES_SELECT. _lead_time_bucket's ``stage`` index walks this same list, so the
# SQL column order and the Python row-slice order can't drift independently.
_LEAD_TIME_STAGES = (("mtd", "lead_seconds"), ("otm", "open_to_merge_seconds"), ("otd", "open_to_deploy_seconds"))
_STAGE_STAT_WIDTH = 8  # min, p05, p25, p50, mean, p75, p95, max
_STAGE_MERGE_TO_DEPLOY, _STAGE_OPEN_TO_MERGE, _STAGE_OPEN_TO_DEPLOY = range(len(_LEAD_TIME_STAGES))

_LEAD_TIME_SERIES_SELECT = f"""
    SELECT
        __BUCKET_FN__ AS bucket_start,
        count() AS deployed_pr_count,
        {", ".join(_box_stat_columns(column, prefix) for prefix, column in _LEAD_TIME_STAGES)}
    FROM ({_LEAD_TIME_INNER})
    WHERE deployed_at >= {{date_from}} __DATE_TO_DEPLOYED__
    GROUP BY bucket_start
    LIMIT 40000
"""

# Transient environments (ephemeral per-PR previews on this repo) are excluded from the picker
# options and the default scope: a busy repo deploys previews hundreds of times a week, which
# would swamp every deploy count. An exact ``environment`` filter can still reach one by name.
_ENVIRONMENTS_SELECT = f"""
    SELECT environment, count() AS n
    FROM __DEPLOYMENTS_SOURCE__ AS d
    WHERE d.created_at >= {{environment_scan_floor}} AND NOT d.is_transient_environment __DATE_TO_CREATED__
    GROUP BY environment
    ORDER BY n DESC, environment ASC
    LIMIT {_ENVIRONMENTS_LIMIT}
"""

# Keep default production resolution separate from the capped picker query. Returning one aggregate
# row also avoids HogQL's implicit row limit when a repository has more than 100 production regions.
_PRODUCTION_ENVIRONMENTS_SELECT = """
    SELECT groupUniqArray(environment) AS environments
    FROM __DEPLOYMENTS_SOURCE__ AS d
    WHERE d.created_at >= {environment_scan_floor}
        AND NOT d.is_transient_environment
        AND (d.is_production_environment OR match(lower(d.environment), '^prod(uction)?([-_.].*)?$'))
        __DATE_TO_CREATED__
"""

_ENVIRONMENT_CHOICES_SELECT = """
    SELECT groupUniqArray(environment) AS environments
    FROM __DEPLOYMENTS_SOURCE__ AS d
    WHERE d.created_at >= {environment_scan_floor}
        AND d.environment IN {requested_environments}
        __DATE_TO_CREATED__
"""

_TEAMS_SELECT = f"""
    SELECT DISTINCT team_slug
    FROM __MEMBERS_SOURCE__ AS m
    WHERE team_slug != ''
    ORDER BY team_slug ASC
    LIMIT {_TEAMS_LIMIT}
"""


def _date_to_clause(date_to: datetime | None, column: str) -> str:
    """The optional window-end clause on ``column``; empty when the window is open-ended."""
    return f"AND {column} <= {{date_to}}" if date_to is not None else ""


def _environment_scan_floor(date_from: datetime, date_to: datetime) -> datetime:
    prev_from = date_from - (date_to - date_from)
    return min(prev_from - _DEPLOY_SCAN_SLACK, date_to - _ENVIRONMENT_LOOKBACK)


def _sorted_names(rows: list[Any]) -> list[str]:
    names = rows[0][0] if rows else []
    return sorted(str(name) for name in names or [] if name)


@frozen(slots=False)
class _EnvironmentCatalog:
    """The environment names a source deployed to around one window. Each list is its own ClickHouse
    read and runs on first use, so a read that only needs the production default skips the rest."""

    curated: CuratedGitHubSource
    deployments_source: str
    date_from: datetime
    date_to: datetime | None

    def _rows(self, select: str, *, query_type: str, placeholders: dict[str, ast.Expr] | None = None) -> list[Any]:
        end = self.date_to or datetime.now(tz=self.date_from.tzinfo)
        bound: dict[str, ast.Expr] = {
            "environment_scan_floor": ast.Constant(value=_environment_scan_floor(self.date_from, end)),
            **(placeholders or {}),
        }
        sql = select.replace("__DEPLOYMENTS_SOURCE__", self.deployments_source).replace(
            "__DATE_TO_CREATED__", date_to_filter_clause(self.date_to, bound, column="d.created_at")
        )
        return self.curated.run(sql, query_type=query_type, placeholders=bound).results or []

    @cached_property
    def options(self) -> list[str]:
        """The picker's options: persistent environments deployed to in the scan window, most-deployed first."""
        rows = self._rows(_ENVIRONMENTS_SELECT, query_type="engineering_analytics.dora_environments")
        return [str(name) for name, _ in rows if name]

    @cached_property
    def production(self) -> list[str]:
        return _sorted_names(
            self._rows(_PRODUCTION_ENVIRONMENTS_SELECT, query_type="engineering_analytics.dora_production_environments")
        )

    def existing(self, names: list[str]) -> list[str]:
        """The given names the source deployed to in the scan window, transient environments included."""
        return _sorted_names(
            self._rows(
                _ENVIRONMENT_CHOICES_SELECT,
                query_type="engineering_analytics.dora_environment_choices",
                placeholders={"requested_environments": ast.Tuple(exprs=[ast.Constant(value=n) for n in names])},
            )
        )


@frozen
class _EnvironmentScope:
    # 'persistent', or the exact environment name(s) the scope resolved to (see DoraOverview).
    scope: str
    # The trusted SQL predicate variant for the deploys CTE.
    predicate: str
    # The exact environment names the predicate matches, bound as the {environments} placeholder;
    # None for the predicate variants that match by flag rather than by name.
    values: list[str] | None

    @classmethod
    def named(cls, names: list[str]) -> "_EnvironmentScope":
        return cls(scope=", ".join(names), predicate="d.environment IN {environments}", values=names)


@frozen
class _DoraScan:
    """One request's bound deploy scan: the curated handle, the resolved environment scope and its
    deploys CTE, the placeholders every deploy sub-query shares, and the window."""

    curated: CuratedGitHubSource
    environment_catalog: _EnvironmentCatalog
    environment_scope: _EnvironmentScope
    deploys_cte: str
    statuses_source: str
    placeholders: dict[str, ast.Expr]
    date_from: datetime
    date_to: datetime | None

    def run(self, sql: str, *, query_type: str, placeholders: dict[str, ast.Expr] | None = None) -> HogQLQueryResponse:
        """Run ``sql`` with the shared placeholders plus ``placeholders`` that only this read binds."""
        return self.curated.run(sql, query_type=query_type, placeholders={**self.placeholders, **(placeholders or {})})

    def date_to_filter(self, column: str) -> str:
        return _date_to_clause(self.date_to, column)

    def attribution_ctes(self, *, pr_filter: str = "") -> str:
        """The deploys, deploy heads and deployed PRs CTEs. ``pr_filter`` is a trusted ``AND`` clause
        over the pull request source aliased ``pr``."""
        return (
            f"{self.deploys_cte}, {_DEPLOY_HEADS_CTE}, {_DEPLOYED_PRS_CTE}".replace(
                "__PR_SOURCE__", self.curated.pr_source()
            )
            .replace("__RUNS_SOURCE__", self.curated.run_source(started_floor=True))
            .replace("__TEAM_FILTER__", pr_filter)
        )


def _resolve_environment_scope(
    requested_environments: list[str] | None, catalog: _EnvironmentCatalog
) -> _EnvironmentScope:
    if requested_environments is not None:
        if requested_environments:
            return _EnvironmentScope.named(requested_environments)
        return _EnvironmentScope(scope="No matching environments", predicate="0 = 1", values=[])
    if catalog.production:
        return _EnvironmentScope.named(catalog.production)
    if catalog.options:
        return _EnvironmentScope.named(catalog.options[:1])
    return _EnvironmentScope(scope="persistent", predicate="NOT d.is_transient_environment", values=None)


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
        selected_environments=[],
        has_membership_data=has_membership_data,
        github_teams=github_teams,
        deployment_count=0,
        deployment_count_prev=0,
        deployments_per_day=None,
        deployments_per_day_prev=None,
        median_merge_to_deploy_seconds=None,
        median_merge_to_deploy_seconds_prev=None,
        median_open_to_deploy_seconds=None,
        median_open_to_deploy_seconds_prev=None,
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
        open_to_merge_series=[],
        open_to_deploy_series=[],
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
    # The newest status row synced in any environment, which shows how fresh the deploy data is.
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


def _query_frequency_series(scan: _DoraScan, granularity: Granularity) -> list[DeploymentFrequencyBucket]:
    """Successful deployments per bucket across the window, oldest first, zero-filled."""
    sql = f"WITH {scan.deploys_cte} " + (
        _FREQUENCY_SERIES_SELECT.replace("__BUCKET_FN__", bucket_expr(granularity, "first_success_at")).replace(
            "__DATE_TO_SUCCESS__", scan.date_to_filter("first_success_at")
        )
    )
    response = scan.run(sql, query_type="engineering_analytics.dora_frequency")
    count_by_bucket = {
        normalize_bucket(bucket_start, granularity): int(count or 0) for bucket_start, count in response.results or []
    }
    return [
        DeploymentFrequencyBucket(bucket_start=bucket, deployment_count=count_by_bucket.get(bucket, 0))
        for bucket in window_buckets(scan.date_from, scan.date_to, granularity)
    ]


@frozen
class _LeadTime:
    """The PR-scoped merge-to-deploy figures: window-pair counts and medians, attribution
    coverage, plus the box-plot series."""

    deployed_count: int
    deployed_count_prev: int
    median_seconds: float | None
    median_seconds_prev: float | None
    open_to_deploy_median_seconds: float | None
    open_to_deploy_median_seconds_prev: float | None
    # PRs merged in the window (the locked recipe), and how many of those a deploy attributed.
    merged_count: int
    attributed_count: int
    series: list[LeadTimeBucket]
    open_to_merge_series: list[LeadTimeBucket]
    open_to_deploy_series: list[LeadTimeBucket]

    @property
    def unattributed_share(self) -> float | None:
        return 1 - self.attributed_count / self.merged_count if self.merged_count else None


_EMPTY_LEAD_TIME = _LeadTime(
    deployed_count=0,
    deployed_count_prev=0,
    median_seconds=None,
    median_seconds_prev=None,
    open_to_deploy_median_seconds=None,
    open_to_deploy_median_seconds_prev=None,
    merged_count=0,
    attributed_count=0,
    series=[],
    open_to_merge_series=[],
    open_to_deploy_series=[],
)


def _query_lead_time(
    scan: _DoraScan, *, github_team: str | None, members_source: str | None, granularity: Granularity
) -> _LeadTime:
    # A team filter without membership data cannot be honored: empty lead-time figures, never
    # silently unfiltered ones.
    if github_team and members_source is None:
        return _EMPTY_LEAD_TIME
    team_filter = ""
    team_placeholders: dict[str, ast.Expr] = {}
    if github_team:
        team = DeliveryScope(kind=DeliveryScopeKind.GITHUB_TEAM, github_team=github_team)
        team_filter = f"AND {team.pr_predicate(scan.curated)}"
        team_placeholders = team.placeholders()
    attribution_ctes = scan.attribution_ctes(pr_filter=team_filter)

    windows = window_pair_predicates("deployed_at", date_to=scan.date_to)
    merged_window = window_pair_predicates("merged_at", date_to=scan.date_to)
    attributed_window = f"{merged_window.current} {scan.date_to_filter('deployed_at')}".strip()
    headline_sql = f"WITH {attribution_ctes} " + (
        _LEAD_TIME_HEADLINE_SELECT.replace("__CUR_DEPLOYED__", windows.current)
        .replace("__PREV_DEPLOYED__", windows.previous)
        .replace("__CUR_MERGED__", merged_window.current)
        .replace("__CUR_ATTRIBUTED__", attributed_window)
        .replace("__PR_SOURCE__", scan.curated.pr_source())
        .replace("__TEAM_FILTER__", team_filter)
    )
    headline = scan.run(headline_sql, query_type="engineering_analytics.dora_lead_time", placeholders=team_placeholders)
    (
        deployed_cur,
        deployed_prev,
        median_cur,
        median_prev,
        otd_median_cur,
        otd_median_prev,
        attributed_cur,
        merged_cur,
    ) = headline.results[0] if headline.results else (0, 0, None, None, None, None, 0, 0)

    series_sql = f"WITH {attribution_ctes} " + (
        _LEAD_TIME_SERIES_SELECT.replace("__BUCKET_FN__", bucket_expr(granularity, "deployed_at")).replace(
            "__DATE_TO_DEPLOYED__", scan.date_to_filter("deployed_at")
        )
    )
    rows = scan.run(
        series_sql, query_type="engineering_analytics.dora_lead_time_series", placeholders=team_placeholders
    )
    stats_by_bucket = {normalize_bucket(row[0], granularity): row[1:] for row in (rows.results or [])}
    buckets = window_buckets(scan.date_from, scan.date_to, granularity)
    # Row layout mirrors _LEAD_TIME_SERIES_SELECT: count, then a six-stat slice per stage.
    return _LeadTime(
        deployed_count=int(deployed_cur or 0),
        deployed_count_prev=int(deployed_prev or 0),
        median_seconds=opt_float(median_cur),
        median_seconds_prev=opt_float(median_prev),
        open_to_deploy_median_seconds=opt_float(otd_median_cur),
        open_to_deploy_median_seconds_prev=opt_float(otd_median_prev),
        merged_count=int(merged_cur or 0),
        attributed_count=int(attributed_cur or 0),
        series=[
            _lead_time_bucket(bucket, stats_by_bucket.get(bucket), stage=_STAGE_MERGE_TO_DEPLOY) for bucket in buckets
        ],
        open_to_merge_series=[
            _lead_time_bucket(bucket, stats_by_bucket.get(bucket), stage=_STAGE_OPEN_TO_MERGE) for bucket in buckets
        ],
        open_to_deploy_series=[
            _lead_time_bucket(bucket, stats_by_bucket.get(bucket), stage=_STAGE_OPEN_TO_DEPLOY) for bucket in buckets
        ],
    )


def _scan(
    curated: CuratedGitHubSource,
    deploy_sources: DeploySources,
    *,
    date_from: datetime,
    date_to: datetime | None,
    validated_environments: list[str] | None,
) -> _DoraScan:
    """Resolve the environment scope and bind the deploys CTE and placeholders every deploy read shares."""
    end = date_to or datetime.now(tz=date_from.tzinfo)
    prev_from = date_from - (end - date_from)

    placeholders: dict[str, ast.Expr] = {
        "date_from": ast.Constant(value=date_from),
        "prev_from": ast.Constant(value=prev_from),
        "deploy_scan_floor": ast.Constant(value=prev_from - _DEPLOY_SCAN_SLACK),
        "merge_scan_floor": ast.Constant(value=prev_from - _MERGE_SCAN_LOOKBACK),
        "run_started_floor": run_started_floor_constant(prev_from - _MERGE_SCAN_LOOKBACK),
    }
    if date_to is not None:
        placeholders["date_to"] = ast.Constant(value=date_to)

    catalog = _EnvironmentCatalog(
        curated=curated, deployments_source=deploy_sources.deployments, date_from=date_from, date_to=date_to
    )
    env_scope = _resolve_environment_scope(validated_environments, catalog)
    # The busiest-environment fallbacks bind the same placeholder as an explicit filter: either
    # way ``values`` holds exactly the environment names the predicate matches.
    if env_scope.values is not None:
        placeholders["environments"] = ast.Tuple(exprs=[ast.Constant(value=name) for name in env_scope.values])

    return _DoraScan(
        curated=curated,
        environment_catalog=catalog,
        environment_scope=env_scope,
        deploys_cte=(
            _DEPLOYS_CTE.replace("__DEPLOYMENTS_SOURCE__", deploy_sources.deployments)
            .replace("__STATUSES_SOURCE__", deploy_sources.statuses)
            .replace("__ENV_PREDICATE__", env_scope.predicate)
        ),
        statuses_source=deploy_sources.statuses,
        placeholders=placeholders,
        date_from=date_from,
        date_to=date_to,
    )


def query_dora_overview(
    *,
    curated: CuratedGitHubSource,
    date_from: datetime,
    date_to: datetime | None,
    validated_environments: list[str] | None = None,
    github_team: str | None = None,
    granularity: Granularity | None = None,
) -> DoraOverview:
    granularity = granularity or pick_granularity(date_from, date_to)
    deploy_sources = curated.deploy_sources()
    members_source = curated.members_source()
    has_membership_data = members_source is not None
    github_teams = _query_github_teams(curated, members_source)

    if deploy_sources is None:
        return _empty_overview(
            deploy_data_available=False,
            environment_scope=", ".join(validated_environments) if validated_environments else "persistent",
            environments=[],
            has_membership_data=has_membership_data,
            github_teams=github_teams,
            granularity=granularity,
        )

    end = date_to or datetime.now(tz=date_from.tzinfo)
    window_days = max((end - date_from).total_seconds() / 86400, 1 / 24)
    scan = _scan(
        curated, deploy_sources, date_from=date_from, date_to=date_to, validated_environments=validated_environments
    )
    outcomes = _query_deploy_outcomes(scan)
    lead = _query_lead_time(scan, github_team=github_team, members_source=members_source, granularity=granularity)

    return DoraOverview(
        deploy_data_available=True,
        environment_scope=scan.environment_scope.scope,
        environments=scan.environment_catalog.options,
        selected_environments=scan.environment_scope.values or [],
        has_membership_data=has_membership_data,
        github_teams=github_teams,
        deployment_count=outcomes.deployment_count,
        deployment_count_prev=outcomes.deployment_count_prev,
        deployments_per_day=outcomes.deployment_count / window_days,
        deployments_per_day_prev=outcomes.deployment_count_prev / window_days,
        median_merge_to_deploy_seconds=lead.median_seconds,
        median_merge_to_deploy_seconds_prev=lead.median_seconds_prev,
        median_open_to_deploy_seconds=lead.open_to_deploy_median_seconds,
        median_open_to_deploy_seconds_prev=lead.open_to_deploy_median_seconds_prev,
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
        deployment_frequency_series=_query_frequency_series(scan, granularity),
        merge_to_deploy_series=lead.series,
        open_to_merge_series=lead.open_to_merge_series,
        open_to_deploy_series=lead.open_to_deploy_series,
        series_granularity=granularity,
    )


# Every deployed PR relevant to one window, one row each: deployed in the window (the distribution
# population) or merged in it (the attribution-coverage population). The delivery summary splits the
# rows in Python, so the containment rule stays defined once, in the CTEs above.
_DEPLOYED_PR_ROWS_SELECT = f"""
    SELECT
        number,
        (__SCOPE__) AS in_scope,
        created_at,
        merged_at,
        deployed_at,
        open_to_merge_seconds,
        lead_seconds,
        open_to_deploy_seconds
    FROM ({_LEAD_TIME_INNER})
    WHERE (deployed_at >= {{date_from}} __DATE_TO_DEPLOYED__) OR (merged_at >= {{date_from}} __DATE_TO_MERGED__)
    LIMIT {UNPAGED_SCAN_LIMIT}
"""


@frozen
class DeployedPR:
    number: int
    in_scope: bool
    created_at: datetime
    merged_at: datetime
    # The first successful in-scope deployment that contains the merge.
    deployed_at: datetime
    open_to_merge_seconds: int
    merge_to_deploy_seconds: int
    open_to_deploy_seconds: int


@frozen
class DeployedPRs:
    environment_scope: str
    rows: list[DeployedPR]


def query_deployed_prs(
    *,
    curated: CuratedGitHubSource,
    date_from: datetime,
    date_to: datetime | None,
    scope_predicate: str,
    scope_placeholders: dict[str, ast.Expr],
) -> DeployedPRs | None:
    """The deployed-PR population behind lead time, in the default (production) environment scope,
    as rows. ``scope_predicate`` is a trusted SQL predicate over the unqualified ``deployed_prs``
    columns that marks each row ``in_scope``; its placeholders ride in ``scope_placeholders``. None
    when the deploy tables aren't synced."""
    deploy_sources = curated.deploy_sources()
    if deploy_sources is None:
        return None
    scan = _scan(curated, deploy_sources, date_from=date_from, date_to=date_to, validated_environments=None)
    sql = f"WITH {scan.attribution_ctes()} " + (
        _DEPLOYED_PR_ROWS_SELECT.replace("__DATE_TO_DEPLOYED__", scan.date_to_filter("deployed_at"))
        .replace("__DATE_TO_MERGED__", scan.date_to_filter("merged_at"))
        .replace("__SCOPE__", scope_predicate)
    )
    response = scan.run(sql, query_type="engineering_analytics.deployed_pr_rows", placeholders=scope_placeholders)
    rows = [
        DeployedPR(
            number=int(number),
            in_scope=bool(in_scope),
            created_at=created_at,
            merged_at=merged_at,
            deployed_at=deployed_at,
            open_to_merge_seconds=int(open_to_merge),
            merge_to_deploy_seconds=int(merge_to_deploy),
            open_to_deploy_seconds=int(open_to_deploy),
        )
        for number, in_scope, created_at, merged_at, deployed_at, open_to_merge, merge_to_deploy, open_to_deploy in (
            response.results or []
        )
        if created_at is not None and merged_at is not None and deployed_at is not None
    ]
    return DeployedPRs(environment_scope=scan.environment_scope.scope, rows=rows)


def _lead_time_bucket(bucket: datetime, stats: tuple[Any, ...] | None, *, stage: int) -> LeadTimeBucket:
    """One stage's bucket off a series row: ``stats`` is (count, then a _STAGE_STAT_WIDTH-wide
    slice per stage, in _LEAD_TIME_STAGES order); ``stage`` picks which slice."""
    if not stats:
        return LeadTimeBucket(
            bucket_start=bucket,
            deployed_pr_count=0,
            min_seconds=None,
            p05_seconds=None,
            p25_seconds=None,
            p50_seconds=None,
            mean_seconds=None,
            p75_seconds=None,
            p95_seconds=None,
            max_seconds=None,
        )
    n = stats[0]
    offset = 1 + stage * _STAGE_STAT_WIDTH
    min_s, p05, p25, p50, mean, p75, p95, max_s = stats[offset : offset + _STAGE_STAT_WIDTH]
    return LeadTimeBucket(
        bucket_start=bucket,
        deployed_pr_count=int(n or 0),
        min_seconds=opt_float(min_s),
        p05_seconds=opt_float(p05),
        p25_seconds=opt_float(p25),
        p50_seconds=opt_float(p50),
        mean_seconds=opt_float(mean),
        p75_seconds=opt_float(p75),
        p95_seconds=opt_float(p95),
        max_seconds=opt_float(max_s),
    )


def query_dora_environment_choices(
    *,
    curated: CuratedGitHubSource,
    environments: list[str],
    date_from: datetime,
    date_to: datetime | None,
) -> list[str]:
    """The ``environments`` the source deployed to in the scan window; empty without deploy data."""
    deploy_sources = curated.deploy_sources()
    if deploy_sources is None or not environments:
        return []
    catalog = _EnvironmentCatalog(
        curated=curated, deployments_source=deploy_sources.deployments, date_from=date_from, date_to=date_to
    )
    return catalog.existing(environments)


def _query_github_teams(curated: CuratedGitHubSource, members_source: str | None) -> list[str]:
    """Distinct GitHub team slugs from the membership snapshot: the team filter's options."""
    if members_source is None:
        return []
    response = curated.run(
        _TEAMS_SELECT.replace("__MEMBERS_SOURCE__", members_source),
        query_type="engineering_analytics.dora_github_teams",
    )
    return [str(slug) for (slug,) in (response.results or []) if slug]
