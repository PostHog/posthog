from io import StringIO

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.models import MessageCategory, MessageRecipientPreference
from posthog.models.message_category import MessageCategoryType
from posthog.models.message_preferences import PreferenceStatus

from .customerio_import_service import CustomerIOImportService


class TestCustomerIOImportService(BaseTest):
    def setUp(self):
        super().setUp()
        self.api_key = "test-api-key"
        self.service = CustomerIOImportService(self.team, self.api_key, self.user)

    @parameterized.expand(
        [
            # Test case 1: Valid preferences with topic_ prefix
            (
                {
                    "email": "user1@example.com",
                    "id": "cio_123",
                    "cio_subscription_preferences": '{"topics": {"topic_1": false, "topic_2": true}}',
                },
                {"status": "success", "email": "user1@example.com", "opted_out_categories": ["cat_1"]},
            ),
            # Test case 2: Valid preferences without topic_ prefix
            (
                {
                    "email": "user2@example.com",
                    "id": "cio_456",
                    "cio_subscription_preferences": '{"topics": {"1": false, "2": false}}',
                },
                {"status": "success", "email": "user2@example.com", "opted_out_categories": ["cat_1", "cat_2"]},
            ),
            # Test case 3: Empty preferences
            (
                {"email": "user3@example.com", "id": "cio_789", "cio_subscription_preferences": ""},
                {"status": "success", "email": "user3@example.com", "opted_out_categories": []},
            ),
            # Test case 4: Missing email - should use Customer.io ID
            (
                {"email": "", "id": "cio_999", "cio_subscription_preferences": '{"topics": {"1": false}}'},
                {"status": "error", "email": "Customer.io ID: cio_999", "error": "Missing email"},
            ),
            # Test case 5: Missing both email and ID
            (
                {"email": "", "id": "", "cio_subscription_preferences": '{"topics": {"1": false}}'},
                {"status": "error", "email": "unknown", "error": "Missing email"},
            ),
            # Test case 6: Invalid JSON in preferences
            (
                {"email": "user4@example.com", "id": "cio_111", "cio_subscription_preferences": "invalid json"},
                {
                    "status": "error",
                    "email": "user4@example.com",
                    "error": "Invalid JSON: Expecting value: line 1 column 1 (char 0)",
                },
            ),
            # Test case 7: All topics subscribed (no opt-outs)
            (
                {
                    "email": "user5@example.com",
                    "id": "cio_222",
                    "cio_subscription_preferences": '{"topics": {"topic_1": true, "topic_2": true}}',
                },
                {"status": "success", "email": "user5@example.com", "opted_out_categories": []},
            ),
        ]
    )
    def test_process_csv_row(self, row, expected_result):
        """Test CSV row processing with various input formats"""
        # Set up topic mapping
        self.service.topic_mapping = {
            "topic_1": "cat_1",
            "1": "cat_1",
            "topic_2": "cat_2",
            "2": "cat_2",
        }

        result = self.service._process_csv_row(row)

        # Check status and email
        assert result["status"] == expected_result["status"]
        assert result.get("email") == expected_result.get("email")

        # Check opted out categories (order doesn't matter)
        if "opted_out_categories" in expected_result:
            assert set(result.get("opted_out_categories", [])) == set(expected_result["opted_out_categories"])

        # Check error message (partial match for JSON errors)
        if "error" in expected_result:
            assert expected_result["error"][:20] in result.get("error", "")

    def test_process_preferences_csv_complete_flow(self):
        """Test complete CSV processing flow with batching"""
        # Create categories first
        cat1 = MessageCategory.objects.create(
            team=self.team,
            key="customerio_topic_1",
            name="Marketing",
            category_type=MessageCategoryType.MARKETING,
            created_by=self.user,
        )
        cat2 = MessageCategory.objects.create(
            team=self.team,
            key="customerio_topic_2",
            name="Product Updates",
            category_type=MessageCategoryType.MARKETING,
            created_by=self.user,
        )

        # Create CSV content with multiple rows
        csv_content = """email,id,cio_subscription_preferences
user1@example.com,cio_1,"{""topics"": {""topic_1"": false, ""topic_2"": true}}"
user2@example.com,cio_2,"{""topics"": {""topic_1"": false, ""topic_2"": false}}"
user3@example.com,cio_3,""
invalid@example.com,cio_4,"invalid json"
,cio_5,"{""topics"": {""topic_1"": false}}"
user4@example.com,cio_6,"{""topics"": {""topic_1"": true, ""topic_2"": true}}"
"""

        # Process CSV
        result = self.service.process_preferences_csv(StringIO(csv_content))

        # Check results
        assert result["status"] == "completed"
        assert result["total_rows"] == 6
        assert result["rows_processed"] == 6
        assert result["users_with_optouts"] == 2  # user1 and user2
        assert result["users_skipped"] == 2  # user3 (empty) and user4 (all subscribed)
        assert result["parse_errors"] == 2  # invalid@example.com and missing email
        assert result["preferences_updated"] == 3  # user1: 1 opt-out, user2: 2 opt-outs
        assert len(result["failed_imports"]) == 2

        # Check failed imports
        failed_emails = [f["email"] for f in result["failed_imports"]]
        assert "invalid@example.com" in failed_emails
        assert "Customer.io ID: cio_5" in failed_emails  # Missing email case

        # Check database records
        pref1 = MessageRecipientPreference.objects.get(team_id=self.team.id, identifier="user1@example.com")
        assert pref1.preferences[str(cat1.id)] == PreferenceStatus.OPTED_OUT.value
        assert str(cat2.id) not in pref1.preferences  # topic_2 was true

        pref2 = MessageRecipientPreference.objects.get(team_id=self.team.id, identifier="user2@example.com")
        assert pref2.preferences[str(cat1.id)] == PreferenceStatus.OPTED_OUT.value
        assert pref2.preferences[str(cat2.id)] == PreferenceStatus.OPTED_OUT.value

    @patch("products.workflows.backend.services.customerio_import_service.CustomerIOClient")
    def test_import_api_data_complete_flow(self, mock_client_class):
        """Test API import flow including categories and globally unsubscribed users"""
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client

        # Mock validation
        mock_client.validate_credentials.return_value = True

        # Mock subscription topics
        mock_client.get_subscription_topics.return_value = [
            {
                "id": "1",
                "identifier": "topic_1",
                "name": "Marketing Emails",
                "description": "Marketing communications",
                "public_description": "Promotional content and offers",
                "transactional": False,
            },
            {
                "id": "2",
                "identifier": "topic_2",
                "name": "System Notifications",
                "description": "Important system updates",
                "public_description": "Critical system notifications",
                "transactional": True,
            },
        ]

        # Mock globally unsubscribed customers
        mock_client.get_globally_unsubscribed_customers.side_effect = [
            {
                "identifiers": [
                    {"email": "unsubbed1@example.com"},
                    {"email": "unsubbed2@example.com"},
                ],
                "next": "cursor123",
            },
            {
                "identifiers": [
                    {"email": "unsubbed3@example.com"},
                ],
                "next": "",
            },
        ]

        # Run import
        result = self.service.import_api_data()

        # Check results
        assert result["status"] == "completed"
        assert result["topics_found"] == 2
        assert result["categories_created"] == 2
        assert result["globally_unsubscribed_count"] == 3
        assert result["preferences_updated"] == 6  # 3 users * 2 categories

        # Check categories were created
        cat1 = MessageCategory.objects.get(team=self.team, key="customerio_topic_1")
        assert cat1.name == "Marketing Emails"
        assert cat1.category_type == MessageCategoryType.MARKETING

        cat2 = MessageCategory.objects.get(team=self.team, key="customerio_topic_2")
        assert cat2.name == "System Notifications"
        assert cat2.category_type == MessageCategoryType.TRANSACTIONAL

        # Check globally unsubscribed preferences
        pref1 = MessageRecipientPreference.objects.get(team_id=self.team.id, identifier="unsubbed1@example.com")
        assert pref1.preferences[str(cat1.id)] == PreferenceStatus.OPTED_OUT.value
        assert pref1.preferences[str(cat2.id)] == PreferenceStatus.OPTED_OUT.value

    def test_save_csv_batch_with_existing_preferences(self):
        """Test batch saving when some users already have preferences"""
        # Create a category
        cat1 = MessageCategory.objects.create(
            team=self.team,
            key="customerio_topic_1",
            name="Marketing",
            category_type=MessageCategoryType.MARKETING,
            created_by=self.user,
        )

        # Create an existing preference for user1
        existing_pref = MessageRecipientPreference.objects.create(
            team_id=self.team.id,
            identifier="user1@example.com",
            preferences={"other_cat": PreferenceStatus.OPTED_OUT.value},
        )

        # Create batch data
        batch = [
            ("user1@example.com", [str(cat1.id)]),  # Existing user
            ("user2@example.com", [str(cat1.id)]),  # New user
            ("user3@example.com", [str(cat1.id), str(cat1.id)]),  # Duplicate categories
        ]

        # Save batch
        prefs_count = self.service._save_csv_batch(batch)

        # Check results
        assert prefs_count == 3

        # Check existing user's preferences were updated
        existing_pref.refresh_from_db()
        assert existing_pref.preferences["other_cat"] == PreferenceStatus.OPTED_OUT.value
        assert existing_pref.preferences[str(cat1.id)] == PreferenceStatus.OPTED_OUT.value

        # Check new users were created
        new_pref = MessageRecipientPreference.objects.get(team_id=self.team.id, identifier="user2@example.com")
        assert new_pref.preferences[str(cat1.id)] == PreferenceStatus.OPTED_OUT.value

    @patch("products.workflows.backend.services.customerio_import_service.CustomerIOClient")
    def test_api_import_with_invalid_credentials(self, mock_client_class):
        """Test API import handling of invalid credentials"""
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client

        # Mock failed validation
        mock_client.validate_credentials.return_value = False

        # Run import
        result = self.service.import_api_data()

        # Check error handling
        assert result["status"] == "failed"
        assert len(result["errors"]) == 1
        assert "Invalid Customer.io API credentials" in result["errors"][0]

    def test_process_csv_without_categories(self):
        """Test CSV processing when no categories exist"""
        csv_content = """email,id,cio_subscription_preferences
user1@example.com,cio_1,"{""topics"": {""topic_1"": false}}"
"""
        # Create service with None API key since CSV doesn't need it
        service = CustomerIOImportService(self.team, api_key=None, user=self.user)

        # Process CSV without creating categories first
        result = service.process_preferences_csv(StringIO(csv_content))

        # Should fail gracefully
        assert result["status"] == "failed"
        assert "No categories found" in result["details"]

    def test_api_import_without_api_key(self):
        """Test API import fails when API key is None"""
        service = CustomerIOImportService(self.team, api_key=None, user=self.user)

        # Run import without API key
        result = service.import_api_data()

        # Should fail with appropriate error
        assert result["status"] == "failed"
        assert len(result["errors"]) == 1
        assert "API key is required" in result["errors"][0]

    def test_unique_user_tracking_across_api_and_csv(self):
        """Test that unique users are tracked correctly across API and CSV imports"""
        # Simulate API import adding users
        self.service.all_processed_users.add("user1@example.com")
        self.service.all_processed_users.add("user2@example.com")

        # Create category for CSV processing
        MessageCategory.objects.create(
            team=self.team,
            key="customerio_topic_1",
            name="Marketing",
            category_type=MessageCategoryType.MARKETING,
            created_by=self.user,
        )

        # Create CSV with overlapping and new users
        csv_content = """email,id,cio_subscription_preferences
user1@example.com,cio_1,"{""topics"": {""topic_1"": false}}"
user3@example.com,cio_3,"{""topics"": {""topic_1"": false}}"
user2@example.com,cio_2,""
"""

        # Process CSV
        result = self.service.process_preferences_csv(StringIO(csv_content))

        # Check unique users count
        assert result["total_unique_users"] == 3  # user1, user2, user3 (no duplicates)
        assert len(self.service.all_processed_users) == 3
