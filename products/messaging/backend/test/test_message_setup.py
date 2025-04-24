from unittest.mock import patch

from rest_framework import status


from posthog.test.base import APIBaseTest


class TestMessageSetupViewSet(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.email_setup_url = f"/api/environments/{self.team.id}/messaging_setup/email/"
        self.email_verify_url = f"/api/environments/{self.team.id}/messaging_setup/email/verify/"

    @patch("products.messaging.backend.api.message_setup.MailjetProvider")
    def test_email_domain_parameter_required(self, mock_mailjet_provider):
        response = self.client.post(self.email_setup_url, {})

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json(), {"error": "Domain parameter is required"})
        mock_mailjet_provider.assert_not_called()

    @patch("products.messaging.backend.api.message_setup.MailjetProvider")
    def test_email_setup_returns_mailjet_result(self, mock_mailjet_provider):
        # Mock the setup_email_domain method to return a test result
        mock_mailjet = mock_mailjet_provider.return_value
        expected_result = {
            "status": "pending",
            "dnsRecords": [
                {
                    "type": "dkim",
                    "recordType": "TXT",
                    "recordHostname": "mailjet._domainkey.example.com",
                    "recordValue": "v=DKIM1; k=rsa; p=MIGfMA0GCSqGSIb3DQEBA...",
                    "status": "pending",
                },
                {
                    "type": "spf",
                    "recordType": "TXT",
                    "recordHostname": "@",
                    "recordValue": "v=spf1 include:spf.mailjet.com ~all",
                    "status": "pending",
                },
            ],
        }
        mock_mailjet.setup_email_domain.return_value = expected_result

        # Make the API request
        response = self.client.post(self.email_setup_url, {"domain": "example.com"})

        # Verify the response
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), expected_result)

        # Verify the mock was called correctly
        mock_mailjet.setup_email_domain.assert_called_once_with("example.com")

    @patch("products.messaging.backend.api.message_setup.MailjetProvider")
    def test_email_verify_domain_parameter_required(self, mock_mailjet_provider):
        response = self.client.post(self.email_verify_url, {})

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json(), {"error": "Domain parameter is required"})
        mock_mailjet_provider.assert_not_called()

    @patch("products.messaging.backend.api.message_setup.MailjetProvider")
    def test_email_verify_returns_mailjet_result(self, mock_mailjet_provider):
        # Mock the verify_email_domain method to return a test result
        mock_mailjet = mock_mailjet_provider.return_value
        expected_result = {
            "status": "verified",
            "dnsRecords": [
                {
                    "type": "dkim",
                    "recordType": "TXT",
                    "recordHostname": "mailjet._domainkey.example.com",
                    "recordValue": "v=DKIM1; k=rsa; p=MIGfMA0GCSqGSIb3DQEBA...",
                    "status": "verified",
                },
                {
                    "type": "spf",
                    "recordType": "TXT",
                    "recordHostname": "@",
                    "recordValue": "v=spf1 include:spf.mailjet.com ~all",
                    "status": "verified",
                },
            ],
        }
        mock_mailjet.verify_email_domain.return_value = expected_result

        # Make the API request
        response = self.client.post(self.email_verify_url, {"domain": "example.com"})

        # Verify the response
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), expected_result)

        # Verify the mock was called correctly
        mock_mailjet.verify_email_domain.assert_called_once_with("example.com")
