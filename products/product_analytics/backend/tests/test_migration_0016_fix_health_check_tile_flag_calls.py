import importlib
from typing import Any

from posthog.test.base import TestMigrations
from unittest.mock import ANY

from products.product_analytics.backend.models import Insight as LiveInsight

migration = importlib.import_module(
    "products.product_analytics.backend.migrations.0016_fix_health_check_tile_flag_calls"
)


BROWSER_FILTER = {"key": "$browser", "type": "event", "value": ["Chrome"], "operator": "exact"}


def _tile(query: str, properties: list | None = None) -> dict:
    filters: dict = {"dateRange": {"date_from": "-30d", "explicitDate": False}}
    if properties is not None:
        filters["properties"] = properties
    return {
        "kind": "DataVisualizationNode",
        "display": "ActionsTable",
        "source": {"kind": "HogQLQuery", "query": query, "filters": filters},
    }


def _generated_metadata(team: Any, query: dict) -> dict:
    insight = LiveInsight(team=team, query=query)
    insight.generate_query_metadata()
    assert insight.query_metadata is not None
    return insight.query_metadata


EDITED_QUERY = migration.OLD_QUERY.replace("LIMIT 200", "LIMIT 2000")
OLD_METADATA = {"events": ["survey dismissed", "survey sent", "survey shown"], "properties": []}


class TestFixHealthCheckTileFlagCalls(TestMigrations):
    app = "product_analytics"
    migrate_from = "0015_insightagentread"
    migrate_to = "0016_fix_health_check_tile_flag_calls"

    def setUpBeforeMigration(self, apps: Any) -> None:
        Insight = apps.get_model("product_analytics", "Insight")
        self.copy = Insight.objects.create(
            team_id=self.team.id, query=_tile(migration.OLD_QUERY), query_metadata=OLD_METADATA
        ).id
        self.edited_copy = Insight.objects.create(
            team_id=self.team.id, query=_tile(EDITED_QUERY), query_metadata=OLD_METADATA
        ).id
        filtered_tile = _tile(migration.OLD_QUERY, [BROWSER_FILTER])
        self.filtered_copy = Insight.objects.create(
            team_id=self.team.id,
            query=filtered_tile,
            query_metadata=_generated_metadata(self.team, filtered_tile),
        ).id
        self.copy_without_metadata = Insight.objects.create(
            team_id=self.team.id, query=_tile(migration.OLD_QUERY), query_metadata=None
        ).id

    def test_rewrites_only_unedited_copies(self) -> None:
        Insight = self.apps.get_model("product_analytics", "Insight")  # type: ignore[union-attr]

        copy = Insight.objects.get(id=self.copy)
        assert copy.query == _tile(migration.NEW_QUERY)
        assert copy.query_metadata == {**_generated_metadata(self.team, copy.query), "updated_at": ANY}

        filtered_copy = Insight.objects.get(id=self.filtered_copy)
        assert filtered_copy.query == _tile(migration.NEW_QUERY, [BROWSER_FILTER])
        assert filtered_copy.query_metadata == {
            **_generated_metadata(self.team, filtered_copy.query),
            "updated_at": ANY,
        }
        assert filtered_copy.query_metadata["properties"] != []

        copy_without_metadata = Insight.objects.get(id=self.copy_without_metadata)
        assert copy_without_metadata.query == _tile(migration.NEW_QUERY)
        assert copy_without_metadata.query_metadata is None

        edited_copy = Insight.objects.get(id=self.edited_copy)
        assert edited_copy.query == _tile(EDITED_QUERY)
        assert edited_copy.query_metadata == OLD_METADATA
