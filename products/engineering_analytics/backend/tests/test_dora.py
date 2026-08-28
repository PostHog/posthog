from datetime import UTC, datetime
from typing import Any

from posthog.test.base import APIBaseTest, BaseTest, ClickhouseTestMixin

from rest_framework import status

from posthog.models.team import Team

from products.engineering_analytics.backend.logic.queries._curated import CuratedGitHubSource
from products.engineering_analytics.backend.logic.queries.dora import query_dora_overview
from products.engineering_analytics.backend.logic.sources import GitHubTables
from products.engineering_analytics.backend.logic.views.source_schema import (
    DEPLOYMENT_STATUSES_COLUMNS,
    DEPLOYMENTS_COLUMNS,
    PULL_REQUESTS_COLUMNS,
    TEAM_MEMBERS_COLUMNS,
)
from products.engineering_analytics.backend.tests._github_fixtures import (
    _pr_row,
    connect_github_source_without_data,
    create_github_warehouse_table,
)


def _deployment_row(
    deployment_id: int, sha: str, environment: str, created_at: str, *, production: bool, transient: bool = False
) -> dict:
    return {
        "id": deployment_id,
        "sha": sha,
        "ref": "master",
        "task": "deploy",
        "environment": environment,
        "original_environment": environment,
        "description": "",
        "creator": "{}",
        "payload": "{}",
        "production_environment": production,
        "transient_environment": transient,
        "created_at": created_at,
        "updated_at": created_at,
    }


def _status_row(status_id: int, deployment_id: int, state: str, environment: str, created_at: str) -> dict:
    return {
        "id": status_id,
        "deployment_id": deployment_id,
        "state": state,
        "creator": "{}",
        "description": "",
        "environment": environment,
        "target_url": "",
        "log_url": "",
        "environment_url": "",
        "created_at": created_at,
        "updated_at": created_at,
    }


class TestDoraEndpoint(ClickhouseTestMixin, APIBaseTest):
    def test_degrades_without_deploy_tables(self):
        # The source resolves (pull_requests + workflow_runs) but has no deployments schemas:
        # the endpoint must answer deploy_data_available=false instead of querying missing tables.
        connect_github_source_without_data(self.team, prefix="dora", repository="PostHog/posthog")

        response = self.client.get(f"/api/projects/{self.team.id}/engineering_analytics/dora/")
        assert response.status_code == status.HTTP_200_OK, response.content
        payload = response.json()
        assert payload["deploy_data_available"] is False
        assert payload["deployment_count"] == 0
        assert payload["deployments_per_day"] is None
        assert payload["deployment_frequency_series"] == []
        assert payload["merge_to_deploy_series"] == []


class TestDoraQuery(ClickhouseTestMixin, BaseTest):
    def _curated(
        self,
        team: Team,
        *,
        deployment_rows: list[dict[str, Any]],
        status_rows: list[dict[str, Any]],
        pr_rows: list[dict[str, Any]],
        member_rows: list[dict[str, Any]] | None = None,
    ) -> CuratedGitHubSource:
        deployments_table = create_github_warehouse_table(
            self, "github_deployments", DEPLOYMENTS_COLUMNS, deployment_rows
        )
        statuses_table = create_github_warehouse_table(
            self, "github_deployment_statuses", DEPLOYMENT_STATUSES_COLUMNS, status_rows
        )
        pr_table = create_github_warehouse_table(self, "github_pull_requests", PULL_REQUESTS_COLUMNS, pr_rows)
        members_table = (
            create_github_warehouse_table(self, "github_team_members", TEAM_MEMBERS_COLUMNS, member_rows)
            if member_rows is not None
            else None
        )
        return CuratedGitHubSource(
            team=team,
            tables=GitHubTables(
                pull_requests=pr_table,
                workflow_runs="unused",
                team_members=members_table,
                deployments=deployments_table,
                deployment_statuses=statuses_table,
            ),
        )

    def _seeded_curated(self, member_rows: list[dict[str, Any]] | None) -> CuratedGitHubSource:
        # Window 2026-01-10 → 2026-01-20; previous window 2025-12-31 → 2026-01-10.
        # prod: d1 succeeds Jan 12, d2 fails Jan 13, d3 succeeds Jan 13 (d2's recovery, 2h later),
        # d5 succeeded in the previous window, d6 never reached an outcome (no status rows).
        # Each successful deploy's sha is a merged PR's merge_commit_sha (its head): PR 1 heads
        # d1, PR 2 heads d3, PR 5 heads d5. Attribution follows head merge order, not success
        # time: PR 6 (carol) merges Jan 12 09:00, AFTER d1's head merge (08:00), so d1 — despite
        # succeeding later that day — does not contain it and it waits for d3.
        # staging: d4 succeeds Jan 12 09:00 — before d1 — so a production-scope leak would
        # change PR 1's lead time from 2h to 1h.
        return self._curated(
            self.team,
            deployment_rows=[
                _deployment_row(1, "sha-a", "prod", "2026-01-12 09:30:00", production=True),
                _deployment_row(2, "sha-b", "prod", "2026-01-13 09:30:00", production=True),
                _deployment_row(3, "sha-c", "prod", "2026-01-13 11:30:00", production=True),
                _deployment_row(4, "sha-d", "staging", "2026-01-12 08:30:00", production=False),
                _deployment_row(5, "sha-e", "prod", "2026-01-05 09:30:00", production=True),
                _deployment_row(6, "sha-f", "prod", "2026-01-14 09:30:00", production=True),
            ],
            status_rows=[
                _status_row(11, 1, "in_progress", "prod", "2026-01-12 09:31:00"),
                _status_row(12, 1, "success", "prod", "2026-01-12 10:00:00"),
                _status_row(21, 2, "failure", "prod", "2026-01-13 10:00:00"),
                _status_row(31, 3, "success", "prod", "2026-01-13 12:00:00"),
                _status_row(41, 4, "success", "staging", "2026-01-12 09:00:00"),
                _status_row(51, 5, "success", "prod", "2026-01-05 10:00:00"),
            ],
            pr_rows=[
                # alice heads d1 and merges 2h before its success; bob heads d3, 2.5h before its.
                _pr_row(
                    1,
                    "alice",
                    "closed",
                    0,
                    "2026-01-11 08:00:00",
                    merged_at="2026-01-12 08:00:00",
                    merge_commit_sha="sha-a",
                ),
                _pr_row(
                    2,
                    "bob",
                    "closed",
                    0,
                    "2026-01-12 08:00:00",
                    merged_at="2026-01-13 09:30:00",
                    merge_commit_sha="sha-c",
                ),
                # Bot merge in the same slot as PR 1: must not move the lead-time figures.
                _pr_row(3, "dependabot[bot]", "closed", 0, "2026-01-11 08:00:00", merged_at="2026-01-12 08:00:00"),
                # Merged but never deployed in the window: not part of the deployed population.
                _pr_row(4, "alice", "closed", 0, "2026-01-19 08:00:00", merged_at="2026-01-19 23:00:00"),
                # Previous window: deployed by d5 (which it heads), backing the _prev twins.
                _pr_row(
                    5,
                    "alice",
                    "closed",
                    0,
                    "2026-01-05 06:00:00",
                    merged_at="2026-01-05 08:00:00",
                    merge_commit_sha="sha-e",
                ),
                # Merged after d1's head merge but before d1's success: the success-time rule would
                # wrongly hand it d1 (1h lead); containment makes it wait for d3 (27h lead).
                _pr_row(6, "carol", "closed", 0, "2026-01-11 09:00:00", merged_at="2026-01-12 09:00:00"),
            ],
            member_rows=member_rows,
        )

    def test_dora_over_seeded_deploys(self):
        # Guards the freshly written HogQL end to end over the real nullable string schema:
        # production scoping, success/failure keying, the recovery self-join, the merged-PR
        # deploy attribution (bots excluded), and both zero-filled series.
        curated = self._seeded_curated(member_rows=None)
        result = query_dora_overview(
            curated=curated,
            date_from=datetime(2026, 1, 10, tzinfo=UTC),
            date_to=datetime(2026, 1, 20, tzinfo=UTC),
        )

        assert result.deploy_data_available is True
        assert result.environment_scope == "production"
        assert result.environments == ["prod", "staging"]
        assert result.has_membership_data is False
        assert result.github_teams == []

        assert result.deployment_count == 2  # d1 + d3; d2 never succeeded, d4 is staging
        assert result.deployment_count_prev == 1  # d5
        assert result.deployments_per_day == 0.2
        assert result.failed_deployment_count == 1  # d2
        assert result.failed_deployment_share == 1 / 3  # outcomes in window: d1, d2, d3
        assert result.median_failed_deploy_to_next_success_seconds == 7200.0  # d2 10:00 → d3 12:00

        assert result.deployed_pr_count == 3  # PRs 1, 2, 6; bot and undeployed merges excluded
        assert result.deployed_pr_count_prev == 1  # PR 5 via d5
        # PR 1: 7200 via d1. PR 2: 9000 via d3. PR 6: 97200 via d3 — the containment rule at
        # work: d1 succeeded after PR 6's merge but its head merged before it, so d1 doesn't count.
        assert result.median_merge_to_deploy_seconds == 9000.0
        assert result.median_merge_to_deploy_seconds_prev == 7200.0
        assert result.merged_pr_count == 4  # PRs 1, 2, 4, 6; the bot merge is excluded
        assert result.unattributed_merged_pr_share == 0.25  # PR 4 merged Jan 19, never deployed
        assert result.latest_deploy_status_at == datetime(2026, 1, 13, 12, 0, tzinfo=UTC)

        assert result.series_granularity == "day"
        frequency = {bucket.bucket_start: bucket.deployment_count for bucket in result.deployment_frequency_series}
        assert len(result.deployment_frequency_series) == 11  # zero-filled Jan 10 → Jan 20
        assert frequency[datetime(2026, 1, 12)] == 1
        assert frequency[datetime(2026, 1, 13)] == 1
        assert frequency[datetime(2026, 1, 15)] == 0

        lead = {bucket.bucket_start: bucket for bucket in result.merge_to_deploy_series}
        assert len(result.merge_to_deploy_series) == 11
        jan_12 = lead[datetime(2026, 1, 12)]
        assert jan_12.deployed_pr_count == 1
        assert jan_12.min_seconds == jan_12.max_seconds == jan_12.p50_seconds == jan_12.mean_seconds == 7200.0
        jan_13 = lead[datetime(2026, 1, 13)]
        assert jan_13.deployed_pr_count == 2  # PRs 2 and 6, both deployed by d3
        assert jan_13.min_seconds == 9000.0
        assert jan_13.max_seconds == 97200.0
        empty = lead[datetime(2026, 1, 15)]
        assert empty.deployed_pr_count == 0
        assert empty.p50_seconds is None

    def test_restore_recovery_excluded_when_it_lands_after_date_to(self):
        # d2 fails Jan 13 10:00, recovers via d3's success at Jan 13 12:00 (see _seeded_curated).
        # A historical report ending before that recovery must not count it: "no recovery in the
        # window" should stay null instead of reaching past date_to for the next success.
        curated = self._seeded_curated(member_rows=None)
        result = query_dora_overview(
            curated=curated,
            date_from=datetime(2026, 1, 10, tzinfo=UTC),
            date_to=datetime(2026, 1, 13, 11, 0, 0, tzinfo=UTC),
        )

        assert result.failed_deployment_count == 1  # d2 still counts as a failure in this window
        assert result.median_failed_deploy_to_next_success_seconds is None

    def test_github_team_filter_narrows_lead_time_only(self):
        curated = self._seeded_curated(
            member_rows=[
                {"id": 1, "login": "alice", "team_id": 1, "team_slug": "team-replay", "team_name": "team-replay"},
                {"id": 2, "login": "bob", "team_id": 2, "team_slug": "team-ingestion", "team_name": "team-ingestion"},
            ]
        )
        result = query_dora_overview(
            curated=curated,
            date_from=datetime(2026, 1, 10, tzinfo=UTC),
            date_to=datetime(2026, 1, 20, tzinfo=UTC),
            github_team="team-replay",
        )

        assert result.has_membership_data is True
        assert result.github_teams == ["team-ingestion", "team-replay"]
        # Only alice's merges count toward lead time and coverage; deploy counts stay repo-wide.
        assert result.deployed_pr_count == 1
        assert result.median_merge_to_deploy_seconds == 7200.0
        assert result.merged_pr_count == 2  # alice's PRs 1 and 4
        assert result.unattributed_merged_pr_share == 0.5  # PR 4 never deployed
        assert result.deployment_count == 2

    def test_team_filter_without_membership_returns_empty_lead_time(self):
        curated = self._seeded_curated(member_rows=None)
        result = query_dora_overview(
            curated=curated,
            date_from=datetime(2026, 1, 10, tzinfo=UTC),
            date_to=datetime(2026, 1, 20, tzinfo=UTC),
            github_team="team-replay",
        )

        # The filter can't be honored, so the lead-time figures go empty, never silently unfiltered.
        assert result.has_membership_data is False
        assert result.deployed_pr_count == 0
        assert result.median_merge_to_deploy_seconds is None
        assert result.merge_to_deploy_series == []
        # Deploy-scoped figures are unaffected.
        assert result.deployment_count == 2

    def test_busiest_environment_fallback_excludes_transient_and_sibling_environments(self):
        # Nothing is production-marked (this repo's real shape), so the default scope falls back
        # to the single busiest persistent environment: the ephemeral per-PR preview deploys and
        # the quieter sibling environment (a second region, dev, a package registry) must stay
        # out of the counts — every-persistent counted them all and multiplied every metric.
        curated = self._curated(
            self.team,
            deployment_rows=[
                _deployment_row(1, "sha-a", "prod-us", "2026-01-12 09:30:00", production=False),
                _deployment_row(2, "sha-b", "preview-pr-123", "2026-01-12 09:30:00", production=False, transient=True),
                _deployment_row(3, "sha-c", "prod-us", "2026-01-13 09:30:00", production=False),
                _deployment_row(4, "sha-d", "dev", "2026-01-12 09:30:00", production=False),
            ],
            status_rows=[
                _status_row(11, 1, "success", "prod-us", "2026-01-12 10:00:00"),
                _status_row(21, 2, "success", "preview-pr-123", "2026-01-12 10:00:00"),
                _status_row(31, 3, "success", "prod-us", "2026-01-13 10:00:00"),
                _status_row(41, 4, "success", "dev", "2026-01-12 10:00:00"),
            ],
            # One never-merged PR keeps the seeded CSV non-empty without joining any deploy.
            pr_rows=[_pr_row(1, "alice", "open", 0, "2026-01-11 08:00:00")],
        )
        result = query_dora_overview(
            curated=curated,
            date_from=datetime(2026, 1, 10, tzinfo=UTC),
            date_to=datetime(2026, 1, 20, tzinfo=UTC),
        )

        assert result.environment_scope == "prod-us"
        assert result.environments == ["prod-us", "dev"]
        assert result.deployment_count == 2

    def test_deploy_scan_slack_bounds_prewindow_deployments(self):
        # A deployment created before the scan window still counts when its success lands inside
        # it, up to the 7-day slack; beyond the slack it is excluded even with an in-window success.
        curated = self._curated(
            self.team,
            deployment_rows=[
                # Created 3 days before prev_from (2025-12-31): inside the slack.
                _deployment_row(1, "sha-a", "prod", "2025-12-28 09:00:00", production=True),
                # Created 9 days before prev_from: outside the slack, excluded from every read.
                _deployment_row(2, "sha-b", "prod", "2025-12-22 09:00:00", production=True),
            ],
            status_rows=[
                _status_row(11, 1, "success", "prod", "2026-01-12 10:00:00"),
                _status_row(21, 2, "success", "prod", "2026-01-13 10:00:00"),
            ],
            pr_rows=[_pr_row(1, "alice", "open", 0, "2026-01-11 08:00:00")],
        )
        result = query_dora_overview(
            curated=curated,
            date_from=datetime(2026, 1, 10, tzinfo=UTC),
            date_to=datetime(2026, 1, 20, tzinfo=UTC),
        )

        assert result.deployment_count == 1

    def test_exact_environment_scope(self):
        # A dedicated fixture, not _seeded_curated: that shared fixture's PR 5 (merged Jan 5) has
        # no earlier production match once scoped to staging-only, so it would fall through and
        # pair with staging's one deployment too, contaminating the median this test isolates.
        curated = self._curated(
            self.team,
            deployment_rows=[
                _deployment_row(1, "sha-a", "prod", "2026-01-12 09:30:00", production=True),
                _deployment_row(4, "sha-d", "staging", "2026-01-12 08:30:00", production=False),
            ],
            status_rows=[
                _status_row(11, 1, "success", "prod", "2026-01-12 10:00:00"),
                _status_row(41, 4, "success", "staging", "2026-01-12 09:00:00"),
            ],
            pr_rows=[
                _pr_row(
                    1,
                    "alice",
                    "closed",
                    0,
                    "2026-01-11 08:00:00",
                    merged_at="2026-01-12 08:00:00",
                    merge_commit_sha="sha-d",
                ),
            ],
        )
        result = query_dora_overview(
            curated=curated,
            date_from=datetime(2026, 1, 10, tzinfo=UTC),
            date_to=datetime(2026, 1, 20, tzinfo=UTC),
            environment="staging",
        )

        assert result.environment_scope == "staging"
        assert result.deployment_count == 1  # d4 only; d1 (prod) excluded by the exact scope
        assert result.failed_deployment_count == 0
        # PR 1 (merged Jan 12 08:00) reaches staging's 09:00 success: a 1h lead time.
        assert result.median_merge_to_deploy_seconds == 3600.0
