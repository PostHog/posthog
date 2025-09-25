from unittest.mock import MagicMock, patch

from django.test import TestCase, override_settings

from rest_framework import exceptions

from posthog.models import Organization, Team

from products.messaging.backend.providers.mailjet import MailjetProvider


class TestMailjetProvider(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name="test")
        self.team = Team.objects.create(organization=self.organization)
        self.domain = "example.com"
        self.mock_dns_response = {
            "DKIMRecordName": "mailjet._domainkey.example.com",
            "DKIMRecordValue": "v=DKIM1; k=rsa; p=MIGfMA0GCSqGSIb3DQEBA...",
            "DKIMStatus": "Not checked",
            "SPFRecordValue": "v=spf1 include:spf.mailjet.com ~all",
            "SPFStatus": "Not checked",
            "OwnerShipToken": "123a4bc56d7890efg123h4ijk56l78mn",
            "OwnerShipTokenRecordName": "mailjet._123a4bc56.example.com.",
        }

    @override_settings(MAILJET_PUBLIC_KEY="test_api_key", MAILJET_SECRET_KEY="test_secret_key")
    def test_init_with_valid_credentials(self):
        provider = MailjetProvider()
        self.assertEqual(provider.api_key, "test_api_key")
        self.assertEqual(provider.api_secret, "test_secret_key")

    @override_settings(MAILJET_PUBLIC_KEY="", MAILJET_SECRET_KEY="test_secret_key")
    def test_init_with_missing_api_key(self):
        with self.assertRaises(ValueError) as context:
            MailjetProvider()
        self.assertEqual(str(context.exception), "MAILJET_PUBLIC_KEY is not set in environment or settings")

    @override_settings(MAILJET_PUBLIC_KEY="test_api_key", MAILJET_SECRET_KEY="")
    def test_init_with_missing_secret_key(self):
        with self.assertRaises(ValueError) as context:
            MailjetProvider()
        self.assertEqual(str(context.exception), "MAILJET_SECRET_KEY is not set in environment or settings")

    @override_settings(MAILJET_PUBLIC_KEY="test_api_key", MAILJET_SECRET_KEY="test_secret_key")
    def test_format_dns_records(self):
        provider = MailjetProvider()
        status, records = provider._format_dns_records(
            self.mock_dns_response,
            self.mock_dns_response,
            False,
        )

        self.assertEqual(status, "pending")
        self.assertEqual(len(records), 3)

        dkim_record = next((r for r in records if r["type"] == "dkim"), {})
        spf_record = next((r for r in records if r["type"] == "spf"), {})
        ownership_record = next((r for r in records if r["type"] == "ownership"), {})

        self.assertEqual(dkim_record["recordType"], "TXT")
        self.assertEqual(dkim_record["recordHostname"], self.mock_dns_response["DKIMRecordName"])
        self.assertEqual(dkim_record["recordValue"], self.mock_dns_response["DKIMRecordValue"])
        self.assertEqual(dkim_record["status"], "pending")

        self.assertEqual(spf_record["recordType"], "TXT")
        self.assertEqual(spf_record["recordHostname"], "@")
        self.assertEqual(spf_record["recordValue"], self.mock_dns_response["SPFRecordValue"])
        self.assertEqual(spf_record["status"], "pending")

        self.assertEqual(ownership_record["recordType"], "TXT")
        self.assertEqual(ownership_record["recordHostname"], self.mock_dns_response["OwnerShipTokenRecordName"])
        self.assertEqual(ownership_record["recordValue"], self.mock_dns_response["OwnerShipToken"])
        self.assertEqual(ownership_record["status"], "pending")

    @override_settings(MAILJET_PUBLIC_KEY="test_api_key", MAILJET_SECRET_KEY="test_secret_key")
    def test_format_dns_records_verified(self):
        provider = MailjetProvider()
        verified_response = self.mock_dns_response.copy()
        verified_response["DKIMStatus"] = "OK"
        verified_response["SPFStatus"] = "OK"

        status, records = provider._format_dns_records(verified_response, verified_response, True)

        self.assertEqual(status, "success")
        self.assertEqual(records[0]["status"], "success")
        self.assertEqual(records[1]["status"], "success")

    @override_settings(MAILJET_PUBLIC_KEY="test_api_key", MAILJET_SECRET_KEY="test_secret_key")
    def test_format_dns_records_partial_verification(self):
        provider = MailjetProvider()
        partial_response = self.mock_dns_response.copy()
        partial_response["DKIMStatus"] = "OK"

        status, records = provider._format_dns_records(partial_response, partial_response, True)

        self.assertEqual(status, "pending")
        self.assertEqual(records[0]["status"], "success")
        self.assertEqual(records[1]["status"], "pending")

    @patch("requests.post")
    @override_settings(MAILJET_PUBLIC_KEY="test_api_key", MAILJET_SECRET_KEY="test_secret_key")
    def test_create_email_domain_success(self, mock_post):
        mock_response = MagicMock()
        mock_response.json.return_value = {"Count": 1, "Data": [{"Success": True}], "Total": 1}
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        provider = MailjetProvider()
        provider.create_email_domain(self.domain, self.team.id)
        mock_post.assert_called_once()

    @patch("requests.post")
    @override_settings(MAILJET_PUBLIC_KEY="test_api_key", MAILJET_SECRET_KEY="test_secret_key")
    def test_create_email_domain_invalid_domain(self, mock_post):
        provider = MailjetProvider()
        invalid_domains = ["", "invalid domain", "no-tld", "@example.com"]

        for domain in invalid_domains:
            with self.assertRaises(exceptions.ValidationError):
                provider.create_email_domain(domain, self.team.id)

        mock_post.assert_not_called()

    @patch("requests.post")
    @override_settings(MAILJET_PUBLIC_KEY="test_api_key", MAILJET_SECRET_KEY="test_secret_key")
    def test_create_email_domain_request_exception(self, mock_post):
        mock_post.side_effect = Exception("API Error")

        provider = MailjetProvider()

        with self.assertRaises(Exception):
            provider.create_email_domain(self.domain, self.team.id)

    @patch("requests.get")
    @override_settings(MAILJET_PUBLIC_KEY="test_api_key", MAILJET_SECRET_KEY="test_secret_key")
    def test_get_domain_dns_records_success(self, mock_get):
        mock_response = MagicMock()
        mock_response.json.return_value = {"Count": 1, "Data": [self.mock_dns_response], "Total": 1}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        provider = MailjetProvider()
        result = provider._get_domain_dns_records(self.domain)

        self.assertEqual(result, self.mock_dns_response)
        mock_get.assert_called_once()
        args, kwargs = mock_get.call_args
        self.assertEqual(kwargs["auth"], ("test_api_key", "test_secret_key"))
        self.assertEqual(kwargs["headers"], {"Content-Type": "application/json"})
        self.assertEqual(args[0], f"https://api.mailjet.com/v3/REST/dns/{self.domain}")

    @patch("requests.get")
    @override_settings(MAILJET_PUBLIC_KEY="test_api_key", MAILJET_SECRET_KEY="test_secret_key")
    def test_get_domain_dns_records_request_exception(self, mock_get):
        mock_get.side_effect = Exception("API Error")

        provider = MailjetProvider()

        with self.assertRaises(Exception):
            provider._get_domain_dns_records(self.domain)

    @patch("requests.post")
    @override_settings(MAILJET_PUBLIC_KEY="test_api_key", MAILJET_SECRET_KEY="test_secret_key")
    def test_check_domain_dns_records_success(self, mock_post):
        mock_response = MagicMock()
        mock_response.json.return_value = {"Count": 1, "Data": [self.mock_dns_response], "Total": 1}
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        provider = MailjetProvider()
        result = provider._check_domain_dns_records(self.domain)

        self.assertEqual(result, self.mock_dns_response)
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        self.assertEqual(kwargs["auth"], ("test_api_key", "test_secret_key"))
        self.assertEqual(kwargs["headers"], {"Content-Type": "application/json"})
        self.assertEqual(args[0], f"https://api.mailjet.com/v3/REST/dns/{self.domain}/check")

    @patch("requests.get")
    @override_settings(MAILJET_PUBLIC_KEY="test_api_key", MAILJET_SECRET_KEY="test_secret_key")
    def test_check_domain_dns_records_request_exception(self, mock_get):
        mock_get.side_effect = Exception("API Error")

        provider = MailjetProvider()

        with self.assertRaises(Exception):
            provider._check_domain_dns_records(self.domain)

    @patch.object(MailjetProvider, "_validate_email_sender")
    @patch.object(MailjetProvider, "_check_domain_dns_records")
    @patch.object(MailjetProvider, "_get_domain_dns_records")
    @override_settings(MAILJET_PUBLIC_KEY="test_api_key", MAILJET_SECRET_KEY="test_secret_key")
    def test_verify_email_domain(self, mock_get_dns, mock_check_dns, mock_validate):
        verified_dns_response = self.mock_dns_response.copy()
        verified_dns_response["DKIMStatus"] = "OK"
        verified_dns_response["SPFStatus"] = "OK"
        mock_get_dns.return_value = verified_dns_response
        mock_check_dns.return_value = verified_dns_response
        mock_validate.return_value = True

        provider = MailjetProvider()
        result = provider.verify_email_domain(self.domain)

        mock_check_dns.assert_called_once_with(self.domain)
        mock_get_dns.assert_called_once_with(self.domain)

        self.assertEqual(result["status"], "success")
        self.assertEqual(len(result["dnsRecords"]), 3)
        self.assertTrue(all(record["status"] == "success" for record in result["dnsRecords"]))

    @patch.object(MailjetProvider, "_validate_email_sender")
    @patch.object(MailjetProvider, "_check_domain_dns_records")
    @patch.object(MailjetProvider, "_get_domain_dns_records")
    @override_settings(MAILJET_PUBLIC_KEY="test_api_key", MAILJET_SECRET_KEY="test_secret_key")
    def test_verify_email_domain_not_verified(self, mock_get_dns, mock_check_dns, mock_validate):
        mock_get_dns.return_value = self.mock_dns_response
        mock_check_dns.return_value = self.mock_dns_response
        mock_validate.return_value = False

        provider = MailjetProvider()
        result = provider.verify_email_domain(self.domain)

        mock_check_dns.assert_called_once_with(self.domain)
        mock_get_dns.assert_called_once_with(self.domain)

        self.assertEqual(result["status"], "pending")
        self.assertEqual(len(result["dnsRecords"]), 3)
        self.assertTrue(all(record["status"] == "pending" for record in result["dnsRecords"]))

    @patch.object(MailjetProvider, "_validate_email_sender")
    @patch.object(MailjetProvider, "_check_domain_dns_records")
    @patch.object(MailjetProvider, "_get_domain_dns_records")
    @override_settings(MAILJET_PUBLIC_KEY="test_api_key", MAILJET_SECRET_KEY="test_secret_key")
    def test_verify_email_domain_validation_failed(self, mock_get_dns, mock_check_dns, mock_validate):
        verified_dns_response = self.mock_dns_response.copy()
        verified_dns_response["DKIMStatus"] = "OK"
        verified_dns_response["SPFStatus"] = "OK"
        mock_get_dns.return_value = verified_dns_response
        mock_check_dns.return_value = verified_dns_response

        mock_validate.return_value = False

        provider = MailjetProvider()
        result = provider.verify_email_domain(self.domain)

        mock_validate.assert_called_once_with(f"*@{self.domain}")
        self.assertEqual(result["status"], "pending")
        self.assertEqual(len(result["dnsRecords"]), 3)

        self.assertTrue(result["dnsRecords"][0]["status"] == "success")
        self.assertTrue(result["dnsRecords"][1]["status"] == "success")
        self.assertTrue(result["dnsRecords"][2]["status"] == "pending")
