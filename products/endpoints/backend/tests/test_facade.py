from posthog.test.base import BaseTest

from posthog.models.team import Team

from products.endpoints.backend.facade import api as facade
from products.endpoints.backend.tests.conftest import create_endpoint_with_version

SAMPLE_QUERY = {"kind": "HogQLQuery", "query": "SELECT count(1) FROM query_log"}


class TestEndpointsFacade(BaseTest):
    def test_endpoint_reads_are_team_scoped_and_exclude_deleted(self):
        endpoint = create_endpoint_with_version("live_endpoint", self.team, SAMPLE_QUERY, self.user)
        deleted = create_endpoint_with_version("deleted_endpoint", self.team, SAMPLE_QUERY, self.user)
        deleted.soft_delete()
        other_team = Team.objects.create(organization=self.organization)
        create_endpoint_with_version("other_team_endpoint", other_team, SAMPLE_QUERY, self.user)

        listed = facade.list_endpoints(self.team.id)
        assert [e.name for e in listed] == ["live_endpoint"]
        assert facade.get_endpoint(self.team.id, "deleted_endpoint") is None
        assert facade.get_endpoint(other_team.id, "live_endpoint") is None

        info = facade.get_endpoint(self.team.id, "live_endpoint")
        assert info is not None
        assert info.id == endpoint.id
        assert info.team_id == self.team.id
        assert info.is_active is True
        assert info.current_version == 1

    def test_get_endpoint_version_resolves_current_and_specific(self):
        endpoint = create_endpoint_with_version("versioned", self.team, SAMPLE_QUERY, self.user)
        new_query = {"kind": "HogQLQuery", "query": "SELECT 2"}
        endpoint.create_new_version(new_query, self.user)

        current = facade.get_endpoint_version(self.team.id, "versioned")
        assert current is not None
        assert current.version == 2
        assert current.query == new_query
        assert current.endpoint_id == endpoint.id
        assert current.is_materialized is False

        v1 = facade.get_endpoint_version(self.team.id, "versioned", version=1)
        assert v1 is not None
        assert v1.query == SAMPLE_QUERY

        assert facade.get_endpoint_version(self.team.id, "versioned", version=99) is None
        assert facade.get_endpoint_version(self.team.id, "missing") is None

    def test_wiring_reexports_resolve(self):
        from products.endpoints.backend.facade import (
            models as facade_models,
            tasks as facade_tasks,
            temporal,
        )

        assert callable(facade_tasks.deactivate_stale_materializations)
        assert callable(temporal.prepare_executable_query)
        assert callable(temporal.update_materialization_ready_for_saved_query)
        assert facade_models.Endpoint is not None
        assert facade_models.EndpointVersion is not None
