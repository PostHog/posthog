from typing import Optional

import pytest
from unittest import TestCase
from unittest.mock import MagicMock, patch

from django.test import override_settings

import dns.resolver
from parameterized import parameterized

from products.workflows.backend.providers.ses import SESProvider

TEST_DOMAIN = "test.posthog.com"


class TestSESProvider(TestCase):
    boto3_client_patcher: Optional[patch] = None  # type: ignore
    mock_boto3_client: Optional[MagicMock] = None

    @classmethod
    def setUpClass(cls):
        # Patch boto3.client for all tests in this class
        patcher = patch("products.workflows.backend.providers.ses.boto3.client")
        cls.boto3_client_patcher = patcher
        cls.mock_boto3_client = patcher.start()

        # Set up a default mock client with safe return values
        mock_client_instance = cls.mock_boto3_client.return_value
        mock_client_instance.list_identities.return_value = {"Identities": []}
        mock_client_instance.delete_identity.return_value = None
        mock_client_instance.get_identity_verification_attributes.return_value = {"VerificationAttributes": {}}
        mock_client_instance.get_identity_dkim_attributes.return_value = {"DkimAttributes": {}}
        mock_client_instance.verify_domain_identity.return_value = {"VerificationToken": "test-token-123"}
        mock_client_instance.verify_domain_dkim.return_value = {"DkimTokens": ["token1", "token2", "token3"]}
        mock_client_instance.get_caller_identity.return_value = {"Account": "123456789012"}

    def setUp(self):
        # Remove all domains from SES (mocked)
        ses_provider = SESProvider()
        if TEST_DOMAIN in ses_provider.ses_client.list_identities()["Identities"]:
            ses_provider.delete_identity(TEST_DOMAIN)

    def test_init_with_valid_credentials(self):
        with override_settings(
            SES_ACCESS_KEY_ID="test_access_key",
            SES_SECRET_ACCESS_KEY="test_secret_key",
            SES_REGION="us-east-1",
            SES_ENDPOINT="",
        ):
            provider = SESProvider()
            assert provider.ses_client
            assert provider.ses_v2_client
            assert provider.sts_client

    @patch("products.workflows.backend.providers.ses.dns.resolver.Resolver")
    def test_create_email_domain_success(self, mock_resolver_cls):
        mock_resolver_cls.return_value.resolve.side_effect = dns.resolver.NXDOMAIN()
        provider = SESProvider()

        # Mock the SES and SESv2 clients on the provider instance
        with (
            patch.object(provider, "ses_client") as mock_ses_client,
            patch.object(provider, "ses_v2_client") as mock_ses_v2_client,
        ):
            # Mock the verification attributes to return a success status
            mock_ses_client.get_identity_verification_attributes.return_value = {
                "VerificationAttributes": {
                    TEST_DOMAIN: {
                        "VerificationStatus": "Success",
                        "VerificationToken": "test-token-123",
                    }
                }
            }

            # Mock DKIM attributes to return a success status
            mock_ses_client.get_identity_dkim_attributes.return_value = {
                "DkimAttributes": {TEST_DOMAIN: {"DkimVerificationStatus": "Success"}}
            }

            # Mock the domain verification and DKIM setup calls
            mock_ses_client.verify_domain_identity.return_value = {"VerificationToken": "test-token-123"}
            mock_ses_client.verify_domain_dkim.return_value = {"DkimTokens": ["token1", "token2", "token3"]}

            # Mock tenant client methods
            mock_ses_v2_client.create_tenant.return_value = {}
            mock_ses_v2_client.get_caller_identity.return_value = {"Account": "123456789012"}
            mock_ses_v2_client.create_tenant_resource_association.return_value = {}

            provider.create_email_domain(TEST_DOMAIN, mail_from_subdomain="mail", team_id=1)

    @patch("products.workflows.backend.providers.ses.boto3.client")
    def test_create_email_domain_invalid_domain(self, mock_boto_client):
        with override_settings(
            SES_ACCESS_KEY_ID="test_access_key", SES_SECRET_ACCESS_KEY="test_secret_key", SES_REGION="us-east-1"
        ):
            provider = SESProvider()
            with pytest.raises(Exception, match="Please enter a valid domain"):
                provider.create_email_domain("invalid-domain", mail_from_subdomain="mail", team_id=1)

    @patch("products.workflows.backend.providers.ses.dns.resolver.Resolver")
    def test_verify_email_domain_initial_setup(self, mock_resolver_cls):
        mock_resolver_cls.return_value.resolve.side_effect = dns.resolver.NXDOMAIN()
        provider = SESProvider()

        # Mock the SES client on the provider instance
        with (
            patch.object(provider, "ses_client") as mock_ses_client,
        ):
            # Mock the verification attributes to return a non-success status
            mock_ses_client.get_identity_verification_attributes.return_value = {
                "VerificationAttributes": {
                    TEST_DOMAIN: {
                        "VerificationStatus": "Pending",  # Non-success status
                        "VerificationToken": "test-token-123",
                    }
                }
            }

            # Mock DKIM attributes to return a non-success status
            mock_ses_client.get_identity_dkim_attributes.return_value = {
                "DkimAttributes": {
                    TEST_DOMAIN: {
                        "DkimVerificationStatus": "Pending"  # Non-success status
                    }
                }
            }

            # Mock the domain verification and DKIM setup calls
            mock_ses_client.verify_domain_identity.return_value = {"VerificationToken": "test-token-123"}
            mock_ses_client.verify_domain_dkim.return_value = {"DkimTokens": ["token1", "token2", "token3"]}

            result = provider.verify_email_domain(TEST_DOMAIN, mail_from_subdomain="mail", team_id=1)

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
                    "type": "verification",
                    "recordType": "TXT",
                    "recordHostname": "@",
                    "recordValue": "v=spf1 include:amazonses.com ~all",
                    "status": "pending",
                },
                {
                    "recordHostname": "mail.test.posthog.com",
                    "recordType": "MX",
                    "recordValue": "feedback-smtp.us-east-1.amazonses.com",
                    "status": "pending",
                    "type": "mail_from",
                    "priority": 10,
                },
                {
                    "recordHostname": "mail.test.posthog.com",
                    "recordType": "TXT",
                    "recordValue": "v=spf1 include:amazonses.com ~all",
                    "status": "pending",
                    "type": "mail_from",
                },
                {
                    "type": "dmarc",
                    "recordType": "TXT",
                    "recordHostname": "_dmarc.test.posthog.com",
                    "recordValue": "v=DMARC1; p=none;",
                    "status": "pending",
                },
            ],
        }

    @patch("products.workflows.backend.providers.ses.dns.resolver.Resolver")
    def test_verify_email_domain_success(self, mock_resolver_cls):
        mock_rdata = MagicMock()
        mock_rdata.strings = [b"v=DMARC1; p=none;"]
        mock_resolver_cls.return_value.resolve.return_value = [mock_rdata]
        provider = SESProvider()

        # Patch the SES client to return 'Success' for both verification and DKIM
        with (
            patch.object(provider.ses_client, "get_identity_verification_attributes") as mock_verif_attrs,
            patch.object(provider.ses_client, "get_identity_dkim_attributes") as mock_dkim_attrs,
            patch.object(provider.ses_client, "get_identity_mail_from_domain_attributes") as mock_mail_from_attrs,
        ):
            mock_verif_attrs.return_value = {
                "VerificationAttributes": {
                    TEST_DOMAIN: {
                        "VerificationStatus": "Success",
                        "VerificationToken": "test-token-123",
                    }
                }
            }
            mock_dkim_attrs.return_value = {"DkimAttributes": {TEST_DOMAIN: {"DkimVerificationStatus": "Success"}}}
            mock_mail_from_attrs.return_value = {
                "MailFromDomainAttributes": {TEST_DOMAIN: {"MailFromDomainStatus": "Success"}}
            }

            result = provider.verify_email_domain(TEST_DOMAIN, mail_from_subdomain="mail", team_id=1)

            # Should return verified status with DNS records
            assert result["status"] == "success"
            assert len(result["dnsRecords"]) > 0  # Records are now always returned

    @patch("products.workflows.backend.providers.ses.dns.resolver.Resolver")
    def test_verify_email_domain_pending_when_dmarc_missing(self, mock_resolver_cls):
        """All SES checks pass but DMARC lookup fails → overall status is pending."""
        mock_resolver_cls.return_value.resolve.side_effect = dns.resolver.NXDOMAIN()
        provider = SESProvider()

        with (
            patch.object(provider.ses_client, "get_identity_verification_attributes") as mock_verif_attrs,
            patch.object(provider.ses_client, "get_identity_dkim_attributes") as mock_dkim_attrs,
            patch.object(provider.ses_client, "get_identity_mail_from_domain_attributes") as mock_mail_from_attrs,
        ):
            mock_verif_attrs.return_value = {"VerificationAttributes": {TEST_DOMAIN: {"VerificationStatus": "Success"}}}
            mock_dkim_attrs.return_value = {"DkimAttributes": {TEST_DOMAIN: {"DkimVerificationStatus": "Success"}}}
            mock_mail_from_attrs.return_value = {
                "MailFromDomainAttributes": {TEST_DOMAIN: {"MailFromDomainStatus": "Success"}}
            }

            result = provider.verify_email_domain(TEST_DOMAIN, mail_from_subdomain="mail", team_id=1)

            assert result["status"] == "pending"

    @parameterized.expand(
        [
            ("valid_dmarc_record", None, [b"v=DMARC1; p=none;"], "success", "v=DMARC1; p=none;"),
            ("lowercase_dmarc_tag", None, [b"v=dmarc1; p=quarantine;"], "success", "v=dmarc1; p=quarantine;"),
            ("leading_whitespace", None, [b" V=DMARC1; p=reject;"], "success", "V=DMARC1; p=reject;"),
            ("no_dns_record", dns.resolver.NXDOMAIN(), None, "pending", "v=DMARC1; p=none;"),
            ("non_dmarc_txt_record", None, [b"some random txt value"], "pending", "v=DMARC1; p=none;"),
        ]
    )
    def test_verify_email_domain_dmarc_status(
        self, _name, dns_side_effect, dns_strings, expected_dmarc_status, expected_record_value
    ):
        provider = SESProvider()

        with (
            patch.object(provider.ses_client, "get_identity_verification_attributes") as mock_verif_attrs,
            patch.object(provider.ses_client, "get_identity_dkim_attributes") as mock_dkim_attrs,
            patch.object(provider.ses_client, "get_identity_mail_from_domain_attributes") as mock_mail_from_attrs,
            patch("products.workflows.backend.providers.ses.dns.resolver.Resolver") as mock_resolver_cls,
        ):
            mock_resolver = mock_resolver_cls.return_value
            if dns_side_effect:
                mock_resolver.resolve.side_effect = dns_side_effect
            else:
                mock_rdata = MagicMock()
                mock_rdata.strings = dns_strings
                mock_resolver.resolve.return_value = [mock_rdata]

            mock_verif_attrs.return_value = {"VerificationAttributes": {TEST_DOMAIN: {"VerificationStatus": "Pending"}}}
            mock_dkim_attrs.return_value = {"DkimAttributes": {TEST_DOMAIN: {"DkimVerificationStatus": "Pending"}}}
            mock_mail_from_attrs.return_value = {
                "MailFromDomainAttributes": {TEST_DOMAIN: {"MailFromDomainStatus": "Pending"}}
            }

            result = provider.verify_email_domain(TEST_DOMAIN, mail_from_subdomain="mail", team_id=1)

            dmarc_records = [r for r in result["dnsRecords"] if r["type"] == "dmarc"]
            assert len(dmarc_records) == 1
            assert dmarc_records[0]["status"] == expected_dmarc_status
            assert dmarc_records[0]["recordValue"] == expected_record_value
            assert result["status"] == "pending"  # SES statuses are Pending, so overall stays pending
