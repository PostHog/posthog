from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from rest_framework import status

from posthog.models.activity_logging.activity_log import ActivityLog

from products.endpoints.backend.models import Endpoint, EndpointVersion


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
        endpoint = Endpoint.objects.create(
            name="version_test",
            team=self.team,
            query={"kind": "HogQLQuery", "query": "SELECT 1"},
            created_by=self.user,
            current_version=1,
        )
        EndpointVersion.objects.create(
            endpoint=endpoint,
            version=1,
            query=endpoint.query,
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
        self.assertEqual(new_query["query"], v2.query["query"])

        # Check version 1 still has old query
        v1 = endpoint.get_version(1)
        self.assertEqual("SELECT 1", v1.query["query"])

    def test_update_metadata_does_not_create_version(self):
        """Changing name/description shouldn't create new version."""
        endpoint = Endpoint.objects.create(
            name="metadata_test",
            team=self.team,
            query=self.sample_query,
            created_by=self.user,
            current_version=1,
        )
        EndpointVersion.objects.create(
            endpoint=endpoint,
            version=1,
            query=endpoint.query,
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
        endpoint = Endpoint.objects.create(
            name="run_test",
            team=self.team,
            query={"kind": "HogQLQuery", "query": "SELECT 1 as v1"},
            created_by=self.user,
            is_active=True,
            current_version=1,
        )
        EndpointVersion.objects.create(
            endpoint=endpoint,
            version=1,
            query=endpoint.query,
            created_by=self.user,
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
        self.assertEqual(2, response_data["_version"])
        self.assertIn("_version_created_at", response_data)

    def test_run_specific_version(self):
        """Running with version param should execute that version."""
        endpoint = Endpoint.objects.create(
            name="run_v1_test",
            team=self.team,
            query={"kind": "HogQLQuery", "query": "SELECT 1 as v1"},
            created_by=self.user,
            is_active=True,
            current_version=1,
        )
        EndpointVersion.objects.create(
            endpoint=endpoint,
            version=1,
            query=endpoint.query,
            created_by=self.user,
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
        self.assertEqual(1, response_data["_version"])

    def test_run_nonexistent_version_returns_404(self):
        """Running non-existent version should return 404."""
        endpoint = Endpoint.objects.create(
            name="404_test",
            team=self.team,
            query=self.sample_query,
            created_by=self.user,
            is_active=True,
            current_version=1,
        )
        EndpointVersion.objects.create(
            endpoint=endpoint,
            version=1,
            query=endpoint.query,
            created_by=self.user,
        )

        response = self.client.post(f"/api/environments/{self.team.id}/endpoints/{endpoint.name}/run/?version=999")

        self.assertEqual(status.HTTP_404_NOT_FOUND, response.status_code)
        response_data = response.json()
        self.assertIn("Version 999 not found", response_data["error"])
        self.assertEqual(1, response_data["current_version"])

    def test_run_invalid_version_returns_400(self):
        """Running with invalid version param should return 400."""
        endpoint = Endpoint.objects.create(
            name="invalid_version_test",
            team=self.team,
            query=self.sample_query,
            created_by=self.user,
            is_active=True,
            current_version=1,
        )
        EndpointVersion.objects.create(
            endpoint=endpoint,
            version=1,
            query=endpoint.query,
            created_by=self.user,
        )

        response = self.client.post(f"/api/environments/{self.team.id}/endpoints/{endpoint.name}/run/?version=abc")

        self.assertEqual(status.HTTP_400_BAD_REQUEST, response.status_code)
        response_data = response.json()
        self.assertIn("Invalid version parameter", response_data["error"])

    def test_list_versions(self):
        """Should list all versions in descending order."""
        endpoint = Endpoint.objects.create(
            name="list_versions_test",
            team=self.team,
            query={"kind": "HogQLQuery", "query": "SELECT 1"},
            created_by=self.user,
            current_version=1,
        )
        EndpointVersion.objects.create(
            endpoint=endpoint,
            version=1,
            query=endpoint.query,
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
        """Should get specific version details."""
        endpoint = Endpoint.objects.create(
            name="version_detail_test",
            team=self.team,
            query={"kind": "HogQLQuery", "query": "SELECT 1"},
            created_by=self.user,
            current_version=1,
        )
        EndpointVersion.objects.create(
            endpoint=endpoint,
            version=1,
            query=endpoint.query,
            created_by=self.user,
        )

        response = self.client.get(f"/api/environments/{self.team.id}/endpoints/{endpoint.name}/versions/1/")

        self.assertEqual(status.HTTP_200_OK, response.status_code)
        data = response.json()
        self.assertEqual(1, data["version"])
        self.assertEqual("SELECT 1", data["query"]["query"])
        self.assertIn("created_by", data)
        self.assertIn("created_at", data)

    def test_delete_endpoint_cascades_to_versions(self):
        """Deleting endpoint should delete all versions."""
        endpoint = Endpoint.objects.create(
            name="cascade_test",
            team=self.team,
            query=self.sample_query,
            created_by=self.user,
            current_version=1,
        )
        EndpointVersion.objects.create(
            endpoint=endpoint,
            version=1,
            query=endpoint.query,
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
        endpoint = Endpoint.objects.create(
            name="immutable_test",
            team=self.team,
            query={"kind": "HogQLQuery", "query": "SELECT 1"},
            created_by=self.user,
            current_version=1,
        )
        EndpointVersion.objects.create(
            endpoint=endpoint,
            version=1,
            query=endpoint.query,
            created_by=self.user,
        )

        v1 = endpoint.get_version(1)
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
        endpoint = Endpoint.objects.create(
            name="activity_test",
            team=self.team,
            query={"kind": "HogQLQuery", "query": "SELECT 1"},
            created_by=self.user,
            current_version=1,
        )
        EndpointVersion.objects.create(
            endpoint=endpoint,
            version=1,
            query=endpoint.query,
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
        """When query changes on materialized endpoint, materialization should transfer to new version."""
        from datetime import timedelta

        from unittest.mock import patch

        from products.data_warehouse.backend.models import DataWarehouseSavedQuery

        # Create endpoint with a query that references a table
        endpoint = Endpoint.objects.create(
            name="materialized_test",
            team=self.team,
            query={"kind": "HogQLQuery", "query": "SELECT * FROM events LIMIT 10"},
            created_by=self.user,
            current_version=1,
        )
        EndpointVersion.objects.create(
            endpoint=endpoint,
            version=1,
            query=endpoint.query,
            created_by=self.user,
        )

        # Create initial saved query (simulating materialization)
        old_saved_query = DataWarehouseSavedQuery.objects.create(
            name=endpoint.name,
            team=self.team,
            query=endpoint.query,
            is_materialized=True,
            sync_frequency_interval=timedelta(hours=24),
            origin=DataWarehouseSavedQuery.Origin.ENDPOINT,
        )
        endpoint.saved_query = old_saved_query
        endpoint.save()

        old_saved_query_id = old_saved_query.id

        # Mock the sync workflow to avoid triggering actual workflow
        with patch("products.data_warehouse.backend.api.saved_query.sync_saved_query_workflow"):
            # Update query (which should create new version and transfer materialization)
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

        # Verify new saved query was created
        self.assertIsNotNone(endpoint.saved_query)
        self.assertNotEqual(endpoint.saved_query.id, old_saved_query_id)

        # Verify new saved query has correct properties
        new_saved_query = endpoint.saved_query
        self.assertTrue(new_saved_query.is_materialized)
        self.assertEqual(new_saved_query.sync_frequency_interval, timedelta(hours=24))

        # Verify new saved query has the NEW query (not the old one)
        self.assertEqual(new_saved_query.query["query"], new_query["query"])

        # Verify old saved query was soft deleted
        old_saved_query.refresh_from_db()
        self.assertTrue(old_saved_query.deleted)

    def test_no_materialization_transfer_for_non_materialized_endpoint(self):
        """Non-materialized endpoints should not trigger materialization transfer."""
        # Create non-materialized endpoint
        endpoint = Endpoint.objects.create(
            name="non_materialized_test",
            team=self.team,
            query={"kind": "HogQLQuery", "query": "SELECT 1"},
            created_by=self.user,
            current_version=1,
        )
        EndpointVersion.objects.create(
            endpoint=endpoint,
            version=1,
            query=endpoint.query,
            created_by=self.user,
        )

        # Ensure no saved query
        self.assertIsNone(endpoint.saved_query)

        # Update query
        new_query = {"kind": "HogQLQuery", "query": "SELECT 2"}
        response = self.client.put(
            f"/api/environments/{self.team.id}/endpoints/{endpoint.name}/",
            {"query": new_query},
            format="json",
        )

        self.assertEqual(status.HTTP_200_OK, response.status_code)

        endpoint.refresh_from_db()

        # Verify version was incremented but no saved query was created
        self.assertEqual(2, endpoint.current_version)
        self.assertIsNone(endpoint.saved_query)
