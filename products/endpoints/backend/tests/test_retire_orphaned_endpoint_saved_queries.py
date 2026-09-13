from io import StringIO
from uuid import uuid4

import pytest
from posthog.test.base import BaseTest

from django.core.management import call_command

from products.data_modeling.backend.logic.saved_query_dag_sync import sync_saved_query_to_dag
from products.data_modeling.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery
from products.data_modeling.backend.models.node import Node
from products.endpoints.backend.models import Endpoint, EndpointVersion


@pytest.mark.django_db
class TestRetireOrphanedEndpointSavedQueries(BaseTest):
    def _endpoint_saved_query(self, name: str, *, linked: bool) -> DataWarehouseSavedQuery:
        saved_query = DataWarehouseSavedQuery.objects.create(
            name=name,
            team=self.team,
            query={"kind": "HogQLQuery", "query": "SELECT 1"},
            origin=DataWarehouseSavedQuery.Origin.ENDPOINT,
            is_materialized=True,
        )
        sync_saved_query_to_dag(saved_query)
        if linked:
            endpoint = Endpoint.objects.create(team=self.team, name=f"ep_{uuid4().hex[:8]}")
            EndpointVersion.objects.create(
                endpoint=endpoint,
                team=self.team,
                version=1,
                query=saved_query.query,
                saved_query=saved_query,
            )
        return saved_query

    def _run(self, *args: str) -> str:
        out = StringIO()
        call_command("retire_orphaned_endpoint_saved_queries", *args, stdout=out, stderr=StringIO())
        return out.getvalue()

    def test_retires_only_the_query_no_version_points_at(self):
        orphan = self._endpoint_saved_query("orphan_v1", linked=False)
        linked = self._endpoint_saved_query("linked_v1", linked=True)

        self._run("--team-id", str(self.team.pk), "--apply")

        orphan.refresh_from_db()
        self.assertTrue(orphan.deleted)
        self.assertFalse(orphan.is_materialized)
        self.assertFalse(Node.objects.filter(saved_query=orphan).exists())

        linked.refresh_from_db()
        self.assertFalse(linked.deleted)
        self.assertTrue(linked.is_materialized)
        self.assertTrue(Node.objects.filter(saved_query=linked).exists())

    def test_dry_run_changes_nothing(self):
        orphan = self._endpoint_saved_query("orphan_v1", linked=False)

        output = self._run("--team-id", str(self.team.pk))

        self.assertIn("orphan_v1", output)
        orphan.refresh_from_db()
        self.assertFalse(orphan.deleted)
        self.assertTrue(Node.objects.filter(saved_query=orphan).exists())
