from datetime import UTC, datetime, timedelta

from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from posthog.hogql.database.database import Database
from posthog.hogql.database.s3_table import DataWarehouseTable as HogQLDataWarehouseTable
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client import sync_execute
from posthog.constants import AvailableFeature
from posthog.models import PropertyDefinition
from posthog.models.organization import OrganizationMembership

from products.access_control.backend.facade.contracts import PropertyAccessLevel
from products.access_control.backend.models.property_access_control import PropertyAccessControl
from products.mcp_analytics.backend.facade.clickhouse_schema import MCP_INTENT_ASSIGNMENTS_WRITABLE_TABLE
from products.warehouse_sources.backend.facade.models import DataWarehouseCredential, DataWarehouseTable

# ClickHouse applies the table TTL with its own clock, so fixtures stay relative to now.
OTHER_TEAM_ID = 10**9


def _now() -> datetime:
    return datetime.now(tz=UTC).replace(microsecond=0)


def _insert_assignment(team_id: int, intent_hash: str, topic_id: str | None, **overrides) -> None:
    row = {
        "team_id": team_id,
        "intent_hash": intent_hash,
        "run_id": "run-1",
        "topic_id": topic_id,
        "distance": 0.1,
        "x": 1.0,
        "y": -1.0,
        "is_outlier": 0,
        "intent_text": "list feature flags",
        "calls_in_run": 3,
        "timestamp": _now() - timedelta(days=1),
        **overrides,
    }
    sync_execute(
        f"""
        INSERT INTO {MCP_INTENT_ASSIGNMENTS_WRITABLE_TABLE}
        (team_id, intent_hash, run_id, topic_id, distance, x, y, is_outlier, intent_text, calls_in_run, timestamp)
        VALUES
        """,
        [row],
    )


class TestMCPIntentAssignmentsTable(ClickhouseTestMixin, APIBaseTest):
    def test_rows_round_trip_through_hogql(self) -> None:
        _insert_assignment(self.team.pk, "a" * 64, "topic-1")
        _insert_assignment(self.team.pk, "b" * 64, None, is_outlier=1, distance=0.9)

        response = execute_hogql_query(
            query="""
                SELECT intent_hash, topic_id, is_outlier, round(toFloat(distance), 2), x, y, intent_text, calls_in_run
                FROM posthog.mcp_intent_assignments
                ORDER BY intent_hash
            """,
            team=self.team,
        )

        assert response.results == [
            ("a" * 64, "topic-1", 0, 0.1, 1.0, -1.0, "list feature flags", 3),
            ("b" * 64, None, 1, 0.9, 1.0, -1.0, "list feature flags", 3),
        ]

    def test_returns_only_the_latest_assignment_per_intent_across_partitions(self) -> None:
        # Rows in different monthly partitions never merge, so the read itself must dedupe.
        _insert_assignment(self.team.pk, "a" * 64, "topic-1", run_id="run-1", timestamp=_now() - timedelta(days=40))
        _insert_assignment(self.team.pk, "a" * 64, "topic-2", run_id="run-2", timestamp=_now() - timedelta(days=1))

        deduped = execute_hogql_query(
            query="SELECT intent_hash, topic_id, run_id FROM posthog.mcp_intent_assignments", team=self.team
        )
        raw = execute_hogql_query(query="SELECT count() FROM posthog.raw_mcp_intent_assignments", team=self.team)

        assert deduped.results == [("a" * 64, "topic-2", "run-2")]
        assert raw.results == [(2,)]

    def test_filters_apply_after_the_latest_assignment_is_chosen(self) -> None:
        _insert_assignment(self.team.pk, "a" * 64, "topic-1", run_id="run-1", timestamp=_now() - timedelta(days=2))
        _insert_assignment(self.team.pk, "a" * 64, "topic-2", run_id="run-2", timestamp=_now() - timedelta(days=1))

        response = execute_hogql_query(
            query="SELECT intent_hash FROM posthog.mcp_intent_assignments WHERE topic_id = 'topic-1'", team=self.team
        )

        assert response.results == []

    def test_other_teams_rows_are_invisible(self) -> None:
        _insert_assignment(OTHER_TEAM_ID, "c" * 64, "topic-9")
        _insert_assignment(self.team.pk, "a" * 64, "topic-1")

        response = execute_hogql_query(query="SELECT intent_hash FROM posthog.mcp_intent_assignments", team=self.team)
        raw = execute_hogql_query(query="SELECT intent_hash FROM posthog.raw_mcp_intent_assignments", team=self.team)

        assert response.results == [("a" * 64,)]
        assert raw.results == [("a" * 64,)]

    def test_a_warehouse_table_with_the_bare_name_still_resolves_to_the_warehouse_table(self) -> None:
        credential = DataWarehouseCredential.objects.create(access_key="key", access_secret="secret", team=self.team)
        DataWarehouseTable.objects.create(
            name="mcp_intent_assignments",
            format="Parquet",
            team=self.team,
            credential=credential,
            url_pattern="https://bucket.s3/data/*",
            columns={"id": {"hogql": "StringDatabaseField", "clickhouse": "Nullable(String)", "schema_valid": True}},
        )

        database = Database.create_for(team=self.team)

        assert isinstance(database.get_table("mcp_intent_assignments"), HogQLDataWarehouseTable)

    def test_restricting_the_intent_property_masks_the_raw_hash_and_text_and_empties_the_deduped_table(self) -> None:
        # intent_text copies $mcp_intent and intent_hash is its unsalted sha256, so a reader denied the property
        # must not read or filter on either. The deduped table cannot pick one row per intent without the hash.
        _insert_assignment(self.team.pk, "a" * 64, "topic-0", timestamp=_now() - timedelta(days=2))
        _insert_assignment(self.team.pk, "a" * 64, "topic-1")
        _insert_assignment(self.team.pk, "b" * 64, "topic-2")
        self.organization.available_product_features = [
            {"name": AvailableFeature.PROPERTY_ACCESS_CONTROL, "key": AvailableFeature.PROPERTY_ACCESS_CONTROL}
        ]
        self.organization.save()
        definition = PropertyDefinition.objects.create(
            team=self.team, name="$mcp_intent", property_type="String", type=PropertyDefinition.Type.EVENT
        )
        PropertyAccessControl.objects.create(
            team=self.team, property_definition=definition, access_level=PropertyAccessLevel.NONE.value
        )
        hash_a = "a" * 64

        def run(query: str) -> list[tuple]:
            return execute_hogql_query(query=query, team=self.team, user=self.user).results

        raw_star = execute_hogql_query(
            query="SELECT * FROM posthog.raw_mcp_intent_assignments ORDER BY topic_id", team=self.team, user=self.user
        )
        # A background merge can drop the older topic-0 row of the same intent, so only the masking is checked.
        raw_rows = [dict(zip(raw_star.columns or [], values)) for values in raw_star.results]
        assert {(row["intent_hash"], row["intent_text"]) for row in raw_rows} == {(None, None)}
        assert {"topic-1", "topic-2"} <= {row["topic_id"] for row in raw_rows}
        assert run(f"SELECT count() FROM posthog.raw_mcp_intent_assignments WHERE intent_hash = '{hash_a}'") == [(0,)]
        assert run(
            "SELECT count() FROM posthog.raw_mcp_intent_assignments WHERE intent_text = 'list feature flags'"
        ) == [(0,)]
        assert run("SELECT count() FROM posthog.mcp_intent_assignments") == [(0,)]

        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        [(admin_hash_matches,)] = run(
            f"SELECT count() FROM posthog.raw_mcp_intent_assignments WHERE intent_hash = '{hash_a}'"
        )
        assert admin_hash_matches >= 1
        assert run(
            "SELECT intent_hash, topic_id, intent_text FROM posthog.mcp_intent_assignments ORDER BY intent_hash"
        ) == [
            (hash_a, "topic-1", "list feature flags"),
            ("b" * 64, "topic-2", "list feature flags"),
        ]
