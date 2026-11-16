import importlib
from typing import Any

from posthog.test.base import TestMigrations
from unittest.mock import ANY

from products.product_analytics.backend.models import Insight as LiveInsight

migration = importlib.import_module(
    "products.product_analytics.backend.migrations.0016_fix_health_check_tile_flag_calls"
)


def _tile(query: str) -> dict:
    return {
        "kind": "DataVisualizationNode",
        "display": "ActionsTable",
        "source": {
            "kind": "HogQLQuery",
            "query": query,
            "filters": {"dateRange": {"date_from": "-30d", "explicitDate": False}},
        },
    }


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

    def test_rewrites_only_unedited_copies(self) -> None:
        Insight = self.apps.get_model("product_analytics", "Insight")  # type: ignore[union-attr]

        copy = Insight.objects.get(id=self.copy)
        saved = LiveInsight(team=self.team, query=copy.query)
        saved.generate_query_metadata()
        assert saved.query_metadata is not None
        assert copy.query == _tile(migration.NEW_QUERY)
        assert copy.query_metadata == {**saved.query_metadata, "updated_at": ANY}

        edited_copy = Insight.objects.get(id=self.edited_copy)
        assert edited_copy.query == _tile(EDITED_QUERY)
        assert edited_copy.query_metadata == OLD_METADATA
