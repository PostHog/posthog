from __future__ import annotations

from dataclasses import dataclass

from freezegun import freeze_time
from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from posthog.schema import DateRange, ErrorTrackingQuery

from posthog.clickhouse.client import sync_execute

from products.cohorts.backend.models.cohort import get_or_create_internal_test_users_cohort
from products.error_tracking.backend.hogql_queries.error_tracking_query_runner import ErrorTrackingQueryRunner

from ee.hogai.eval.sandboxed.error_tracking.seeders import _EVAL_DISTINCT_IDS, seed_error_tracking_issues


@dataclass(frozen=True)
class _EvalSeedContext:
    team_id: int
    user_id: int
    repository: str


class TestErrorTrackingEvalSeeders(ClickhouseTestMixin, APIBaseTest):
    @classmethod
    def setUpClass(cls) -> None:
        from ee.clickhouse.materialized_columns.columns import get_materialized_columns, materialize

        for property_name in ("$exception_types", "$exception_values"):
            if (property_name, "properties") not in get_materialized_columns("events"):
                materialize("events", property_name)
        super().setUpClass()

    @freeze_time("2026-05-22T12:00:00Z")
    def test_error_tracking_seeded_events_survive_person_filters(self) -> None:
        test_users_cohort = get_or_create_internal_test_users_cohort(
            self.team, initiating_user_email="eval-master-seed@posthog.test"
        )
        self.team.test_account_filters = [
            {"key": "id", "type": "cohort", "value": test_users_cohort.pk, "operator": "not_in"}
        ]
        self.team.save(update_fields=["test_account_filters"])

        seed = seed_error_tracking_issues(
            _EvalSeedContext(team_id=self.team.id, user_id=self.user.id, repository="posthog/hedgebox")
        )
        target_id = next(item["id"] for item in seed["lookup_issues"] if item["name"] == "Team invite rejected")

        person_rows = sync_execute(
            """
            SELECT distinct_id
            FROM person_distinct_id2
            WHERE team_id = %(team_id)s AND distinct_id IN %(distinct_ids)s
            """,
            {"team_id": self.team.id, "distinct_ids": list(_EVAL_DISTINCT_IDS)},
        )
        assert {row[0] for row in person_rows} == set(_EVAL_DISTINCT_IDS)
        issue_state_rows = sync_execute(
            """
            SELECT issue_id
            FROM error_tracking_fingerprint_issue_state
            WHERE team_id = %(team_id)s
            """,
            {"team_id": self.team.id},
        )
        assert {str(row[0]) for row in issue_state_rows} == {item["id"] for item in seed["lookup_issues"]}

        response = (
            ErrorTrackingQueryRunner(
                team=self.team,
                query=ErrorTrackingQuery(
                    kind="ErrorTrackingQuery",
                    dateRange=DateRange(),
                    status="active",
                    searchQuery="team-invite TypeError",
                    filterTestAccounts=True,
                    orderBy="occurrences",
                    volumeResolution=1,
                    withAggregations=True,
                    withFirstEvent=False,
                    withLastEvent=False,
                ),
            )
            .calculate()
            .model_dump()
        )

        assert [(result["id"], result["function"], result["source"]) for result in response["results"]] == [
            (
                target_id,
                "submitInvite",
                "https://app.hedgebox.test/static/js/team-invite.js",
            )
        ]
