from unittest.mock import patch, MagicMock

from posthog.test.base import APIBaseTest

from rest_framework import status

from posthog.models import MessageCategory, Team, MessageRecipientPreference


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


class TestCustomerIOImport(APIBaseTest):
    @patch("products.workflows.backend.services.customerio_import_service.CustomerIOClient")
    def test_import_from_customerio_success(self, mock_client_class):
        """
        Test successful import of topics and customer preferences from Customer.io
        """
        # Mock the CustomerIOClient
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        
        # Mock validation
        mock_client.validate_credentials.return_value = True
        
        # Mock topics response
        mock_topics = [
            {"id": "1", "identifier": "topic_1", "name": "Newsletter", "description": "Weekly newsletter"},
            {"id": "2", "identifier": "topic_2", "name": "Product Updates", "description": "Product announcements"},
        ]
        mock_client.get_subscription_centers.return_value = mock_topics
        
        # Mock customer preferences
        def mock_customer_generator():
            yield {
                "email": "user1@example.com",
                "id": "cust_1",
                "preferences": {
                    "topics": {
                        "topic_1": False,  # Opted out
                        "topic_2": True,  # Opted in
                    }
                }
            }
            yield {
                "email": "user2@example.com",
                "id": "cust_2",
                "preferences": {
                    "topics": {
                        "topic_1": False,  # Opted out
                        "topic_2": False,  # Opted out
                    }
                }
            }
        
        mock_client.get_all_customers_with_preferences.return_value = mock_customer_generator()
        
        # Make the API call
        response = self.client.post(
            f"/api/environments/{self.team.id}/messaging_categories/import_from_customerio/",
            {"app_api_key": "test_api_key"},
        )
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        
        # Verify the response
        self.assertEqual(data["status"], "completed")
        self.assertEqual(data["topics_found"], 2)
        self.assertEqual(data["workflows_created"], 2)
        self.assertEqual(data["customers_processed"], 2)
        self.assertEqual(data["preferences_updated"], 2)  # Both customers have opt-outs
        
        # Verify categories were created
        categories = MessageCategory.objects.filter(team=self.team)
        self.assertEqual(categories.count(), 2)
        
        # Check category keys
        category_keys = set(categories.values_list("key", flat=True))
        self.assertEqual(category_keys, {"customerio_topic_1", "customerio_topic_2"})
        
        # Verify preferences were created
        prefs = MessageRecipientPreference.objects.filter(team=self.team)
        self.assertEqual(prefs.count(), 2)
        
    @patch("products.workflows.backend.services.customerio_import_service.CustomerIOClient")
    def test_import_from_customerio_invalid_credentials(self, mock_client_class):
        """
        Test import fails with invalid credentials
        """
        # Mock the CustomerIOClient
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        
        # Mock validation failure
        mock_client.validate_credentials.return_value = False
        
        # Make the API call
        response = self.client.post(
            f"/api/environments/{self.team.id}/messaging_categories/import_from_customerio/",
            {"app_api_key": "invalid_key"},
        )
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        data = response.json()
        
        self.assertEqual(data["details"]["status"], "failed")
        self.assertIn("Invalid Customer.io API credentials", data["details"]["errors"][0])
        
    @patch("products.workflows.backend.services.customerio_import_service.CustomerIOClient")
    def test_import_from_customerio_no_topics(self, mock_client_class):
        """
        Test import handles case when no topics are found
        """
        # Mock the CustomerIOClient
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        
        # Mock validation
        mock_client.validate_credentials.return_value = True
        
        # Mock empty topics response
        mock_client.get_subscription_centers.return_value = []
        
        # Make the API call
        response = self.client.post(
            f"/api/environments/{self.team.id}/messaging_categories/import_from_customerio/",
            {"app_api_key": "test_api_key"},
        )
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        
        self.assertEqual(data["status"], "completed")
        self.assertEqual(data["topics_found"], 0)
        self.assertEqual(data["workflows_created"], 0)
        self.assertIn("No subscription topics found", data["errors"][0])
        
    def test_import_from_customerio_missing_api_key(self):
        """
        Test import requires API key
        """
        response = self.client.post(
            f"/api/environments/{self.team.id}/messaging_categories/import_from_customerio/",
            {},
        )
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("app_api_key", response.json())
        
    @patch("products.workflows.backend.services.customerio_import_service.CustomerIOClient")
    def test_import_from_customerio_eu_region(self, mock_client_class):
        """
        Test import tries EU region when US region fails
        """
        # Track instantiation calls
        instances = []
        
        def track_instance(*args, **kwargs):
            instance = MagicMock()
            instances.append({"args": args, "kwargs": kwargs, "instance": instance})
            return instance
        
        mock_client_class.side_effect = track_instance
        
        # First instance (US region) fails validation
        instances[0]["instance"].validate_credentials.return_value = False
        
        # Second instance (EU region) succeeds
        def setup_eu_instance():
            instances[1]["instance"].validate_credentials.return_value = True
            instances[1]["instance"].get_subscription_centers.return_value = [
                {"id": "1", "identifier": "topic_1", "name": "Newsletter"}
            ]
            instances[1]["instance"].get_all_customers_with_preferences.return_value = iter([])
        
        # Make the API call
        response = self.client.post(
            f"/api/environments/{self.team.id}/messaging_categories/import_from_customerio/",
            {"app_api_key": "test_api_key"},
        )
        
        # After first failure, setup EU instance
        if len(instances) == 1:
            setup_eu_instance()
            response = self.client.post(
                f"/api/environments/{self.team.id}/messaging_categories/import_from_customerio/",
                {"app_api_key": "test_api_key"},
            )
        
        # Verify both US and EU regions were tried
        self.assertGreaterEqual(len(instances), 2)
        self.assertEqual(instances[0]["kwargs"]["region"], "us")
        self.assertEqual(instances[1]["kwargs"]["region"], "eu")
        
    @patch("products.workflows.backend.services.customerio_import_service.CustomerIOClient")
    def test_import_updates_existing_categories(self, mock_client_class):
        """
        Test that re-importing updates existing categories instead of creating duplicates
        """
        # Create an existing category
        existing = MessageCategory.objects.create(
            team=self.team, 
            key="customerio_topic_1", 
            name="Old Name",
            created_by=self.user
        )
        
        # Mock the CustomerIOClient
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        
        # Mock validation
        mock_client.validate_credentials.return_value = True
        
        # Mock topics response
        mock_topics = [
            {"id": "1", "identifier": "topic_1", "name": "Updated Newsletter", "description": "New description"},
        ]
        mock_client.get_subscription_centers.return_value = mock_topics
        mock_client.get_all_customers_with_preferences.return_value = iter([])
        
        # Make the API call
        response = self.client.post(
            f"/api/environments/{self.team.id}/messaging_categories/import_from_customerio/",
            {"app_api_key": "test_api_key"},
        )
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        
        # Should not create new workflow since it already exists
        self.assertEqual(data["workflows_created"], 0)
        
        # Verify the category was updated
        existing.refresh_from_db()
        self.assertEqual(existing.name, "Updated Newsletter")
        self.assertEqual(existing.description, "New description")
        
        # Verify no duplicates
        categories = MessageCategory.objects.filter(team=self.team, key="customerio_topic_1")
        self.assertEqual(categories.count(), 1)
