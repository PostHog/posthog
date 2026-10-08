from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from parameterized import parameterized

from .customerio_import_service import CustomerIOImportService


class TestCustomerIOImportServiceUnit(SimpleTestCase):
    def setUp(self):
        super().setUp()
        self.team = MagicMock()
        self.user = MagicMock()
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

    @patch("products.messaging.backend.services.customerio_import_service.CustomerIOClient")
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

    def test_api_import_without_api_key(self):
        """Test API import fails when API key is None"""
        service = CustomerIOImportService(self.team, api_key=None, user=self.user)

        # Run import without API key
        result = service.import_api_data()

        # Should fail with appropriate error
        assert result["status"] == "failed"
        assert len(result["errors"]) == 1
        assert "API key is required" in result["errors"][0]
