from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import pytest
import time_machine
from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from posthog.schema import DateRange, ErrorTrackingQuery

from posthog.clickhouse.client import sync_execute

from products.cohorts.backend.models.cohort import get_or_create_internal_test_users_cohort
from products.error_tracking.backend.hogql_queries.error_tracking_query_runner import ErrorTrackingQueryRunner
from products.posthog_ai.evals.error_tracking.seeders import _EVAL_DISTINCT_IDS, seed_error_tracking_issues
from products.posthog_ai.evals.experiments.setup_seeders import SCENARIOS, SeedEvent, build_scenario_events


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

    @time_machine.travel("2026-05-22T12:00:00Z", tick=False)
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


def _web_anonymous_share(events: tuple[SeedEvent, ...], path: str) -> float:
    views = [e for e in events if e.event == "$pageview" and e.properties.get("$pathname") == path]
    anonymous = {e.distinct_id for e in views if e.properties["$is_identified"] is False}
    return len(anonymous) / len({e.distinct_id for e in views})


@pytest.mark.parametrize(
    "key,low,high",
    [
        ("landing_page_anonymous", 0.9, 1.0),
        ("pricing_crosses_login", 0.2, 0.8),
        ("logged_in_team_page", 0.0, 0.0),
        ("low_traffic_page", 0.9, 1.0),
    ],
)
def test_setup_scenarios_have_the_anonymous_share_they_claim(key: str, low: float, high: float) -> None:
    scenario = SCENARIOS[key]
    generated = build_scenario_events(scenario, datetime(2026, 9, 21, 12, tzinfo=UTC))
    assert low <= _web_anonymous_share(generated.events, scenario.path) <= high


@pytest.mark.parametrize(
    "key,server_expected", [("pricing_crosses_login", False), ("pricing_server_local_evaluation", True)]
)
def test_setup_scenarios_only_add_server_evaluation_where_claimed(key: str, server_expected: bool) -> None:
    scenario = SCENARIOS[key]
    generated = build_scenario_events(scenario, datetime(2026, 9, 21, 12, tzinfo=UTC))
    flag_calls = [e for e in generated.events if e.event == "$feature_flag_called"]
    server_calls = [e for e in flag_calls if e.properties["$lib"] == "posthog-node"]
    assert bool(server_calls) is server_expected
    assert all(e.properties["locally_evaluated"] is True for e in server_calls)
    assert {e.properties["$feature_flag"] for e in flag_calls} == {scenario.running_flag_key}
