import re
import requests
import logging
from django.conf import settings
from rest_framework import exceptions

logger = logging.getLogger(__name__)


class MailjetConfig:
    # Base API URLs
    API_BASE_URL_V3: str = "https://api.mailjet.com/v3"
    API_BASE_URL_V31: str = "https://api.mailjet.com/v3.1"

    # Endpoints
    API_KEY_ENDPOINT: str = "/apikey"
    SENDER_ENDPOINT: str = "/sender"
    DNS_ENDPOINT: str = "/dns"
    DNS_CHECK_ENDPOINT: str = "/check"

    # Default headers
    DEFAULT_HEADERS: dict[str, str] = {
        "Content-Type": "application/json",
    }


class MailjetProvider:
    def __init__(self):
        self.api_key = self.get_api_key()
        self.api_secret = self.get_api_secret()
        self.headers = self._get_headers()

    @classmethod
    def get_api_key(cls) -> str:
        api_key = settings.MAILJET_API_KEY
        if not api_key:
            raise ValueError("MAILJET_API_KEY is not set in environment or settings")
        return api_key

    @classmethod
    def get_api_secret(cls) -> str:
        api_secret = settings.MAILJET_SECRET_KEY
        if not api_secret:
            raise ValueError("MAILJET_SECRET_KEY is not set in environment or settings")
        return api_secret

    def _get_headers(self) -> dict[str, str]:
        headers = MailjetConfig.DEFAULT_HEADERS.copy()
        return headers

    def create_sender_domain(self, domain: str) -> dict:
        """
        Create a new sender domain

        Reference: https://dev.mailjet.com/email/reference/sender-addresses-and-domains/sender/#v3_post_sender
        """
        # Validate the domain contains valid characters for a domain name
        DOMAIN_REGEX = r"^([a-z0-9]+(-[a-z0-9]+)*\.)+[a-z]{2,}$"
        if not re.match(DOMAIN_REGEX, domain):
            raise exceptions.ValidationError("Please enter a valid domain or subdomain name.")

        sender_domain = f"*@{domain}"

        url = f"{MailjetConfig.API_BASE_URL_V3}{MailjetConfig.SENDER_ENDPOINT}"

        payload = {"EmailType": "domain", "Email": sender_domain, "Name": domain}

        try:
            response = requests.post(url, auth=(self.api_key, self.api_secret), headers=self.headers, json=payload)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.exception(f"Mailjet API error creating sender domain: {e}")
            raise

    def get_domain_dns_records(self, domain: str) -> dict:
        """
        Get DNS records for a domain (DKIM and SPF verification status)

        Reference: https://dev.mailjet.com/email/reference/sender-addresses-and-domains/dns/
        """
        url = f"{MailjetConfig.API_BASE_URL_V3}{MailjetConfig.DNS_ENDPOINT}/{domain}"

        try:
            response = requests.get(url, auth=(self.api_key, self.api_secret), headers=self.headers)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.exception(f"Mailjet API error fetching DNS records: {e}")
            raise

    def check_domain_dns_records(self, domain: str) -> dict:
        """
        Check the status of DNS records for a domain

        Reference: https://dev.mailjet.com/email/reference/sender-addresses-and-domains/dns/#v3_get_dns_check
        """
        url = f"{MailjetConfig.API_BASE_URL_V3}{MailjetConfig.DNS_CHECK_ENDPOINT}/{domain}{MailjetConfig.DNS_CHECK_ENDPOINT}"

        try:
            response = requests.get(url, auth=(self.api_key, self.api_secret), headers=self.headers)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.exception(f"Mailjet API error checking DNS records: {e}")
            raise

    def setup_email_domain(self, email_domain: str) -> dict:
        """
        Complete setup for a new email domain:
        1. Create a sender domain
        2. Get DNS records for the domain

        Returns all necessary information for domain verification.
        """
        # Create a sender for the domain
        self.create_sender_domain(email_domain)

        # Get DNS records for verification
        dns_response = self.get_domain_dns_records(email_domain)

        # Format the response with DNS records information
        formatted_dns_records = []

        # Add DKIM record if present
        if "DKIMRecordName" in dns_response and "DKIMRecordValue" in dns_response:
            formatted_dns_records.append(
                {
                    "type": "dkim",
                    "recordType": "TXT",
                    "recordHostname": dns_response.get("DKIMRecordName"),
                    "recordValue": dns_response.get("DKIMRecordValue"),
                    "status": dns_response.get("DKIMStatus", "pending"),
                }
            )

        # Add SPF record if present
        if "SPFRecordName" in dns_response and "SPFRecordValue" in dns_response:
            formatted_dns_records.append(
                {
                    "type": "spf",
                    "recordType": "TXT",
                    "recordHostname": dns_response.get("SPFRecordName", "@"),
                    "recordValue": dns_response.get("SPFRecordValue"),
                    "status": dns_response.get("SPFStatus", "pending"),
                }
            )

        return {
            "status": "pending",
            "dnsRecords": formatted_dns_records,
        }

    def verify_email_domain(self, domain: str) -> dict:
        """
        Verify the email domain by checking DNS records status
        """

        # Check the current status of the domain. If it's already verified, return the current status
        # If not, get the DNS records and return them
        dns_response = self.get_domain_dns_records(domain)

        # Determine overall status
        dkim_status = dns_response.get("DKIMStatus", "pending")
        spf_status = dns_response.get("SPFStatus", "pending")

        # If both DKIM and SPF are verified, then the domain is verified
        overall_status = "verified" if dkim_status == "verified" and spf_status == "verified" else "pending"

        # Format the response with DNS records information
        formatted_dns_records = []

        # Add DKIM record if present
        if "DKIMRecordName" in dns_response and "DKIMRecordValue" in dns_response:
            formatted_dns_records.append(
                {
                    "type": "dkim",
                    "recordType": "TXT",
                    "recordHostname": dns_response.get("DKIMRecordName"),
                    "recordValue": dns_response.get("DKIMRecordValue"),
                    "status": dkim_status,
                }
            )

        # Add SPF record if present
        if "SPFRecordName" in dns_response and "SPFRecordValue" in dns_response:
            formatted_dns_records.append(
                {
                    "type": "spf",
                    "recordType": "TXT",
                    "recordHostname": dns_response.get("SPFRecordName", "@"),
                    "recordValue": dns_response.get("SPFRecordValue"),
                    "status": spf_status,
                }
            )

        return {"status": overall_status, "dnsRecords": formatted_dns_records}
