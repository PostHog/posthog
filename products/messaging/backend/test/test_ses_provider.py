import pytest
from unittest import TestCase
from unittest.mock import patch

from django.test import override_settings

from products.messaging.backend.providers.ses import SESProvider

TEST_DOMAIN = "test.posthog.com"


class TestSESProvider(TestCase):
    def setUp(self):
        # Remove all domains from SES
        ses_provider = SESProvider()
        if TEST_DOMAIN in ses_provider.client.list_identities()["Identities"]:
            ses_provider.delete_identity(TEST_DOMAIN)

    def test_init_with_valid_credentials(self):
        with override_settings(
            SES_ACCESS_KEY_ID="test_access_key",
            SES_SECRET_ACCESS_KEY="test_secret_key",
            SES_REGION="us-east-1",
            SES_ENDPOINT="",
        ):
            provider = SESProvider()
            assert provider.client

    def test_create_email_domain_success(self):
        provider = SESProvider()

        # Mock the client on the provider instance
        with (
            patch.object(provider, "client") as mock_client,
            patch.object(provider, "tenant_client") as mock_tenant_client,
        ):
            # Mock the verification attributes to return a success status
            mock_client.get_identity_verification_attributes.return_value = {
                "VerificationAttributes": {
                    TEST_DOMAIN: {
                        "VerificationStatus": "Success",
                        "VerificationToken": "test-token-123",
                    }
                }
            }

            # Mock DKIM attributes to return a success status
            mock_client.get_identity_dkim_attributes.return_value = {
                "DkimAttributes": {TEST_DOMAIN: {"DkimVerificationStatus": "Success"}}
            }

            # Mock the domain verification and DKIM setup calls
            mock_client.verify_domain_identity.return_value = {"VerificationToken": "test-token-123"}
            mock_client.verify_domain_dkim.return_value = {"DkimTokens": ["token1", "token2", "token3"]}

            # Mock tenant client methods
            mock_tenant_client.create_tenant.return_value = {}
            mock_tenant_client.get_caller_identity.return_value = {"Account": "123456789012"}
            mock_tenant_client.create_tenant_resource_association.return_value = {}

            provider.create_email_domain(TEST_DOMAIN, team_id=1)

    @patch("products.messaging.backend.providers.ses.boto3.client")
    def test_create_email_domain_invalid_domain(self, mock_boto_client):
        with override_settings(
            SES_ACCESS_KEY_ID="test_access_key", SES_SECRET_ACCESS_KEY="test_secret_key", SES_REGION="us-east-1"
        ):
            provider = SESProvider()
            with pytest.raises(Exception, match="Please enter a valid domain"):
                provider.create_email_domain("invalid-domain", team_id=1)

    def test_verify_email_domain_initial_setup(self):
        provider = SESProvider()

        # Mock the client on the provider instance
        with patch.object(provider, "client") as mock_client:
            # Mock the verification attributes to return a non-success status
            mock_client.get_identity_verification_attributes.return_value = {
                "VerificationAttributes": {
                    TEST_DOMAIN: {
                        "VerificationStatus": "Pending",  # Non-success status
                        "VerificationToken": "test-token-123",
                    }
                }
            }

            # Mock DKIM attributes to return a non-success status
            mock_client.get_identity_dkim_attributes.return_value = {
                "DkimAttributes": {
                    TEST_DOMAIN: {
                        "DkimVerificationStatus": "Pending"  # Non-success status
                    }
                }
            }

            # Mock the domain verification and DKIM setup calls
            mock_client.verify_domain_identity.return_value = {"VerificationToken": "test-token-123"}
            mock_client.verify_domain_dkim.return_value = {"DkimTokens": ["token1", "token2", "token3"]}

            result = provider.verify_email_domain(TEST_DOMAIN, team_id=1)

        # Should return pending status with DNS records
        assert result == {
            "status": "pending",
            "dnsRecords": [
                {
                    "type": "verification",
                    "recordType": "TXT",
                    "recordHostname": "_amazonses.test.posthog.com",
                    "recordValue": "test-token-123",
                    "status": "pending",
                },
                {
                    "type": "dkim",
                    "recordType": "CNAME",
                    "recordHostname": "token1._domainkey.test.posthog.com",
                    "recordValue": "token1.dkim.amazonses.com",
                    "status": "pending",
                },
                {
                    "type": "dkim",
                    "recordType": "CNAME",
                    "recordHostname": "token2._domainkey.test.posthog.com",
                    "recordValue": "token2.dkim.amazonses.com",
                    "status": "pending",
                },
                {
                    "type": "dkim",
                    "recordType": "CNAME",
                    "recordHostname": "token3._domainkey.test.posthog.com",
                    "recordValue": "token3.dkim.amazonses.com",
                    "status": "pending",
                },
                {
                    "type": "spf",
                    "recordType": "TXT",
                    "recordHostname": "@",
                    "recordValue": "v=spf1 include:amazonses.com ~all",
                    "status": "pending",
                },
            ],
        }

    def test_verify_email_domain_success(self):
        provider = SESProvider()

        result = provider.verify_email_domain(TEST_DOMAIN, team_id=1)
        # Should return verified status with no DNS records needed
        assert result == {"status": "success", "dnsRecords": []}
