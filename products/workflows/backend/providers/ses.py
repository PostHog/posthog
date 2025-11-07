import re
import logging

from django.conf import settings

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from rest_framework import exceptions

logger = logging.getLogger(__name__)


class SESProvider:
    def __init__(self):
        # Initialize the boto3 clients
        self.sts_client = boto3.client(
            "sts",
            aws_access_key_id=settings.SES_ACCESS_KEY_ID,
            aws_secret_access_key=settings.SES_SECRET_ACCESS_KEY,
            region_name=settings.SES_REGION,
        )
        self.ses_client = boto3.client(
            "ses",
            aws_access_key_id=settings.SES_ACCESS_KEY_ID,
            aws_secret_access_key=settings.SES_SECRET_ACCESS_KEY,
            region_name=settings.SES_REGION,
        )
        self.ses_v2_client = boto3.client(
            "sesv2",
            aws_access_key_id=settings.SES_ACCESS_KEY_ID,
            aws_secret_access_key=settings.SES_SECRET_ACCESS_KEY,
            region_name=settings.SES_REGION,
        )

    def create_email_domain(self, domain: str, team_id: int):
        # NOTE: For sesv1, domain Identity creation is done through verification
        self.verify_email_domain(domain, team_id)

        # Create a tenant for the domain if not exists
        tenant_name = f"team-{team_id}"
        try:
            self.ses_v2_client.create_tenant(TenantName=tenant_name, Tags=[{"Key": "team_id", "Value": str(team_id)}])
        except ClientError as e:
            if e.response["Error"]["Code"] != "AlreadyExistsException":
                raise

        # Associate the new domain identity with the tenant
        try:
            self.ses_v2_client.create_tenant_resource_association(
                TenantName=tenant_name,
                ResourceArn=f"arn:aws:ses:{settings.SES_REGION}:{self.sts_client.get_caller_identity()['Account']}:identity/{domain}",
            )
        except ClientError as e:
            if e.response["Error"]["Code"] != "AlreadyExistsException":
                raise

    def verify_email_domain(self, domain: str, team_id: int):
        # Validate the domain contains valid characters for a domain name
        DOMAIN_REGEX = r"(?i)^([a-z0-9]+(-[a-z0-9]+)*\.)+[a-z]{2,}$"
        if not re.match(DOMAIN_REGEX, domain):
            raise exceptions.ValidationError("Please enter a valid domain or subdomain name.")

        dns_records = []

        # Start/ensure domain verification (TXT at _amazonses.domain) ---
        verification_token = None
        try:
            resp = self.ses_client.verify_domain_identity(Domain=domain)
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
            resp = self.ses_client.verify_domain_dkim(Domain=domain)
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
            id_attrs = self.ses_client.get_identity_verification_attributes(Identities=[domain])
            verification_status = (
                id_attrs["VerificationAttributes"].get(domain, {}).get("VerificationStatus", "Unknown")
            )
        except ClientError:
            verification_status = "Unknown"

        try:
            dkim_attrs = self.ses_client.get_identity_dkim_attributes(Identities=[domain])
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
            self.ses_client.delete_identity(Identity=identity)
            logger.info(f"Identity {identity} deleted from SES")
        except (ClientError, BotoCoreError) as e:
            logger.exception(f"SES API error deleting identity: {e}")
            raise
