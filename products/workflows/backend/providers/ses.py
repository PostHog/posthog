import re
import logging

from django.conf import settings

import boto3
import posthoganalytics
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

    def create_email_domain(self, domain: str, mail_from_subdomain: str, team_id: int):
        # NOTE: For sesv1, domain Identity creation is done through verification
        self.verify_email_domain(domain, mail_from_subdomain, team_id)

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

    def verify_email_domain(self, domain: str, mail_from_subdomain: str, team_id: int):
        mail_from_subdomain_enabled = posthoganalytics.feature_enabled(
            "workflows-mail-from-domain",
            str(team_id),
            groups={"project": str(team_id)},
            group_properties={
                "project": {
                    "id": str(team_id),
                }
            },
            send_feature_flag_events=False,
        )

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
                "type": "verification",
                "recordType": "TXT",
                "recordHostname": "@",
                "recordValue": "v=spf1 include:amazonses.com ~all",
                "status": "pending",
            }
        )

        # Start/ensure MAIL FROM setup (MX + TXT) ---
        if mail_from_subdomain_enabled:
            try:
                resp = self.ses_client.set_identity_mail_from_domain(
                    Identity=domain,
                    MailFromDomain=f"{mail_from_subdomain}.{domain}",
                    BehaviorOnMXFailure="UseDefaultValue",
                )
            except ClientError as e:
                if e.response["Error"]["Code"] not in ("InvalidParameterValue",):
                    raise

            ses_region = getattr(settings, "SES_REGION", "us-east-1")

            dns_records.append(
                {
                    "type": "mail_from",
                    "recordType": "MX",
                    "recordHostname": f"{mail_from_subdomain}.{domain}",
                    "recordValue": f"feedback-smtp.{ses_region}.amazonses.com",
                    "status": "pending",
                }
            )
            dns_records.append(
                {
                    "type": "mail_from",
                    "recordType": "TXT",
                    "recordHostname": f"{mail_from_subdomain}.{domain}",
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

        if mail_from_subdomain_enabled:
            try:
                mail_from_attrs = self.ses_client.get_identity_mail_from_domain_attributes(Identities=[domain])
                mail_from_status = (
                    mail_from_attrs["MailFromDomainAttributes"].get(domain, {}).get("MailFromDomainStatus", "Unknown")
                )
            except ClientError:
                mail_from_status = "Unknown"

        all_statuses = [verification_status, dkim_status]
        if mail_from_subdomain_enabled:
            all_statuses.append(mail_from_status)

        # Normalize overall status
        if (
            verification_status == "Success"
            and dkim_status == "Success"
            and (not mail_from_subdomain_enabled or mail_from_status == "Success")
        ):
            overall = "success"
        elif "Failed" in all_statuses:
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
        if mail_from_subdomain_enabled and mail_from_status == "Success":
            for r in dns_records:
                if r["type"] == "mail_from":
                    r["status"] = "success"

        return {
            "status": overall,
            "dnsRecords": dns_records,
        }

    def update_mail_from_subdomain(self, domain: str, mail_from_subdomain: str):
        """
        Update the MAIL FROM subdomain for a given identity
        """
        try:
            self.ses_client.set_identity_mail_from_domain(
                Identity=domain,
                MailFromDomain=f"{mail_from_subdomain}.{domain}",
                BehaviorOnMXFailure="UseDefaultValue",
            )
            logger.info(f"MAIL FROM domain for {domain} updated to {mail_from_subdomain}.{domain}")
        except (ClientError, BotoCoreError) as e:
            logger.exception(f"SES API error updating MAIL FROM domain: {e}")
            raise

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
