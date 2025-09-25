import re
import logging

from django.conf import settings

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from rest_framework import exceptions

logger = logging.getLogger(__name__)


class SESProvider:
    client: boto3.client

    def __init__(self):
        self.access_key_id = self.get_access_key_id()
        self.secret_access_key = self.get_secret_access_key()
        self.region = self.get_region()
        self.endpoint_url = self.get_endpoint_url()

        logger.info(
            f"Initializing SES client with access key id: {self.access_key_id}, region: {self.region}, endpoint url: {self.endpoint_url}"
        )

        # Initialize SES client
        self.client = boto3.client(
            "ses",
            aws_access_key_id=self.access_key_id,
            aws_secret_access_key=self.secret_access_key,
            region_name=self.region,
            endpoint_url=self.endpoint_url if self.endpoint_url else None,
        )

    @classmethod
    def get_access_key_id(cls) -> str:
        access_key_id = settings.SES_ACCESS_KEY_ID
        if not access_key_id:
            raise ValueError("SES_ACCESS_KEY_ID is not set in environment or settings")
        return access_key_id

    @classmethod
    def get_secret_access_key(cls) -> str:
        secret_access_key = settings.SES_SECRET_ACCESS_KEY
        if not secret_access_key:
            raise ValueError("SES_SECRET_ACCESS_KEY is not set in environment or settings")
        return secret_access_key

    @classmethod
    def get_region(cls) -> str:
        return settings.SES_REGION

    @classmethod
    def get_endpoint_url(cls) -> str | None:
        return settings.SES_ENDPOINT

    def _format_dns_records(self, domain_attributes: dict) -> tuple[str, list[dict]]:
        """
        Format DNS records for domain verification status
        """
        formatted_dns_records = []

        # Check domain verification status
        domain_verification_status = domain_attributes.get("VerificationStatus", "NotStarted")

        # Check DKIM verification status
        dkim_tokens = domain_attributes.get("DkimTokens", [])
        dkim_verification_status = domain_attributes.get("DkimVerificationStatus", "NotStarted")
        dkim_enabled = domain_attributes.get("DkimEnabled", False)

        # Check SPF verification status
        spf_verification_status = domain_attributes.get("SpfVerificationStatus", "NotStarted")

        # Overall status - domain must be verified, and either DKIM or SPF should be successful
        # For SES, domain verification is the primary requirement
        overall_status = "success"

        if (
            domain_verification_status == "Success"
            and dkim_enabled
            and dkim_verification_status == "Success"
            and spf_verification_status == "Success"
        ):
            overall_status = "success"
        else:
            overall_status = "pending"

        # Add domain verification record if not verified
        if domain_verification_status != "Success":
            overall_status = "pending"
            verification_token = domain_attributes.get("VerificationToken")
            if verification_token:
                formatted_dns_records.append(
                    {
                        "type": "domain_verification",
                        "recordType": "TXT",
                        "recordHostname": "_amazonses",
                        "recordValue": verification_token,
                        "status": "pending",
                    }
                )

        # Add DKIM records if DKIM is enabled
        if dkim_enabled and dkim_tokens:
            for token in dkim_tokens:
                formatted_dns_records.append(
                    {
                        "type": "dkim",
                        "recordType": "CNAME",
                        "recordHostname": f"{token}._domainkey",
                        "recordValue": f"{token}.dkim.amazonses.com",
                        "status": "success" if dkim_verification_status == "Success" else "pending",
                    }
                )

        # Add SPF record
        formatted_dns_records.append(
            {
                "type": "spf",
                "recordType": "TXT",
                "recordHostname": "@",
                "recordValue": "v=spf1 include:amazonses.com ~all",
                "status": "success" if spf_verification_status == "Success" else "pending",
            }
        )

        return overall_status, formatted_dns_records

    def create_email_domain(self, domain: str, team_id: int):
        """
        Create a new verified domain in SES

        Reference: https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/ses.html#SES.Client.verify_domain_identity
        """
        # Validate the domain contains valid characters for a domain name
        DOMAIN_REGEX = r"(?i)^([a-z0-9]+(-[a-z0-9]+)*\.)+[a-z]{2,}$"
        if not re.match(DOMAIN_REGEX, domain):
            raise exceptions.ValidationError("Please enter a valid domain or subdomain name.")

        self.client.verify_domain_identity(Domain=domain)

    def enable_dkim_for_domain(self, domain: str):
        """
        Enable DKIM for a domain in SES

        Reference: https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/ses.html#SES.Client.put_identity_dkim_attributes
        """
        try:
            response = self.client.put_identity_dkim_attributes(Identity=domain, DkimEnabled=True)
            logger.info(f"DKIM enabled for domain {domain}")
            return response
        except ClientError as e:
            logger.exception(f"SES API error enabling DKIM for domain: {e}")
            raise
        except BotoCoreError as e:
            logger.exception(f"SES API error enabling DKIM for domain: {e}")
            raise

    def verify_email_domain(self, domain: str, team_id: int):
        """
        Ensure SES v1 domain identity + DKIM for the email's domain and return a response like:

        {
            "status": "pending",
            "dnsRecords": [
                {
                    "type": "spf",
                    "recordType": "TXT",
                    "recordHostname": "@",
                    "recordValue": "v=spf1 include:amazonses.com ~all",
                    "status": "pending",
                }
            ],
        }
        """
        dns_records = []

        # Start/ensure domain verification (TXT at _amazonses.domain) ---
        verification_token = None
        try:
            resp = self.client.verify_domain_identity(Domain=domain)
            verification_token = resp.get("VerificationToken")
        except ClientError as e:
            # If already requested/exists, carry on; SES v1 is idempotent-ish here
            if e.response["Error"]["Code"] not in ("InvalidParameterValue",):
                raise

        if verification_token:
            dns_records.append(
                {
                    "type": "verification",
                    "recordType": "TXT",
                    "recordHostname": f"_amazonses.{domain}",
                    "recordValue": verification_token,
                    "status": "pending",
                }
            )

        #  Start/ensure DKIM (three CNAMEs) ---
        dkim_tokens = []
        try:
            resp = self.client.verify_domain_dkim(Domain=domain)
            dkim_tokens = resp.get("DkimTokens", []) or []
        except ClientError as e:
            if e.response["Error"]["Code"] not in ("InvalidParameterValue",):
                raise

        for t in dkim_tokens:
            dns_records.append(
                {
                    "type": "dkim",
                    "recordType": "CNAME",
                    "recordHostname": f"{t}._domainkey.{domain}",
                    "recordValue": f"{t}.dkim.amazonses.com",
                    "status": "pending",
                }
            )

        dns_records.append(
            {
                "type": "spf",
                "recordType": "TXT",
                "recordHostname": "@",
                "recordValue": "v=spf1 include:amazonses.com ~all",
                "status": "pending",
            }
        )

        # Current verification / DKIM statuses to compute overall status & per-record statuses ---
        try:
            id_attrs = self.client.get_identity_verification_attributes(Identities=[domain])
            verification_status = (
                id_attrs["VerificationAttributes"].get(domain, {}).get("VerificationStatus", "Unknown")
            )
        except ClientError:
            verification_status = "Unknown"

        try:
            dkim_attrs = self.client.get_identity_dkim_attributes(Identities=[domain])
            dkim_status = dkim_attrs["DkimAttributes"].get(domain, {}).get("DkimVerificationStatus", "Unknown")
        except ClientError:
            dkim_status = "Unknown"

        # Normalize overall status
        if verification_status == "Success" and dkim_status == "Success":
            overall = "success"
        elif "Failed" in (verification_status, dkim_status):
            overall = "failed"
        else:
            overall = "pending"

        # Upgrade per-record statuses if SES reports success
        # - Domain verification TXT is considered verified when VerificationStatus == Success
        # - DKIM CNAMEs considered verified when DkimVerificationStatus == Success
        if verification_status == "Success":
            for r in dns_records:
                if r["type"] == "verification":
                    r["status"] = "success"
        if dkim_status == "Success":
            for r in dns_records:
                if r["type"] == "dkim":
                    r["status"] = "success"

        # If MAIL FROM attrs said Success earlier, MX already marked verified

        return {
            "status": overall,
            "dnsRecords": dns_records if overall != "success" else [],
        }

    def delete_identity(self, identity: str):
        """
        Delete an identity from SES
        """
        try:
            self.client.delete_identity(Identity=identity)
            logger.info(f"Identity {identity} deleted from SES")
        except (ClientError, BotoCoreError) as e:
            logger.exception(f"SES API error deleting identity: {e}")
            raise
