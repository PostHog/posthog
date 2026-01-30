from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from rest_framework import status

from posthog.models.activity_logging.activity_log import ActivityLog

from products.endpoints.backend.models import Endpoint, EndpointVersion
from products.endpoints.backend.tests.conftest import create_endpoint_with_version


class TestEndpointVersioning(ClickhouseTestMixin, APIBaseTest):
    ENDPOINT = "endpoints"

    def setUp(self):
        super().setUp()
        self.sample_query = {
            "kind": "HogQLQuery",
            "query": "SELECT count(1) FROM query_log",
        }

    def test_create_endpoint_creates_version_1(self):
        """Initial endpoint creation should create version 1."""
        data = {
            "name": "test_endpoint",
            "query": self.sample_query,
        }

        response = self.client.post(f"/api/environments/{self.team.id}/endpoints/", data, format="json")

        self.assertEqual(status.HTTP_201_CREATED, response.status_code, response.json())
        response_data = response.json()

        self.assertEqual(1, response_data["current_version"])
        self.assertEqual(1, response_data["versions_count"])

        endpoint = Endpoint.objects.get(name="test_endpoint", team=self.team)
        self.assertEqual(1, endpoint.current_version)
        self.assertEqual(1, endpoint.versions.count())

        version = endpoint.versions.first()
        assert version is not None
        self.assertEqual(1, version.version)
        # Check key fields (Pydantic expands with defaults)
        self.assertEqual("HogQLQuery", version.query["kind"])
        self.assertEqual(self.sample_query["query"], version.query["query"])
        self.assertEqual(self.user, version.created_by)

    def test_update_query_creates_new_version(self):
        """Changing query should increment version."""
        endpoint = create_endpoint_with_version(
            name="version_test",
            team=self.team,
            query={"kind": "HogQLQuery", "query": "SELECT 1"},
            created_by=self.user,
        )

        # Update query
        new_query = {"kind": "HogQLQuery", "query": "SELECT 2"}
        response = self.client.put(
            f"/api/environments/{self.team.id}/endpoints/{endpoint.name}/",
            {"query": new_query},
            format="json",
        )

        self.assertEqual(status.HTTP_200_OK, response.status_code)
        response_data = response.json()
        self.assertEqual(2, response_data["current_version"])
        self.assertEqual(2, response_data["versions_count"])

        endpoint.refresh_from_db()
        self.assertEqual(2, endpoint.current_version)
        self.assertEqual(2, endpoint.versions.count())

        # Check version 2 has new query
        v2 = endpoint.get_version(2)
        assert v2 is not None
        self.assertEqual(new_query["query"], v2.query["query"])

        # Check version 1 still has old query
        v1 = endpoint.get_version(1)
        assert v1 is not None
        self.assertEqual("SELECT 1", v1.query["query"])

    def test_update_metadata_does_not_create_version(self):
        """Changing name/description shouldn't create new version."""
        endpoint = create_endpoint_with_version(
            name="metadata_test",
            team=self.team,
            query=self.sample_query,
            created_by=self.user,
        )

        response = self.client.put(
            f"/api/environments/{self.team.id}/endpoints/{endpoint.name}/",
            {"description": "New description", "is_active": False},
            format="json",
        )

        self.assertEqual(status.HTTP_200_OK, response.status_code)
        response_data = response.json()
        self.assertEqual(1, response_data["current_version"])
        self.assertEqual(1, response_data["versions_count"])

        endpoint.refresh_from_db()
        self.assertEqual(1, endpoint.current_version)
        self.assertEqual(1, endpoint.versions.count())

    def test_update_identical_query_does_not_create_version(self):
        """Submitting same query shouldn't create duplicate version."""
        # Create endpoint via API to ensure query goes through Pydantic expansion
        query = {"kind": "HogQLQuery", "query": "SELECT 1"}
        response = self.client.post(
            f"/api/environments/{self.team.id}/endpoints/",
            {"name": "duplicate_test", "query": query},
            format="json",
        )
        self.assertEqual(status.HTTP_201_CREATED, response.status_code)

        endpoint = Endpoint.objects.get(name="duplicate_test", team=self.team)

        # Submit same query
        response = self.client.put(
            f"/api/environments/{self.team.id}/endpoints/{endpoint.name}/",
            {"query": query},
            format="json",
        )

        self.assertEqual(status.HTTP_200_OK, response.status_code)
        endpoint.refresh_from_db()
        self.assertEqual(1, endpoint.current_version)
        self.assertEqual(1, endpoint.versions.count())

    def test_run_latest_version_by_default(self):
        """Running without version param should use latest."""
        endpoint = create_endpoint_with_version(
            name="run_test",
            team=self.team,
            query={"kind": "HogQLQuery", "query": "SELECT 1 as v1"},
            created_by=self.user,
            is_active=True,
        )

        # Create version 2
        new_query = {"kind": "HogQLQuery", "query": "SELECT 2 as v2"}
        self.client.put(
            f"/api/environments/{self.team.id}/endpoints/{endpoint.name}/",
            {"query": new_query},
            format="json",
        )

        # Run without version
        response = self.client.post(f"/api/environments/{self.team.id}/endpoints/{endpoint.name}/run/")

        self.assertEqual(status.HTTP_200_OK, response.status_code)
        response_data = response.json()
        self.assertEqual(2, response_data["endpoint_version"])
        self.assertIn("endpoint_version_created_at", response_data)

    def test_run_specific_version(self):
        """Running with version param should execute that version."""
        endpoint = create_endpoint_with_version(
            name="run_v1_test",
            team=self.team,
            query={"kind": "HogQLQuery", "query": "SELECT 1 as v1"},
            created_by=self.user,
            is_active=True,
        )

        # Create version 2
        new_query = {"kind": "HogQLQuery", "query": "SELECT 2 as v2"}
        self.client.put(
            f"/api/environments/{self.team.id}/endpoints/{endpoint.name}/",
            {"query": new_query},
            format="json",
        )

        # Run version 1 explicitly
        response = self.client.post(f"/api/environments/{self.team.id}/endpoints/{endpoint.name}/run/?version=1")

        self.assertEqual(status.HTTP_200_OK, response.status_code)
        response_data = response.json()
        self.assertEqual(1, response_data["endpoint_version"])

    def test_run_nonexistent_version_returns_404(self):
        """Running non-existent version should return 404."""
        endpoint = create_endpoint_with_version(
            name="404_test",
            team=self.team,
            query=self.sample_query,
            created_by=self.user,
            is_active=True,
        )

        response = self.client.post(f"/api/environments/{self.team.id}/endpoints/{endpoint.name}/run/?version=999")

        self.assertEqual(status.HTTP_404_NOT_FOUND, response.status_code)
        response_data = response.json()
        self.assertIn("Version 999 not found", response_data["error"])
        self.assertEqual(1, response_data["current_version"])

    def test_run_invalid_version_returns_400(self):
        """Running with invalid version param should return 400."""
        endpoint = create_endpoint_with_version(
            name="invalid_version_test",
            team=self.team,
            query=self.sample_query,
            created_by=self.user,
            is_active=True,
        )

        response = self.client.post(f"/api/environments/{self.team.id}/endpoints/{endpoint.name}/run/?version=abc")

        self.assertEqual(status.HTTP_400_BAD_REQUEST, response.status_code)
        self.assertIn("Invalid version parameter", str(response.json()))

    def test_list_versions(self):
        """Should list all versions in descending order."""
        endpoint = create_endpoint_with_version(
            name="list_versions_test",
            team=self.team,
            query={"kind": "HogQLQuery", "query": "SELECT 1"},
            created_by=self.user,
        )

        # Create versions 2 and 3
        for i in range(2, 4):
            self.client.put(
                f"/api/environments/{self.team.id}/endpoints/{endpoint.name}/",
                {"query": {"kind": "HogQLQuery", "query": f"SELECT {i}"}},
                format="json",
            )

        response = self.client.get(f"/api/environments/{self.team.id}/endpoints/{endpoint.name}/versions/")

        self.assertEqual(status.HTTP_200_OK, response.status_code)
        versions = response.json()
        self.assertEqual(3, len(versions))
        self.assertEqual(3, versions[0]["version"])
        self.assertEqual(2, versions[1]["version"])
        self.assertEqual(1, versions[2]["version"])

    def test_get_version_detail(self):
        """Should get specific version details via ?version=N query param."""
        endpoint = create_endpoint_with_version(
            name="version_detail_test",
            team=self.team,
            query={"kind": "HogQLQuery", "query": "SELECT 1"},
            created_by=self.user,
        )

        response = self.client.get(f"/api/environments/{self.team.id}/endpoints/{endpoint.name}/?version=1")

        self.assertEqual(status.HTTP_200_OK, response.status_code)
        data = response.json()
        self.assertEqual(1, data["version"])
        self.assertEqual("SELECT 1", data["query"]["query"])
        self.assertIn("created_by", data)
        self.assertIn("created_at", data)

    def test_delete_endpoint_cascades_to_versions(self):
        """Deleting endpoint should delete all versions."""
        endpoint = create_endpoint_with_version(
            name="cascade_test",
            team=self.team,
            query=self.sample_query,
            created_by=self.user,
        )

        # Create multiple versions
        for i in range(2, 5):
            self.client.put(
                f"/api/environments/{self.team.id}/endpoints/{endpoint.name}/",
                {"query": {"kind": "HogQLQuery", "query": f"SELECT {i}"}},
                format="json",
            )

        endpoint_id = endpoint.id
        self.assertEqual(4, EndpointVersion.objects.filter(endpoint_id=endpoint_id).count())

        # Delete endpoint
        response = self.client.delete(f"/api/environments/{self.team.id}/endpoints/{endpoint.name}/")
        self.assertIn(response.status_code, [status.HTTP_204_NO_CONTENT, status.HTTP_200_OK])

        # Versions should be deleted too (CASCADE)
        self.assertEqual(0, EndpointVersion.objects.filter(endpoint_id=endpoint_id).count())

    def test_version_query_immutability(self):
        """Version queries should be immutable."""
        endpoint = create_endpoint_with_version(
            name="immutable_test",
            team=self.team,
            query={"kind": "HogQLQuery", "query": "SELECT 1"},
            created_by=self.user,
        )

        v1 = endpoint.get_version(1)
        assert v1 is not None
        original_query = v1.query.copy()

        # Update endpoint to create v2
        self.client.put(
            f"/api/environments/{self.team.id}/endpoints/{endpoint.name}/",
            {"query": {"kind": "HogQLQuery", "query": "SELECT 2"}},
            format="json",
        )

        # v1 query should be unchanged
        v1.refresh_from_db()
        self.assertEqual(original_query, v1.query)

    def test_activity_log_tracks_version_creation(self):
        """Activity log should record version changes."""
        endpoint = create_endpoint_with_version(
            name="activity_test",
            team=self.team,
            query={"kind": "HogQLQuery", "query": "SELECT 1"},
            created_by=self.user,
        )

        # Update to create v2
        self.client.put(
            f"/api/environments/{self.team.id}/endpoints/{endpoint.name}/",
            {"query": {"kind": "HogQLQuery", "query": "SELECT 2"}},
            format="json",
        )

        logs = ActivityLog.objects.filter(
            scope="Endpoint",
            item_id=str(endpoint.id),
            activity="updated",
        )

        self.assertEqual(1, logs.count())

    def test_materialization_transfer_on_version_update(self):
        """When query changes on materialized endpoint, new version gets materialization and old version keeps its own."""
        from datetime import timedelta

        from unittest.mock import patch

        from products.data_warehouse.backend.models import DataWarehouseSavedQuery

        initial_query = {"kind": "HogQLQuery", "query": "SELECT * FROM events LIMIT 10"}

        # Create endpoint with a query that references a table
        endpoint = Endpoint.objects.create(
            name="materialized_test",
            team=self.team,
            created_by=self.user,
            current_version=1,
        )
        version1 = EndpointVersion.objects.create(
            endpoint=endpoint,
            version=1,
            query=initial_query,
            created_by=self.user,
        )

        # Create initial saved query (simulating materialization) on the version
        old_saved_query = DataWarehouseSavedQuery.objects.create(
            name=f"{endpoint.name}_v1",
            team=self.team,
            query=initial_query,
            is_materialized=True,
            sync_frequency_interval=timedelta(hours=24),
            origin=DataWarehouseSavedQuery.Origin.ENDPOINT,
        )
        version1.saved_query = old_saved_query
        version1.is_materialized = True
        version1.save()

        old_saved_query_id = old_saved_query.id

        # Mock Temporal-related functions to avoid connection errors
        with (
            patch("products.data_warehouse.backend.data_load.saved_query_service.sync_saved_query_workflow"),
            patch(
                "products.data_warehouse.backend.data_load.saved_query_service.saved_query_workflow_exists",
                return_value=False,
            ),
            patch("products.data_warehouse.backend.data_load.saved_query_service.delete_saved_query_schedule"),
        ):
            # Update query (which should create new version with its own materialization)
            new_query = {"kind": "HogQLQuery", "query": "SELECT * FROM events WHERE timestamp > now() - INTERVAL 1 DAY"}
            response = self.client.put(
                f"/api/environments/{self.team.id}/endpoints/{endpoint.name}/",
                {"query": new_query},
                format="json",
            )

            self.assertEqual(status.HTTP_200_OK, response.status_code, response.json())

        endpoint.refresh_from_db()

        # Verify version was incremented
        self.assertEqual(2, endpoint.current_version)
        self.assertEqual(2, endpoint.versions.count())

        # Verify new saved query was created on the new version
        new_version = endpoint.get_version()
        assert new_version is not None
        assert new_version.saved_query is not None
        self.assertNotEqual(new_version.saved_query.id, old_saved_query_id)

        # Verify new saved query has correct properties
        new_saved_query = new_version.saved_query
        assert new_saved_query is not None
        self.assertTrue(new_saved_query.is_materialized)
        self.assertEqual(new_saved_query.sync_frequency_interval, timedelta(hours=24))

        # Verify new saved query has the NEW query (not the old one)
        assert new_saved_query.query is not None
        self.assertEqual(new_saved_query.query["query"], new_query["query"])

        # Verify old version still has its materialization (not deleted)
        version1.refresh_from_db()
        old_saved_query.refresh_from_db()
        self.assertTrue(version1.is_materialized)
        self.assertFalse(old_saved_query.deleted)
        self.assertEqual(version1.saved_query_id, old_saved_query_id)

    def test_no_materialization_transfer_for_non_materialized_endpoint(self):
        """Non-materialized endpoints should not trigger materialization transfer."""
        # Create non-materialized endpoint using helper
        initial_query = {"kind": "HogQLQuery", "query": "SELECT 1"}
        endpoint = create_endpoint_with_version(
            name="non_materialized_test",
            team=self.team,
            query=initial_query,
            created_by=self.user,
        )
        version = endpoint.get_version()

        # Ensure no saved query on version
        self.assertIsNone(version.saved_query)

        # Update query
        new_query = {"kind": "HogQLQuery", "query": "SELECT 2"}
        response = self.client.put(
            f"/api/environments/{self.team.id}/endpoints/{endpoint.name}/",
            {"query": new_query},
            format="json",
        )

        self.assertEqual(status.HTTP_200_OK, response.status_code)

        endpoint.refresh_from_db()

        # Verify version was incremented but no saved query was created on new version
        self.assertEqual(2, endpoint.current_version)
        new_version = endpoint.get_version()
        self.assertIsNone(new_version.saved_query)

    def test_version_activate_deactivate(self):
        """Version can be activated and deactivated via update endpoint with version param."""
        endpoint = create_endpoint_with_version(
            name="version_activation_test",
            team=self.team,
            query=self.sample_query,
            created_by=self.user,
        )

        # Version should be active by default
        version = endpoint.get_version()
        self.assertTrue(version.is_active)

        # Deactivate version via update endpoint with version param
        response = self.client.put(
            f"/api/environments/{self.team.id}/endpoints/{endpoint.name}/?version=1",
            {"is_active": False},
            format="json",
        )
        self.assertEqual(status.HTTP_200_OK, response.status_code)
        self.assertFalse(response.json()["is_active"])

        version.refresh_from_db()
        self.assertFalse(version.is_active)

        # Reactivate version via update endpoint
        response = self.client.put(
            f"/api/environments/{self.team.id}/endpoints/{endpoint.name}/?version=1",
            {"is_active": True},
            format="json",
        )
        self.assertEqual(status.HTTP_200_OK, response.status_code)
        self.assertTrue(response.json()["is_active"])

        version.refresh_from_db()
        self.assertTrue(version.is_active)

    def test_endpoint_deactivate(self):
        endpoint = create_endpoint_with_version(
            name="endpoint_activation_test",
            team=self.team,
            query=self.sample_query,
            created_by=self.user,
        )
        endpoint.create_new_version(endpoint.get_version().query, self.user)
        version1 = endpoint.get_version(1)
        version2 = endpoint.get_version(2)

        self.assertTrue(version1.is_active)
        self.assertTrue(version2.is_active)

        response = self.client.put(
            f"/api/environments/{self.team.id}/endpoints/{endpoint.name}",
            {"is_active": False},
            format="json",
        )
        self.assertEqual(status.HTTP_200_OK, response.status_code)

        response_v2 = self.client.post(f"/api/environments/{self.team.id}/endpoints/{endpoint.name}/run/")
        self.assertEqual(status.HTTP_404_NOT_FOUND, response_v2.status_code)
        response_v1 = self.client.post(f"/api/environments/{self.team.id}/endpoints/{endpoint.name}/run/?version=1")
        self.assertEqual(status.HTTP_404_NOT_FOUND, response_v1.status_code)

    def test_version_deactivate_keeps_endpoint_activated(self):
        endpoint = create_endpoint_with_version(
            name="endpoint_activation_test",
            team=self.team,
            query=self.sample_query,
            created_by=self.user,
        )
        endpoint.create_new_version(endpoint.get_version().query, self.user)
        version1 = endpoint.get_version(1)
        version2 = endpoint.get_version(2)

        self.assertTrue(version1.is_active)
        self.assertTrue(version2.is_active)

        response = self.client.put(
            f"/api/environments/{self.team.id}/endpoints/{endpoint.name}/?version=1",
            {"is_active": False},
            format="json",
        )
        self.assertEqual(status.HTTP_200_OK, response.status_code)

        response_v2 = self.client.post(f"/api/environments/{self.team.id}/endpoints/{endpoint.name}/run/")
        self.assertEqual(status.HTTP_200_OK, response_v2.status_code)
        response_v1 = self.client.post(f"/api/environments/{self.team.id}/endpoints/{endpoint.name}/run/?version=1")
        self.assertEqual(status.HTTP_400_BAD_REQUEST, response_v1.status_code)

    def test_inactive_version_cannot_be_executed(self):
        """Inactive versions should not be executable."""
        endpoint = create_endpoint_with_version(
            name="inactive_run_test",
            team=self.team,
            query=self.sample_query,
            created_by=self.user,
            is_active=True,
        )

        # Deactivate version
        version = endpoint.get_version()
        version.is_active = False
        version.save()

        # Try to run the endpoint
        response = self.client.post(f"/api/environments/{self.team.id}/endpoints/{endpoint.name}/run/")

        self.assertEqual(status.HTTP_400_BAD_REQUEST, response.status_code)
        self.assertIn("inactive", response.json()["detail"].lower())

    def test_list_versions_includes_is_active(self):
        """Versions list should include is_active field."""
        endpoint = create_endpoint_with_version(
            name="list_with_active",
            team=self.team,
            query=self.sample_query,
            created_by=self.user,
        )

        response = self.client.get(f"/api/environments/{self.team.id}/endpoints/{endpoint.name}/versions/")

        self.assertEqual(status.HTTP_200_OK, response.status_code)
        versions = response.json()
        self.assertEqual(1, len(versions))
        self.assertIn("is_active", versions[0])
        self.assertTrue(versions[0]["is_active"])

    def test_per_version_materialization_uses_versioned_naming(self):
        """Each version should have its own independently-named saved_query."""
        from unittest.mock import patch

        from products.data_warehouse.backend.models import DataWarehouseSavedQuery

        initial_query = {"kind": "HogQLQuery", "query": "SELECT 1"}
        endpoint = create_endpoint_with_version(
            name="versioned_mat",
            team=self.team,
            query=initial_query,
            created_by=self.user,
        )

        # Mock sync workflow
        with patch("products.data_warehouse.backend.data_load.saved_query_service.sync_saved_query_workflow"):
            # Enable materialization on v1
            response = self.client.put(
                f"/api/environments/{self.team.id}/endpoints/{endpoint.name}/",
                {"is_materialized": True, "sync_frequency": "24hour"},
                format="json",
            )
            self.assertEqual(status.HTTP_200_OK, response.status_code, response.json())

        v1 = endpoint.get_version(1)
        self.assertIsNotNone(v1.saved_query)
        # Saved query should use versioned naming: {endpoint_name}_v{version}
        self.assertEqual(v1.saved_query.name, "versioned_mat_v1")

        # Create v2 by changing query
        with patch("products.data_warehouse.backend.data_load.saved_query_service.sync_saved_query_workflow"):
            response = self.client.put(
                f"/api/environments/{self.team.id}/endpoints/{endpoint.name}/",
                {"query": {"kind": "HogQLQuery", "query": "SELECT 2"}},
                format="json",
            )
            self.assertEqual(status.HTTP_200_OK, response.status_code, response.json())

        endpoint.refresh_from_db()
        v2 = endpoint.get_version(2)
        self.assertIsNotNone(v2.saved_query)
        # New version should have its own versioned saved_query name
        self.assertEqual(v2.saved_query.name, "versioned_mat_v2")

        # Both saved_queries should exist independently (v1 keeps its materialization)
        self.assertEqual(
            DataWarehouseSavedQuery.objects.filter(name__startswith="versioned_mat_v", deleted=False).count(),
            2,
        )

    def test_update_with_version_param_enables_materialization_on_specific_version(self):
        """Update with ?version=N should enable materialization on that specific version."""
        from unittest.mock import patch

        # Create endpoint with v1
        initial_query = {"kind": "HogQLQuery", "query": "SELECT 1"}
        endpoint = create_endpoint_with_version(
            name="target_version_mat",
            team=self.team,
            query=initial_query,
            created_by=self.user,
        )

        # Create v2 by changing query
        response = self.client.put(
            f"/api/environments/{self.team.id}/endpoints/{endpoint.name}/",
            {"query": {"kind": "HogQLQuery", "query": "SELECT 2"}},
            format="json",
        )
        self.assertEqual(status.HTTP_200_OK, response.status_code)

        endpoint.refresh_from_db()
        self.assertEqual(2, endpoint.current_version)

        # Neither version should be materialized yet
        v1 = endpoint.get_version(1)
        v2 = endpoint.get_version(2)
        self.assertFalse(v1.is_materialized)
        self.assertFalse(v2.is_materialized)

        # Enable materialization on v1 specifically (not the current version)
        with patch("products.data_warehouse.backend.data_load.saved_query_service.sync_saved_query_workflow"):
            response = self.client.put(
                f"/api/environments/{self.team.id}/endpoints/{endpoint.name}/?version=1",
                {"is_materialized": True, "sync_frequency": "24hour"},
                format="json",
            )
            self.assertEqual(status.HTTP_200_OK, response.status_code, response.json())

        # Refresh versions
        v1.refresh_from_db()
        v2.refresh_from_db()

        # v1 should now be materialized
        self.assertTrue(v1.is_materialized)
        self.assertIsNotNone(v1.saved_query)
        self.assertEqual(v1.saved_query.name, "target_version_mat_v1")

        # v2 should still NOT be materialized
        self.assertFalse(v2.is_materialized)
        self.assertIsNone(v2.saved_query)

    def test_update_with_version_param_disables_materialization_on_specific_version(self):
        """Update with ?version=N should disable materialization on that specific version."""

        from datetime import timedelta

        from products.data_warehouse.backend.models import DataWarehouseSavedQuery

        # Create endpoint with v1
        initial_query = {"kind": "HogQLQuery", "query": "SELECT 1"}
        endpoint = create_endpoint_with_version(
            name="disable_v1_mat",
            team=self.team,
            query=initial_query,
            created_by=self.user,
        )

        # Manually set up materialization on v1
        v1 = endpoint.get_version(1)
        saved_query = DataWarehouseSavedQuery.objects.create(
            name="disable_v1_mat_v1",
            team=self.team,
            query=initial_query,
            is_materialized=True,
            sync_frequency_interval=timedelta(hours=24),
            origin=DataWarehouseSavedQuery.Origin.ENDPOINT,
        )
        v1.saved_query = saved_query
        v1.is_materialized = True
        v1.sync_frequency = "24hour"
        v1.save()

        # Create v2 by changing query
        response = self.client.put(
            f"/api/environments/{self.team.id}/endpoints/{endpoint.name}/",
            {"query": {"kind": "HogQLQuery", "query": "SELECT 2"}},
            format="json",
        )
        self.assertEqual(status.HTTP_200_OK, response.status_code)

        endpoint.refresh_from_db()
        self.assertEqual(2, endpoint.current_version)

        # Disable materialization on v1 specifically
        response = self.client.put(
            f"/api/environments/{self.team.id}/endpoints/{endpoint.name}/?version=1",
            {"is_materialized": False},
            format="json",
        )
        self.assertEqual(status.HTTP_200_OK, response.status_code, response.json())

        # Refresh v1
        v1.refresh_from_db()

        # v1 should no longer be materialized
        self.assertFalse(v1.is_materialized)
        self.assertIsNone(v1.saved_query)

        # Saved query should be soft-deleted
        saved_query.refresh_from_db()
        self.assertTrue(saved_query.deleted)

    def test_update_with_version_param_updates_description_on_specific_version(self):
        """Update with ?version=N should update description on that specific version."""
        # Create endpoint with v1
        initial_query = {"kind": "HogQLQuery", "query": "SELECT 1"}
        endpoint = create_endpoint_with_version(
            name="desc_v1_update",
            team=self.team,
            query=initial_query,
            created_by=self.user,
        )

        # Create v2 by changing query
        response = self.client.put(
            f"/api/environments/{self.team.id}/endpoints/{endpoint.name}/",
            {"query": {"kind": "HogQLQuery", "query": "SELECT 2"}},
            format="json",
        )
        self.assertEqual(status.HTTP_200_OK, response.status_code)

        endpoint.refresh_from_db()
        self.assertEqual(2, endpoint.current_version)

        # Update description on v1 specifically
        response = self.client.put(
            f"/api/environments/{self.team.id}/endpoints/{endpoint.name}/?version=1",
            {"description": "v1 description"},
            format="json",
        )
        self.assertEqual(status.HTTP_200_OK, response.status_code)

        # Verify v1 has the description
        v1 = endpoint.get_version(1)
        v2 = endpoint.get_version(2)
        self.assertEqual("v1 description", v1.description)
        # v2 should NOT have been updated
        self.assertNotEqual("v1 description", v2.description)

    def test_update_with_invalid_version_param_returns_error(self):
        """Update with ?version=N where N doesn't exist should return error."""
        initial_query = {"kind": "HogQLQuery", "query": "SELECT 1"}
        endpoint = create_endpoint_with_version(
            name="invalid_version_update",
            team=self.team,
            query=initial_query,
            created_by=self.user,
        )

        # Try to update with non-existent version
        response = self.client.put(
            f"/api/environments/{self.team.id}/endpoints/{endpoint.name}/?version=999",
            {"is_materialized": True},
            format="json",
        )

        self.assertEqual(status.HTTP_400_BAD_REQUEST, response.status_code)
        self.assertIn("999", str(response.json()))

    def test_update_rejects_query_change_with_version_param(self):
        """Cannot change query when targeting a specific version."""
        initial_query = {"kind": "HogQLQuery", "query": "SELECT 1"}
        endpoint = create_endpoint_with_version(
            name="query_change_rejection",
            team=self.team,
            query=initial_query,
            created_by=self.user,
        )

        response = self.client.put(
            f"/api/environments/{self.team.id}/endpoints/{endpoint.name}/?version=1",
            {"query": {"kind": "HogQLQuery", "query": "SELECT 2"}},
            format="json",
        )

        self.assertEqual(status.HTTP_400_BAD_REQUEST, response.status_code)
        self.assertIn("Cannot change query", str(response.json()))
