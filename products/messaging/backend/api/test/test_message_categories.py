from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.core.files.uploadedfile import SimpleUploadedFile

from rest_framework import status

from posthog.models import Team
from posthog.models.integration import Integration

from products.messaging.backend.models.message_category import MessageCategory
from products.messaging.backend.models.optout_sync_config import OptOutSyncConfig


class TestMessageCategoryAPI(APIBaseTest):
    def test_list_messaging_categories_for_team(self):
        """
        Tests that GET /messaging_categories only retrieves categories for the current team.
        """
        # Category for the current team
        MessageCategory.objects.create(team=self.team, name="Team 1 Category", key="team1_cat")

        # Category for another team
        other_team = Team.objects.create(organization=self.organization)
        MessageCategory.objects.create(team=other_team, name="Team 2 Category", key="team2_cat")

        response = self.client.get(f"/api/environments/{self.team.id}/messaging_categories/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()
        self.assertEqual(len(response_data["results"]), 1)
        self.assertEqual(response_data["results"][0]["name"], "Team 1 Category")

    def test_get_message_category(self):
        """
        Tests GET /messaging_categories/:id works as expected.
        """
        category = MessageCategory.objects.create(team=self.team, name="My Category", key="my_cat")
        response = self.client.get(f"/api/environments/{self.team.id}/messaging_categories/{category.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["name"], "My Category")

        # Test getting a category from another team
        other_team = Team.objects.create(organization=self.organization)
        other_category = MessageCategory.objects.create(team=other_team, name="Other Category", key="other_cat")
        response = self.client.get(f"/api/environments/{self.team.id}/messaging_categories/{other_category.id}/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_update_message_category(self):
        """
        Tests PUT and PATCH /messaging_categories/:id work as expected.
        """
        category = MessageCategory.objects.create(team=self.team, name="Initial Name", key="initial_key")

        # PATCH
        patch_response = self.client.patch(
            f"/api/environments/{self.team.id}/messaging_categories/{category.id}/", {"name": "Patched Name"}
        )
        self.assertEqual(patch_response.status_code, status.HTTP_200_OK)
        category.refresh_from_db()
        self.assertEqual(category.name, "Patched Name")

        # PUT
        put_response = self.client.put(
            f"/api/environments/{self.team.id}/messaging_categories/{category.id}/",
            {"name": "Put Name", "key": "initial_key", "category_type": "marketing"},
        )
        self.assertEqual(put_response.status_code, status.HTTP_200_OK)
        category.refresh_from_db()
        self.assertEqual(category.name, "Put Name")

        # Test PATCH without key field - should work
        patch_no_key_response = self.client.patch(
            f"/api/environments/{self.team.id}/messaging_categories/{category.id}/", {"name": "Patched Without Key"}
        )
        self.assertEqual(patch_no_key_response.status_code, status.HTTP_200_OK)
        category.refresh_from_db()
        self.assertEqual(category.name, "Patched Without Key")
        self.assertEqual(category.key, "initial_key")  # Key should remain unchanged

    def test_cannot_update_key_field(self):
        """
        Tests that attempting to update the key field via PUT or PATCH succeeds but the key remains unchanged.
        """
        category = MessageCategory.objects.create(team=self.team, name="Test Category", key="original_key")

        # Attempt to change key via PATCH
        patch_response = self.client.patch(
            f"/api/environments/{self.team.id}/messaging_categories/{category.id}/",
            {"name": "Updated Name", "key": "new_key"},
        )
        # The request should fail and the key should not change
        self.assertEqual(patch_response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("The key field cannot be updated after creation.", str(patch_response.json()))
        category.refresh_from_db()
        self.assertEqual(category.name, "Test Category")
        self.assertEqual(category.key, "original_key")

        # Attempt to change key via PUT
        put_response = self.client.put(
            f"/api/environments/{self.team.id}/messaging_categories/{category.id}/",
            {"name": "Put Updated Name", "key": "another_new_key", "category_type": "marketing"},
        )
        # The request should fail and the key should not change
        self.assertEqual(put_response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("The key field cannot be updated after creation.", str(put_response.json()))
        category.refresh_from_db()
        self.assertEqual(category.name, "Test Category")
        self.assertEqual(category.key, "original_key")

    def test_create_message_category(self):
        """
        Tests that creating a category automatically sets team_id and created_by.
        """
        response = self.client.post(
            f"/api/environments/{self.team.id}/messaging_categories/",
            {"name": "New Category", "key": "new_cat", "category_type": "marketing"},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        response_data = response.json()
        category = MessageCategory.objects.get(id=response_data["id"])
        self.assertEqual(category.team, self.team)
        self.assertEqual(category.created_by, self.user)
        self.assertEqual(category.name, "New Category")

    def test_cant_create_category_with_duplicate_key(self):
        """
        Tests that creating a category with a duplicate key for the same team is not allowed,
        but it is allowed for a different team.
        """
        MessageCategory.objects.create(team=self.team, name="Category 1", key="duplicate-key")

        # Attempt to create with the same key for the same team
        response = self.client.post(
            f"/api/environments/{self.team.id}/messaging_categories/",
            {"name": "Category 2", "key": "duplicate-key", "category_type": "marketing"},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual("key", response.json()["attr"])
        self.assertIn("already exists", response.json()["detail"])

        # Verify it's possible to create with the same key for a different team
        other_team = Team.objects.create(organization=self.organization)
        response = self.client.post(
            f"/api/environments/{other_team.id}/messaging_categories/",
            {"name": "Category 3", "key": "duplicate-key", "category_type": "marketing"},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_delete_is_forbidden(self):
        """
        Tests that DELETE /messaging_categories/:id is forbidden.
        """
        category = MessageCategory.objects.create(team=self.team, name="To Delete", key="to_delete")
        response = self.client.delete(f"/api/environments/{self.team.id}/messaging_categories/{category.id}/")
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    def test_import_preferences_csv_missing_file(self):
        """Test CSV import fails when file is missing"""
        response = self.client.post(
            f"/api/environments/{self.team.id}/messaging_categories/import_preferences_csv/",
            {},
            format="multipart",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("No file provided", response.json()["error"])

    def test_import_preferences_csv_wrong_file_type(self):
        """Test CSV import rejects non-CSV files"""
        # Try to upload a text file
        txt_file = SimpleUploadedFile(
            "test.txt",
            b"This is not a CSV file",
            content_type="text/plain",
        )

        response = self.client.post(
            f"/api/environments/{self.team.id}/messaging_categories/import_preferences_csv/",
            {"csv_file": txt_file},
            format="multipart",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("File must be a CSV", response.json()["error"])

    def test_import_preferences_csv_large_file(self):
        """Test CSV import handles large files"""
        # Create a large CSV (over 10MB limit)
        large_content = b"email,id,cio_subscription_preferences\n"
        row = b'user@example.com,1,"{""topics"": {""1"": false}}"\n'
        # Create ~11MB file
        large_content += row * 300000

        csv_file = SimpleUploadedFile(
            "large.csv",
            large_content,
            content_type="text/csv",
        )

        response = self.client.post(
            f"/api/environments/{self.team.id}/messaging_categories/import_preferences_csv/",
            {"csv_file": csv_file},
            format="multipart",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("File too large", response.json()["error"])

    def test_import_preferences_csv_without_categories(self):
        """Test CSV import when no categories exist"""
        with patch("products.messaging.backend.api.message_categories.CustomerIOImportService") as mock_service_class:
            mock_service = MagicMock()
            mock_service_class.return_value = mock_service
            mock_service.process_preferences_csv.return_value = {
                "status": "failed",
                "details": "No categories found. Please run API import first.",
            }

            csv_file = SimpleUploadedFile(
                "test.csv",
                b'email,id,cio_subscription_preferences\nuser@example.com,1,"{}"',
                content_type="text/csv",
            )

            response = self.client.post(
                f"/api/environments/{self.team.id}/messaging_categories/import_preferences_csv/",
                {"csv_file": csv_file},
                format="multipart",
            )

            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(response.json()["status"], "failed")
            self.assertIn("No categories found", response.json()["details"])

    def test_import_endpoints_require_authentication(self):
        """Test that import endpoints require authentication"""
        self.client.logout()

        # Test API import endpoint
        response = self.client.post(
            f"/api/environments/{self.team.id}/messaging_categories/import_from_customerio/",
            {"app_api_key": "test_key"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

        # Test CSV import endpoint
        csv_file = SimpleUploadedFile(
            "test.csv",
            b"test",
            content_type="text/csv",
        )
        response = self.client.post(
            f"/api/environments/{self.team.id}/messaging_categories/import_preferences_csv/",
            {"csv_file": csv_file},
            format="multipart",
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class TestOptOutSyncConfigAPI(APIBaseTest):
    def setUp(self):
        super().setUp()
        OptOutSyncConfig.objects.filter(team=self.team).delete()
        Integration.objects.filter(team=self.team, kind="customerio-app").delete()

    def _url(self, action: str) -> str:
        return f"/api/environments/{self.team.id}/messaging_categories/{action}/"

    def test_optout_sync_config_returns_defaults_when_no_config_exists(self):
        response = self.client.get(self._url("optout_sync_config"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.json(),
            {
                "app_integration_id": None,
                "app_import_result": None,
                "csv_import_result": None,
                "webhook_enabled": False,
                "has_webhook_secret": False,
            },
        )

    def test_optout_sync_config_returns_stored_state(self):
        integration = Integration.objects.create(
            team=self.team,
            kind="customerio-app",
            sensitive_config={"app_api_key": "test_key"},
            created_by=self.user,
        )
        OptOutSyncConfig.objects.create(
            team=self.team,
            app_integration=integration,
            app_import_result={
                "status": "completed",
                "imported_at": "2026-04-13T10:00:00Z",
                "categories_created": 6,
                "globally_unsubscribed_count": 42,
            },
        )

        response = self.client.get(self._url("optout_sync_config"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data["app_integration_id"], integration.id)
        self.assertEqual(data["app_import_result"]["status"], "completed")
        self.assertEqual(data["app_import_result"]["categories_created"], 6)
        self.assertIsNone(data["csv_import_result"])

    @patch("products.messaging.backend.api.message_categories.CustomerIOImportService")
    def test_import_from_customerio_stores_integration_and_result(self, mock_service_class):
        mock_service = MagicMock()
        mock_service_class.return_value = mock_service
        mock_service.import_api_data.return_value = {
            "status": "completed",
            "categories_created": 3,
            "globally_unsubscribed_count": 10,
            "topics_found": 3,
            "errors": [],
        }

        response = self.client.post(
            self._url("import_from_customerio"),
            {"app_api_key": "my_secret_key"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["status"], "completed")

        integration = Integration.objects.get(team=self.team, kind="customerio-app")
        self.assertEqual(integration.sensitive_config["app_api_key"], "my_secret_key")

        config = OptOutSyncConfig.objects.get(team=self.team)
        self.assertEqual(config.app_integration, integration)
        assert config.app_import_result is not None
        self.assertEqual(config.app_import_result["status"], "completed")
        self.assertEqual(config.app_import_result["categories_created"], 3)

    @patch("products.messaging.backend.api.message_categories.CustomerIOImportService")
    def test_import_from_customerio_stores_failure_result(self, mock_service_class):
        mock_service = MagicMock()
        mock_service_class.return_value = mock_service
        mock_service.import_api_data.return_value = {
            "status": "failed",
            "errors": ["Invalid API key"],
        }

        response = self.client.post(
            self._url("import_from_customerio"),
            {"app_api_key": "bad_key"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["status"], "failed")

        config = OptOutSyncConfig.objects.get(team=self.team)
        assert config.app_import_result is not None
        self.assertEqual(config.app_import_result["status"], "failed")
        self.assertIn("Invalid API key", config.app_import_result["error"])

    @patch("products.messaging.backend.api.message_categories.CustomerIOImportService")
    def test_import_from_customerio_reuses_stored_key(self, mock_service_class):
        Integration.objects.create(
            team=self.team,
            kind="customerio-app",
            sensitive_config={"app_api_key": "stored_key"},
            created_by=self.user,
        )

        mock_service = MagicMock()
        mock_service_class.return_value = mock_service
        mock_service.import_api_data.return_value = {"status": "completed", "errors": []}

        response = self.client.post(
            self._url("import_from_customerio"),
            {},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_service_class.assert_called_once_with(team=self.team, api_key="stored_key", user=self.user)

    def test_import_from_customerio_fails_without_key(self):
        response = self.client.post(
            self._url("import_from_customerio"),
            {},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("No API key", response.json()["error"])

    def test_import_from_customerio_rejects_key_when_integration_exists(self):
        Integration.objects.create(
            team=self.team,
            kind="customerio-app",
            sensitive_config={"app_api_key": "original_key"},
            created_by=self.user,
        )

        response = self.client.post(
            self._url("import_from_customerio"),
            {"app_api_key": "different_key"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        integration = Integration.objects.get(team=self.team, kind="customerio-app")
        self.assertEqual(integration.sensitive_config["app_api_key"], "original_key")

    def test_remove_app_config_clears_integration_and_result(self):
        integration = Integration.objects.create(
            team=self.team,
            kind="customerio-app",
            sensitive_config={"app_api_key": "test_key"},
            created_by=self.user,
        )
        OptOutSyncConfig.objects.create(
            team=self.team,
            app_integration=integration,
            app_import_result={
                "status": "completed",
                "imported_at": "2026-04-13T10:00:00Z",
                "categories_created": 6,
            },
        )

        response = self.client.delete(self._url("remove_customerio_app_config"))
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        self.assertFalse(Integration.objects.filter(team=self.team, kind="customerio-app").exists())

        config = OptOutSyncConfig.objects.get(team=self.team)
        self.assertIsNone(config.app_integration)
        self.assertIsNone(config.app_import_result)

    def test_remove_app_config_succeeds_when_no_config_exists(self):
        response = self.client.delete(self._url("remove_customerio_app_config"))
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

    def test_optout_sync_config_includes_webhook_fields(self):
        integration = Integration.objects.create(
            team=self.team,
            kind="customerio-webhook",
            sensitive_config={"webhook_signing_secret": "secret123"},
            created_by=self.user,
        )
        OptOutSyncConfig.objects.create(
            team=self.team,
            webhook_integration=integration,
            webhook_enabled=True,
        )

        response = self.client.get(self._url("optout_sync_config"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertTrue(data["webhook_enabled"])
        self.assertTrue(data["has_webhook_secret"])

    def test_optout_sync_config_webhook_fields_default_false(self):
        response = self.client.get(self._url("optout_sync_config"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertFalse(data["webhook_enabled"])
        self.assertFalse(data["has_webhook_secret"])

    def test_save_webhook_config_creates_integration(self):
        response = self.client.post(
            self._url("save_webhook_config"),
            {"webhook_signing_secret": "my_secret", "webhook_enabled": True},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.json()["webhook_enabled"])
        self.assertTrue(response.json()["has_webhook_secret"])

        integration = Integration.objects.get(team=self.team, kind="customerio-webhook")
        self.assertEqual(integration.sensitive_config["webhook_signing_secret"], "my_secret")

        config = OptOutSyncConfig.objects.get(team=self.team)
        self.assertEqual(config.webhook_integration, integration)
        self.assertTrue(config.webhook_enabled)

    def test_save_webhook_config_requires_secret_to_enable(self):
        response = self.client.post(
            self._url("save_webhook_config"),
            {"webhook_enabled": True},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_save_webhook_config_rejects_secret_when_integration_exists(self):
        Integration.objects.create(
            team=self.team,
            kind="customerio-webhook",
            sensitive_config={"webhook_signing_secret": "original"},
            created_by=self.user,
        )

        response = self.client.post(
            self._url("save_webhook_config"),
            {"webhook_signing_secret": "new_secret", "webhook_enabled": True},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        integration = Integration.objects.get(team=self.team, kind="customerio-webhook")
        self.assertEqual(integration.sensitive_config["webhook_signing_secret"], "original")

    def test_save_webhook_config_toggles_without_secret(self):
        Integration.objects.create(
            team=self.team,
            kind="customerio-webhook",
            sensitive_config={"webhook_signing_secret": "secret"},
            created_by=self.user,
        )

        response = self.client.post(
            self._url("save_webhook_config"),
            {"webhook_enabled": False},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.json()["webhook_enabled"])

        config = OptOutSyncConfig.objects.get(team=self.team)
        self.assertFalse(config.webhook_enabled)
        integration = Integration.objects.get(team=self.team, kind="customerio-webhook")
        self.assertEqual(integration.sensitive_config["webhook_signing_secret"], "secret")

    @patch("products.messaging.backend.api.message_categories.CustomerIOImportService")
    def test_csv_import_stores_success_result(self, mock_service_class):
        mock_service = MagicMock()
        mock_service_class.return_value = mock_service
        mock_service.process_preferences_csv.return_value = {
            "status": "completed",
            "total_rows": 100,
            "users_with_optouts": 60,
            "users_skipped": 40,
            "parse_errors": 2,
        }

        csv_file = SimpleUploadedFile("prefs.csv", b"email,id,cio_subscription_preferences\n", content_type="text/csv")
        response = self.client.post(
            self._url("import_preferences_csv"),
            {"csv_file": csv_file},
            format="multipart",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        config = OptOutSyncConfig.objects.get(team=self.team)
        assert config.csv_import_result is not None
        self.assertEqual(config.csv_import_result["status"], "completed")
        self.assertEqual(config.csv_import_result["total_rows"], 100)
        self.assertEqual(config.csv_import_result["users_with_optouts"], 60)

    @patch("products.messaging.backend.api.message_categories.CustomerIOImportService")
    def test_csv_import_stores_failure_result(self, mock_service_class):
        mock_service = MagicMock()
        mock_service_class.return_value = mock_service
        mock_service.process_preferences_csv.return_value = {
            "status": "failed",
            "details": "No categories found. Please run API import first.",
        }

        csv_file = SimpleUploadedFile("prefs.csv", b"email,id,cio_subscription_preferences\n", content_type="text/csv")
        response = self.client.post(
            self._url("import_preferences_csv"),
            {"csv_file": csv_file},
            format="multipart",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        config = OptOutSyncConfig.objects.get(team=self.team)
        assert config.csv_import_result is not None
        self.assertEqual(config.csv_import_result["status"], "failed")
        self.assertIn("No categories found", config.csv_import_result["error"])
