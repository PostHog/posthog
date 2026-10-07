from io import StringIO

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.messaging.backend.models.message_category import MessageCategory, MessageCategoryType
from products.messaging.backend.models.message_preferences import (
    ALL_MESSAGE_PREFERENCE_CATEGORY_ID,
    MessageRecipientPreference,
    PreferenceStatus,
)

from .customerio_import_service import CustomerIOImportService


class TestCustomerIOImportService(BaseTest):
    def setUp(self):
        super().setUp()
        self.api_key = "test-api-key"
        self.service = CustomerIOImportService(self.team, self.api_key, self.user)

    @parameterized.expand(
        [
            ("true", "", True, True),
            (" TRUE ", "invalid json", True, True),
            ("false", "", False, True),
            ("", "", False, True),
            ("true", "", True, False),
        ]
    )
    def test_csv_import_global_unsubscribe(
        self, unsubscribed: str, topics: str, globally_opted_out: bool, has_categories: bool
    ) -> None:
        if has_categories:
            MessageCategory.objects.create(team=self.team, key="customerio_topic_1", name="Newsletter")
        recipient = MessageRecipientPreference.objects.create(
            team=self.team,
            identifier="unsubscribed@example.com",
            preferences={"existing_category": PreferenceStatus.OPTED_IN.value},
        )
        csv_content = (
            f"email,unsubscribed,cio_subscription_preferences\nunsubscribed@example.com,{unsubscribed},{topics}\n"
        )

        result = self.service.process_preferences_csv(StringIO(csv_content))

        assert result["status"] == "completed"
        assert result["parse_errors"] == (1 if topics == "invalid json" else 0)
        if topics == "invalid json":
            assert result["failed_imports"][0]["email"] == "unsubscribed@example.com"
            assert "Global opt-out imported" in result["failed_imports"][0]["error"]
        recipient.refresh_from_db()
        assert recipient.get_preference("existing_category") == PreferenceStatus.OPTED_IN
        assert recipient.get_preference(ALL_MESSAGE_PREFERENCE_CATEGORY_ID) == (
            PreferenceStatus.OPTED_OUT if globally_opted_out else PreferenceStatus.NO_PREFERENCE
        )

    def test_csv_short_row_preserves_pending_global_optouts(self) -> None:
        csv_content = (
            "email,cio_subscription_preferences,unsubscribed\nunsubscribed@example.com,,true\nshort@example.com,\n"
        )

        result = self.service.process_preferences_csv(StringIO(csv_content))

        assert result["status"] == "completed"
        assert result["users_with_optouts"] == 1
        preference = MessageRecipientPreference.objects.get(team=self.team, identifier="unsubscribed@example.com")
        assert preference.get_preference(ALL_MESSAGE_PREFERENCE_CATEGORY_ID) == PreferenceStatus.OPTED_OUT

    def test_csv_reports_topic_optouts_without_categories(self) -> None:
        csv_content = (
            'email,unsubscribed,cio_subscription_preferences\ntopic@example.com,false,{"topics":{"topic_1":false}}\n'
        )

        result = self.service.process_preferences_csv(StringIO(csv_content))

        assert result["parse_errors"] == 1
        assert result["users_skipped"] == 0
        assert result["failed_imports"][0]["email"] == "topic@example.com"
        assert "No categories found" in result["failed_imports"][0]["error"]

    def test_csv_global_unsubscribe_preserves_topic_choices(self) -> None:
        category = MessageCategory.objects.create(team=self.team, key="customerio_topic_1", name="Newsletter")
        csv_content = 'email,unsubscribed,cio_subscription_preferences\nunsubscribed@example.com,true,{"topics":{"topic_1":false}}\n'

        result = self.service.process_preferences_csv(StringIO(csv_content))

        assert result["parse_errors"] == 0
        preference = MessageRecipientPreference.objects.get(team=self.team, identifier="unsubscribed@example.com")
        assert preference.get_preference(ALL_MESSAGE_PREFERENCE_CATEGORY_ID) == PreferenceStatus.OPTED_OUT
        assert preference.get_preference(str(category.id)) == PreferenceStatus.OPTED_OUT

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

    @patch("products.messaging.backend.services.customerio_import_service.CustomerIOClient")
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
        assert result["preferences_updated"] == 9

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
        assert pref1.get_preference(ALL_MESSAGE_PREFERENCE_CATEGORY_ID) == PreferenceStatus.OPTED_OUT

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

    @patch("products.messaging.backend.services.customerio_import_service.CustomerIOClient")
    def test_api_import_global_unsubscribe_without_topics(self, mock_client_class) -> None:
        mock_client = mock_client_class.return_value
        mock_client.validate_credentials.return_value = True
        mock_client.get_subscription_topics.return_value = []
        mock_client.get_globally_unsubscribed_customers.return_value = {
            "identifiers": [{"email": "unsubscribed@example.com"}],
        }

        result = self.service.import_api_data()

        assert result["status"] == "completed"
        assert result["globally_unsubscribed_count"] == 1
        preference = MessageRecipientPreference.objects.get(team=self.team, identifier="unsubscribed@example.com")
        assert preference.get_preference(ALL_MESSAGE_PREFERENCE_CATEGORY_ID) == PreferenceStatus.OPTED_OUT

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
