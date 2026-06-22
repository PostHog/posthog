import re
import logging
from collections.abc import Iterable
from functools import cached_property
from typing import TYPE_CHECKING, Any

from django.conf import settings

import boto3
import dns.name
import dns.resolver
from botocore.exceptions import BotoCoreError, ClientError
from rest_framework import exceptions

if TYPE_CHECKING:
    from types_boto3_ses.client import SESClient
    from types_boto3_sesv2.client import SESV2Client

logger = logging.getLogger(__name__)

# Default MAIL FROM subdomain used when the caller doesn't supply one. Kept in sync with the
# default in posthog/models/integration.py so a blank value never reaches SES as ".<domain>".
DEFAULT_MAIL_FROM_SUBDOMAIN = "feedback"

# A MAIL FROM subdomain must be a single valid DNS label (no dots, spaces, or leading hyphen).
MAIL_FROM_SUBDOMAIN_REGEX = r"(?i)^[a-z0-9]+(-[a-z0-9]+)*$"


class SESProvider:
    ses_client: "SESClient"
    ses_v2_client: "SESV2Client"

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

    def _tenant_name_for_team(self, team_id: int) -> str:
        return f"team-{team_id}"

    def _normalize_mail_from_subdomain(self, mail_from_subdomain: str) -> str:
        """
        Coerce a MAIL FROM subdomain into a valid single DNS label.

        The API serializer allows a blank `mail_from_subdomain`, and a blank value would
        otherwise be interpolated into `f"{subdomain}.{domain}"` as `.<domain>` — which SES
        rejects with `InvalidParameterValue: Invalid MAIL FROM domain name <.domain>`. Treat
        blank as the default and reject anything that isn't a clean label with a clear error.
        """
        subdomain = (mail_from_subdomain or "").strip().strip(".").lower()
        if not subdomain:
            return DEFAULT_MAIL_FROM_SUBDOMAIN
        if not re.match(MAIL_FROM_SUBDOMAIN_REGEX, subdomain):
            raise exceptions.ValidationError(
                "Please enter a valid MAIL FROM subdomain using only letters, digits, and hyphens."
            )
        return subdomain

    @cached_property
    def _aws_account_id(self) -> str:
        return self.sts_client.get_caller_identity()["Account"]

    def _identity_arn(self, domain: str) -> str:
        return f"arn:aws:ses:{settings.SES_REGION}:{self._aws_account_id}:identity/{domain}"

    def _list_identity_tenants(self, domain: str) -> set[str]:
        try:
            resp = self.ses_v2_client.list_resource_tenants(ResourceArn=self._identity_arn(domain))
        except ClientError as e:
            if e.response["Error"]["Code"] == "NotFoundException":
                return set()
            raise
        # `ResourceTenants` is a required field on the response shape — read it with
        # subscript access so a future SDK rename fails the type checker, not prod.
        # `TenantName` per the SDK is `NotRequired`, so `.get()` is the correct access.
        return {name for t in resp["ResourceTenants"] if (name := t.get("TenantName"))}

    def create_email_domain(
        self,
        domain: str,
        mail_from_subdomain: str,
        team_id: int,
        org_team_ids: Iterable[int] | None = None,
    ):
        expected_tenant = self._tenant_name_for_team(team_id)
        friendly_tenants = {self._tenant_name_for_team(t) for t in (org_team_ids or [team_id])}
        foreign_tenants = self._list_identity_tenants(domain) - friendly_tenants
        if foreign_tenants:
            raise exceptions.ValidationError(
                "This domain is already associated with another organization in SES. "
                "Please contact support if you believe this is a mistake."
            )

        # NOTE: For sesv1, domain Identity creation is done through verification
        self.verify_email_domain(domain, mail_from_subdomain, team_id)

        # Create a tenant for the domain if not exists
        try:
            self.ses_v2_client.create_tenant(
                TenantName=expected_tenant, Tags=[{"Key": "team_id", "Value": str(team_id)}]
            )
        except ClientError as e:
            if e.response["Error"]["Code"] != "AlreadyExistsException":
                raise

        # Associate the new domain identity with the tenant
        try:
            self.ses_v2_client.create_tenant_resource_association(
                TenantName=expected_tenant,
                ResourceArn=self._identity_arn(domain),
            )
        except ClientError as e:
            if e.response["Error"]["Code"] != "AlreadyExistsException":
                raise

    def verify_email_domain(self, domain: str, mail_from_subdomain: str, team_id: int):
        # Validate the domain contains valid characters for a domain name
        DOMAIN_REGEX = r"(?i)^([a-z0-9]+(-[a-z0-9]+)*\.)+[a-z]{2,}$"
        if not re.match(DOMAIN_REGEX, domain):
            raise exceptions.ValidationError("Please enter a valid domain or subdomain name.")

        mail_from_subdomain = self._normalize_mail_from_subdomain(mail_from_subdomain)

        dns_records: list[dict[str, Any]] = []

        # Start/ensure domain verification (TXT at _amazonses.domain) ---
        verification_token: str | None = None
        try:
            verify_resp = self.ses_client.verify_domain_identity(Domain=domain)
            verification_token = verify_resp["VerificationToken"]
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
            dkim_resp = self.ses_client.verify_domain_dkim(Domain=domain)
            dkim_tokens = dkim_resp["DkimTokens"]
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
        try:
            self.ses_client.set_identity_mail_from_domain(
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
                "priority": 10,
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

        # DMARC — AWS SES has no method to check its presence, so we do a direct DNS
        # lookup further below and include the result in the overall status.
        dns_records.append(
            {
                "type": "dmarc",
                "recordType": "TXT",
                "recordHostname": f"_dmarc.{domain}",
                "recordValue": "v=DMARC1; p=none;",
                "status": "pending",
            }
        )

        # Current verification / DKIM statuses to compute overall status & per-record statuses ---
        verification_status: str = "Unknown"
        try:
            id_attrs = self.ses_client.get_identity_verification_attributes(Identities=[domain])
            id_for_domain = id_attrs["VerificationAttributes"].get(domain)
            if id_for_domain is not None:
                verification_status = id_for_domain["VerificationStatus"]
        except ClientError:
            pass

        dkim_status: str = "Unknown"
        try:
            dkim_attrs = self.ses_client.get_identity_dkim_attributes(Identities=[domain])
            dkim_for_domain = dkim_attrs["DkimAttributes"].get(domain)
            if dkim_for_domain is not None:
                dkim_status = dkim_for_domain["DkimVerificationStatus"]
        except ClientError:
            pass

        mail_from_status: str = "Unknown"
        try:
            mail_from_attrs = self.ses_client.get_identity_mail_from_domain_attributes(Identities=[domain])
            mail_from_for_domain = mail_from_attrs["MailFromDomainAttributes"].get(domain)
            if mail_from_for_domain is not None:
                mail_from_status = mail_from_for_domain["MailFromDomainStatus"]
        except ClientError:
            pass

        # DMARC: check via direct DNS lookup since AWS SES doesn't track it
        dmarc_status = "Pending"
        dmarc_record_value: str | None = None
        try:
            resolver = dns.resolver.Resolver()
            resolver.lifetime = 5  # seconds — keep the request path responsive
            answers = resolver.resolve(f"_dmarc.{domain}", "TXT")
            for rdata in answers:
                txt_value = "".join(s.decode("utf-8") if isinstance(s, bytes) else s for s in rdata.strings)
                if txt_value.strip().lower().startswith("v=dmarc1"):
                    dmarc_status = "Success"
                    dmarc_record_value = txt_value.strip()
                    break
        except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer, dns.resolver.NoNameservers, dns.resolver.Timeout):
            pass  # No DMARC record found — fall back to "Pending" status
        except Exception:
            logger.exception("Unexpected error during DMARC lookup for %s", domain)

        all_statuses = [verification_status, dkim_status, mail_from_status]

        # Normalize overall status
        if (
            verification_status == "Success"
            and dkim_status == "Success"
            and mail_from_status == "Success"
            and dmarc_status == "Success"
        ):
            overall = "success"
        elif "Failed" in all_statuses:
            overall = "failed"
        else:
            overall = "pending"

        if overall == "success":
            expected_tenant = self._tenant_name_for_team(team_id)
            if expected_tenant not in self._list_identity_tenants(domain):
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
        else:
            # SES reports aggregate DKIM status, but individual CNAMEs may already
            # be present.  Do per-record DNS lookups so the UI can show which
            # specific records are still missing.
            resolver = dns.resolver.Resolver()
            resolver.lifetime = 5
            for r in dns_records:
                if r["type"] != "dkim":
                    continue
                try:
                    answers = resolver.resolve(r["recordHostname"], "CNAME")
                    expected = dns.name.from_text(r["recordValue"])
                    for rdata in answers:
                        # Use dnspython Name comparison, case-insensitive per RFC 1035
                        if rdata.target == expected:
                            r["status"] = "success"
                            break
                except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer, dns.resolver.NoNameservers, dns.resolver.Timeout):
                    pass
                except Exception:
                    logger.exception("Unexpected error during DKIM CNAME lookup for %s", r["recordHostname"])
        if mail_from_status == "Success":
            for r in dns_records:
                if r["type"] == "mail_from":
                    r["status"] = "success"
        if dmarc_status == "Success":
            for r in dns_records:
                if r["type"] == "dmarc":
                    r["status"] = "success"
                    if dmarc_record_value:
                        r["recordValue"] = dmarc_record_value

        return {
            "status": overall,
            "dnsRecords": dns_records,
        }

    def update_mail_from_subdomain(self, domain: str, mail_from_subdomain: str):
        """
        Update the MAIL FROM subdomain for a given identity
        """
        mail_from_subdomain = self._normalize_mail_from_subdomain(mail_from_subdomain)
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

    def _dissociate_identity_tenants(self, domain: str) -> None:
        """
        Remove every tenant resource association for an identity.

        SES refuses `DeleteIdentity` while the identity still has tenant
        associations (created by `create_email_domain`), so these must be torn
        down first. The per-team tenant itself is left in place — it is harmless
        when empty and may be reused by other domains owned by the same team.
        """
        for tenant in self._list_identity_tenants(domain):
            try:
                self.ses_v2_client.delete_tenant_resource_association(
                    TenantName=tenant,
                    ResourceArn=self._identity_arn(domain),
                )
            except ClientError as e:
                # If the association is already gone we have nothing to clean up — that
                # still unblocks deletion, so only re-raise on unexpected errors.
                if e.response["Error"]["Code"] != "NotFoundException":
                    raise

    def delete_identity(self, identity: str):
        """
        Delete an identity from SES
        """
        # Tenant associations block DeleteIdentity, so dissociate them first. Kept outside the
        # try below so a dissociation failure propagates with its own context rather than being
        # logged as a DeleteIdentity error that never ran.
        self._dissociate_identity_tenants(identity)
        try:
            self.ses_client.delete_identity(Identity=identity)
            logger.info(f"Identity {identity} deleted from SES")
        except (ClientError, BotoCoreError) as e:
            logger.exception(f"SES API error deleting identity: {e}")
            raise
