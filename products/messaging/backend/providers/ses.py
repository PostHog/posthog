import re
import logging

from django.conf import settings

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from rest_framework import exceptions

logger = logging.getLogger(__name__)


class SESProvider:
    def __init__(self):
        self.access_key_id = self.get_access_key_id()
        self.secret_access_key = self.get_secret_access_key()
        self.region = self.get_region()
        self.endpoint_url = self.get_endpoint_url()

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

    def create_email_domain(self, domain: str, team_id: int):
        # NOTE: For sesv1 creation is done through verification
        self.verify_email_domain(domain, team_id)

    def verify_email_domain(self, domain: str, team_id: int):
        # Validate the domain contains valid characters for a domain name
        DOMAIN_REGEX = r"(?i)^([a-z0-9]+(-[a-z0-9]+)*\.)+[a-z]{2,}$"
        if not re.match(DOMAIN_REGEX, domain):
            raise exceptions.ValidationError("Please enter a valid domain or subdomain name.")

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
        dkim_tokens: list[str] = []
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
