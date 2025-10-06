import re
import logging

from django.conf import settings

import requests
from rest_framework import exceptions

logger = logging.getLogger(__name__)


class MailjetDnsResponse:
    count: int
    data: list[dict]
    total: int

    def __init__(self, Count: int, Data: list[dict], Total: int):
        self.count = Count
        self.data = Data
        self.total = Total

    def get_first_item(self) -> dict | None:
        return self.data[0] if self.data else None


class MailjetValidationResponse:
    validation_method: str
    errors: dict
    global_error: str

    def __init__(self, ValidationMethod: str, Errors: dict, GlobalError: str):
        self.validation_method = ValidationMethod
        self.errors = Errors
        self.global_error = GlobalError


class MailjetConfig:
    API_BASE_URL_V3: str = "https://api.mailjet.com/v3/REST"

    SENDER_ENDPOINT: str = "/sender"
    SENDER_VALIDATE_ENDPOINT: str = "/validate"
    DNS_ENDPOINT: str = "/dns"
    DNS_CHECK_ENDPOINT: str = "/check"

    DEFAULT_HEADERS: dict[str, str] = {
        "Content-Type": "application/json",
    }


class MailjetProvider:
    def __init__(self):
        self.api_key = self.get_api_key()
        self.api_secret = self.get_api_secret()

    @classmethod
    def get_api_key(cls) -> str:
        api_key = settings.MAILJET_PUBLIC_KEY
        if not api_key:
            raise ValueError("MAILJET_PUBLIC_KEY is not set in environment or settings")
        return api_key

    @classmethod
    def get_api_secret(cls) -> str:
        api_secret = settings.MAILJET_SECRET_KEY
        if not api_secret:
            raise ValueError("MAILJET_SECRET_KEY is not set in environment or settings")
        return api_secret

    def _format_dns_records(
        self, required_dns_records: dict, dns_status_response: dict, is_mailjet_validated: bool
    ) -> tuple[str, list[dict]]:
        formatted_dns_records = []

        # DKIM status possible values: "Not checked", "OK", "Error"
        dkim_status = dns_status_response.get("DKIMStatus", "Not checked")
        # SPF status possible values: "Not checked", "Not found", "OK", "Error"
        spf_status = dns_status_response.get("SPFStatus", "Not checked")
        overall_status = "success" if dkim_status == "OK" and spf_status == "OK" and is_mailjet_validated else "pending"

        if "DKIMRecordName" in required_dns_records and "DKIMRecordValue" in required_dns_records:
            formatted_dns_records.append(
                {
                    "type": "dkim",
                    "recordType": "TXT",
                    "recordHostname": required_dns_records.get("DKIMRecordName"),
                    "recordValue": required_dns_records.get("DKIMRecordValue"),
                    "status": "success" if dkim_status == "OK" else "pending",
                }
            )

        if "SPFRecordValue" in required_dns_records:
            formatted_dns_records.append(
                {
                    "type": "spf",
                    "recordType": "TXT",
                    "recordHostname": "@",
                    "recordValue": required_dns_records.get("SPFRecordValue"),
                    "status": "success" if spf_status == "OK" else "pending",
                }
            )

        if "OwnerShipToken" in required_dns_records and "OwnerShipTokenRecordName" in required_dns_records:
            formatted_dns_records.append(
                {
                    "type": "ownership",
                    "recordType": "TXT",
                    "recordHostname": required_dns_records.get("OwnerShipTokenRecordName"),
                    "recordValue": required_dns_records.get("OwnerShipToken"),
                    "status": "success" if is_mailjet_validated else "pending",
                }
            )

        return overall_status, formatted_dns_records

    def _get_domain_dns_records(self, domain: str):
        """
        Get DNS records for a domain (Mailjet verification, DKIM + SPF verification status)

        Reference: https://dev.mailjet.com/email/reference/sender-addresses-and-domains/dns/
        """
        url = f"{MailjetConfig.API_BASE_URL_V3}{MailjetConfig.DNS_ENDPOINT}/{domain}"

        try:
            response = requests.get(url, auth=(self.api_key, self.api_secret), headers=MailjetConfig.DEFAULT_HEADERS)
            response.raise_for_status()
            return MailjetDnsResponse(**response.json()).get_first_item()
        except requests.exceptions.RequestException as e:
            logger.exception(f"Mailjet API error fetching DNS records: {e}")
            raise

    def _check_domain_dns_records(self, domain: str):
        """
        Trigger a check for the current status of DKIM and SPF records for a domain

        Reference: https://dev.mailjet.com/email/reference/sender-addresses-and-domains/dns/#v3_get_dns_check
        """
        url = f"{MailjetConfig.API_BASE_URL_V3}{MailjetConfig.DNS_ENDPOINT}/{domain}{MailjetConfig.DNS_CHECK_ENDPOINT}"

        try:
            response = requests.post(url, auth=(self.api_key, self.api_secret), headers=MailjetConfig.DEFAULT_HEADERS)
            response.raise_for_status()
            return MailjetDnsResponse(**response.json()).get_first_item()
        except requests.exceptions.RequestException as e:
            logger.exception(f"Mailjet API error checking DNS records: {e}")
            raise

    def _validate_email_sender(self, sender_id: str):
        """
        Trigger validation of the sender in Mailjet

        Reference: https://dev.mailjet.com/email/reference/sender-addresses-and-domains/sender/#v3_post_sender_sender_ID_validate
        """
        url = f"{MailjetConfig.API_BASE_URL_V3}{MailjetConfig.SENDER_ENDPOINT}/{sender_id}{MailjetConfig.SENDER_VALIDATE_ENDPOINT}"
        try:
            response = requests.post(url, auth=(self.api_key, self.api_secret), headers=MailjetConfig.DEFAULT_HEADERS)
            response.raise_for_status()
            validation_response = MailjetValidationResponse(**response.json())
            return validation_response.errors.get("DNSValidationError") is None
        except requests.exceptions.RequestException as e:
            logger.exception(f"Mailjet API error checking DNS records: {e}")
            raise

    def create_email_domain(self, domain: str, team_id: int):
        """
        Create a new sender domain in Mailjet

        Reference: https://dev.mailjet.com/email/reference/sender-addresses-and-domains/sender/#v3_post_sender
        """
        # Validate the domain contains valid characters for a domain name
        DOMAIN_REGEX = r"(?i)^([a-z0-9]+(-[a-z0-9]+)*\.)+[a-z]{2,}$"
        if not re.match(DOMAIN_REGEX, domain):
            raise exceptions.ValidationError("Please enter a valid domain or subdomain name.")

        sender_domain = f"*@{domain}"

        url = f"{MailjetConfig.API_BASE_URL_V3}{MailjetConfig.SENDER_ENDPOINT}"

        # Use the team ID and domain to create a unique sender name on Mailjet side.
        # This isn't used by PostHog, but can be helpful when looking at senders in the Mailjet console.
        delimited_sender_name = f"{team_id}|{domain}"
        # EmailType = "unknown" as both transactional and campaign emails may be sent from this domain
        payload = {"EmailType": "unknown", "Email": sender_domain, "Name": delimited_sender_name}

        try:
            response = requests.post(
                url, auth=(self.api_key, self.api_secret), headers=MailjetConfig.DEFAULT_HEADERS, json=payload
            )

            if (
                response.status_code == 400
                and "There is an already existing" in response.text
                and "sender with the same email" in response.text
            ):
                return

        except requests.exceptions.RequestException as e:
            logger.exception(f"Mailjet API error creating sender domain: {e}")
            raise

    def verify_email_domain(self, domain: str):
        """
        Verify the email domain by checking DNS records status.
        """
        required_dns_records = self._get_domain_dns_records(domain)
        dns_status_response = self._check_domain_dns_records(domain)
        is_mailjet_validated = self._validate_email_sender(f"*@{domain}")
        overall_status, formatted_dns_records = self._format_dns_records(
            required_dns_records, dns_status_response, is_mailjet_validated
        )

        return {"status": overall_status, "dnsRecords": formatted_dns_records}
