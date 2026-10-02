import re
import logging
from collections import defaultdict
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from functools import cached_property
from itertools import batched
from time import monotonic
from typing import TYPE_CHECKING, Any, Literal, cast

from django.conf import settings
from django.core.cache import cache

import boto3
import dns.name
import dns.resolver
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from rest_framework import exceptions

from posthog.dataclasses import frozen
from posthog.exceptions_capture import capture_exception

from products.workflows.backend.facade.contracts import (
    EmailDomainCheck,
    EmailDomainDnsRecord,
    EmailDomainStatusRecord,
    EmailDomainVerification,
    EmailDomainVerificationStatus,
    EmailProviderUnavailableError,
)
from products.workflows.backend.facade.enums import (
    EmailDomainSetupRecordKind,
    EmailDomainSetupRecordStatus,
    EmailDomainSetupStatus,
)
from products.workflows.backend.services.email_domain_dns import find_published_records
from products.workflows.backend.services.email_domain_status import build_email_domain_check, build_email_domain_records

if TYPE_CHECKING:
    from types_boto3_ses.client import SESClient
    from types_boto3_sesv2.client import SESV2Client
    from types_boto3_sesv2.type_defs import RecommendationTypeDef

logger = logging.getLogger(__name__)

AWS_ACCOUNT_ID_CACHE_KEY = "workflows:ses:aws_account_id"
AWS_ACCOUNT_ID_CACHE_SECONDS = 24 * 60 * 60

# DELIVERY_COMPLAINT is the complaint denominator rather than SEND, because AWS defines it as
# deliveries excluding recipients at ISPs it has no feedback-loop agreement with.
# TRANSIENT_BOUNCE is queried because without it a provider that defers rather than rejects reads
# as a low delivery rate with no bounces, and nothing accounts for the difference.
ISP_METRICS: tuple[str, ...] = (
    "SEND",
    "DELIVERY",
    "PERMANENT_BOUNCE",
    "TRANSIENT_BOUNCE",
    "COMPLAINT",
    "DELIVERY_COMPLAINT",
)

# Subject for the identity-wide queries, which carry no ISP dimension. They give the denominator
# the per-provider rows are subtracted from.
ISP_IDENTITY_TOTAL = "__identity_total__"

# Reported provider name for that subtraction. SES has a catch-all bucket for recipients it cannot
# attribute, and rejects its name ("Unknown ISP") as a dimension value with BadRequestException, so
# the only way to show that volume is to derive it.
ISP_OTHER = "__other__"

# SES caps a BatchGetMetricData request at ten queries.
METRIC_QUERY_BATCH_SIZE = 10

# Bounds one metric call. Also the amount of budget a call needs before it may start, below.
METRIC_CONNECT_TIMEOUT_SECONDS = 2
METRIC_READ_TIMEOUT_SECONDS = 5
METRIC_CALL_WORST_CASE_SECONDS = METRIC_CONNECT_TIMEOUT_SECONDS + METRIC_READ_TIMEOUT_SECONDS

# The breakdown runs inside a web request, and the fan-out is one query per domain, provider and
# metric, issued in sequence. Without a ceiling an unresponsive SES holds a worker for minutes on
# boto3's 60 second default. Past the budget the caller gets no breakdown, which is the same
# degradation as any other SES failure and better than partial counts, whose rates would be wrong.
# The budget covers every call the breakdown makes, ranking included, and a call starts only with
# its worst case still inside it — so the ceiling holds even when SES answers slowly.
METRIC_QUERY_BUDGET_SECONDS = 20

RECOMMENDATIONS_PAGE_SIZE = 100

# The account findings walk runs in a background task, so it can wait out SES throttling. Adaptive
# mode adds a client-side rate limiter that slows the following pages after a throttle response.
RECOMMENDATIONS_RETRY_CONFIG = Config(retries={"mode": "adaptive", "max_attempts": 8})


@frozen
class IspSendingMetrics:
    isp: str
    emails_sent: int
    # None when the metric behind the rate could not be loaded. A failed query returns an empty
    # series, which is arithmetically indistinguishable from a real zero — and a 0% complaint rate
    # reads as a healthy provider. Unknown is reported as unknown rather than as a number.
    delivery_rate: float | None
    bounce_rate: float | None
    transient_bounce_rate: float | None
    # Also None when the provider runs no feedback loop, or when nothing was delivered to measure
    # complaints against: both are "no rate exists", as against "we could not load it".
    complaint_rate: float | None
    # The deliveries complaint_rate divides by, which is far smaller than emails_sent. A caller
    # judging whether the rate rests on enough volume has to weigh it against this, not against
    # what was sent.
    complaint_base: int
    # Rates whose metric AWS did not return, so the reader can be told the number is missing rather
    # than shown one. A null rate that is not listed here has no value to state at all.
    unavailable: tuple[str, ...] = ()


@frozen
class IspMetric:
    """One SES metric for one mailbox provider: what a single query asks for, and what indexes its answer."""

    isp: str
    metric: str


@frozen
class IspQueryPlan:
    """The queries for a breakdown, and the index from query id back to what each one asked."""

    queries: list[dict[str, Any]]
    subjects: dict[str, IspMetric]


@frozen
class IspBatchAnswer:
    """What one batch produced: the responses SES returned, and the subjects it refused outright."""

    responses: tuple[Mapping[str, Any], ...]
    rejected: frozenset[IspMetric]


@frozen
class IspMetricSeries:
    """Daily counts per provider and metric, and the subjects SES returned no answer for."""

    buckets: Mapping[IspMetric, Mapping[str, int]]
    failed: frozenset[IspMetric]


def _build_isp_queries(domains: Sequence[str], isps: Sequence[str], start: datetime, end: datetime) -> IspQueryPlan:
    """
    The BatchGetMetricData queries for a breakdown, and an index from query id to what it asked.

    Dimensions filter rather than group, and the response echoes only the query id, so a
    per-provider breakdown needs one query per (domain, provider, metric) and a local index back
    to what each id asked for.
    """
    queries: list[dict[str, Any]] = []
    subjects: dict[str, IspMetric] = {}
    for domain in domains:
        for isp in (*isps, ISP_IDENTITY_TOTAL):
            for metric in ISP_METRICS:
                query_id = f"q{len(queries)}"
                subjects[query_id] = IspMetric(isp=isp, metric=metric)
                queries.append(
                    {
                        "Id": query_id,
                        "Namespace": "VDM",
                        "Metric": metric,
                        "Dimensions": (
                            {"EMAIL_IDENTITY": domain}
                            if isp == ISP_IDENTITY_TOTAL
                            else {"EMAIL_IDENTITY": domain, "ISP": isp}
                        ),
                        "StartDate": start,
                        "EndDate": end,
                    }
                )
    return IspQueryPlan(queries=queries, subjects=subjects)


def _isp_rows_from_series(isps: Sequence[str], series: IspMetricSeries) -> list[IspSendingMetrics]:
    """Per-provider rows derived from the collected series, busiest provider first."""
    buckets, failed = series.buckets, series.failed
    rows: list[IspSendingMetrics] = []
    for isp in isps:
        if IspMetric(isp=isp, metric="SEND") in failed:
            # Without the denominator there is no row to build: volume is unknown and every
            # rate divides by it. This is the one case where the provider is dropped.
            continue
        sent_by_date = buckets.get(IspMetric(isp=isp, metric="SEND"), {})
        emails_sent = sum(sent_by_date.values())
        if emails_sent == 0:
            continue
        delivered_by_date = buckets.get(IspMetric(isp=isp, metric="DELIVERY"), {})
        bounced_by_date = buckets.get(IspMetric(isp=isp, metric="PERMANENT_BOUNCE"), {})
        deferred_by_date = buckets.get(IspMetric(isp=isp, metric="TRANSIENT_BOUNCE"), {})
        delivery_failed = IspMetric(isp=isp, metric="DELIVERY") in failed
        bounce_failed = IspMetric(isp=isp, metric="PERMANENT_BOUNCE") in failed
        transient_failed = IspMetric(isp=isp, metric="TRANSIENT_BOUNCE") in failed
        complaint_failed = (
            IspMetric(isp=isp, metric="COMPLAINT") in failed
            or IspMetric(isp=isp, metric="DELIVERY_COMPLAINT") in failed
        )
        complaint_base = sum(buckets.get(IspMetric(isp=isp, metric="DELIVERY_COMPLAINT"), {}).values())
        rows.append(
            IspSendingMetrics(
                isp=isp,
                emails_sent=emails_sent,
                # Feedback can arrive after the window closes, so a rate can exceed its
                # denominator at the boundary. Clamp, as the project-wide rates do.
                delivery_rate=None if delivery_failed else min(1.0, sum(delivered_by_date.values()) / emails_sent),
                bounce_rate=None if bounce_failed else min(1.0, sum(bounced_by_date.values()) / emails_sent),
                transient_bounce_rate=(
                    None if transient_failed else min(1.0, sum(deferred_by_date.values()) / emails_sent)
                ),
                complaint_rate=(
                    None
                    if complaint_failed or not complaint_base
                    else min(
                        1.0, sum(buckets.get(IspMetric(isp=isp, metric="COMPLAINT"), {}).values()) / complaint_base
                    )
                ),
                complaint_base=0 if complaint_failed else complaint_base,
                unavailable=tuple(
                    name
                    for name, missing in (
                        ("delivery", delivery_failed),
                        ("bounce", bounce_failed),
                        ("transient_bounce", transient_failed),
                        ("complaint", complaint_failed),
                    )
                    if missing
                ),
            )
        )

    other = _other_provider_row(isps, series)
    if other is not None:
        rows.append(other)

    rows.sort(key=lambda row: -row.emails_sent)
    return rows


def _other_provider_row(isps: Sequence[str], series: IspMetricSeries) -> IspSendingMetrics | None:
    """
    The volume a domain sent that no named provider accounts for.

    Named providers rarely cover everything a domain sends. The rest lands in a bucket SES will not
    let us query by name, so the row is the identity-wide total minus the named providers. Without
    it the table drops that volume without saying so, and on some domains it is most of the mail.

    Returns None when the subtraction would be unsound. A named provider whose SEND query failed
    has no counts to subtract, so its volume would surface here as unattributed.
    """
    if any(
        IspMetric(isp=isp, metric=metric) in series.failed
        for metric in ISP_METRICS
        for isp in (*isps, ISP_IDENTITY_TOTAL)
    ):
        return None

    def remainder(metric: str) -> dict[str, int]:
        left = dict(series.buckets.get(IspMetric(isp=ISP_IDENTITY_TOTAL, metric=metric), {}))
        for isp in isps:
            for date, value in series.buckets.get(IspMetric(isp=isp, metric=metric), {}).items():
                left[date] = left.get(date, 0) - value
        # A negative remainder means the named rows already cover the day, so there is nothing left
        # to report. Feedback arriving late can also push one past its own total.
        return {date: value for date, value in left.items() if value > 0}

    sent_by_date = remainder("SEND")
    emails_sent = sum(sent_by_date.values())
    if emails_sent == 0:
        return None

    delivered_by_date = remainder("DELIVERY")
    bounced_by_date = remainder("PERMANENT_BOUNCE")
    deferred_by_date = remainder("TRANSIENT_BOUNCE")
    complaint_base = sum(remainder("DELIVERY_COMPLAINT").values())
    return IspSendingMetrics(
        isp=ISP_OTHER,
        emails_sent=emails_sent,
        delivery_rate=min(1.0, sum(delivered_by_date.values()) / emails_sent),
        bounce_rate=min(1.0, sum(bounced_by_date.values()) / emails_sent),
        transient_bounce_rate=min(1.0, sum(deferred_by_date.values()) / emails_sent),
        complaint_rate=(
            None if not complaint_base else min(1.0, sum(remainder("COMPLAINT").values()) / complaint_base)
        ),
        complaint_base=complaint_base,
    )


_LegacyRecordPurpose = Literal["verification", "dkim", "mail_from", "dmarc"]
_LegacyRecordType = Literal["TXT", "CNAME", "MX"]

_LEGACY_RECORD_PURPOSES: dict[EmailDomainSetupRecordKind, _LegacyRecordPurpose] = {
    EmailDomainSetupRecordKind.VERIFICATION: "verification",
    EmailDomainSetupRecordKind.SPF: "verification",
    EmailDomainSetupRecordKind.DKIM: "dkim",
    EmailDomainSetupRecordKind.MAIL_FROM_MX: "mail_from",
    EmailDomainSetupRecordKind.MAIL_FROM_SPF: "mail_from",
    EmailDomainSetupRecordKind.DMARC: "dmarc",
}


def _legacy_dns_record(record: EmailDomainStatusRecord) -> EmailDomainDnsRecord:
    legacy: EmailDomainDnsRecord = {
        "type": _LEGACY_RECORD_PURPOSES[record.kind],
        "recordType": cast(_LegacyRecordType, record.type.value),
        "recordHostname": "@" if record.kind == EmailDomainSetupRecordKind.SPF else record.hostname,
        "recordValue": record.value,
        "status": "pending",
    }
    if record.priority is not None:
        legacy["priority"] = record.priority
    return legacy


_UNKNOWN = "Unknown"


@frozen
class _SESIdentityState:
    """The SES v1 identity attributes. A status is "Unknown" when SES has no attribute for the domain."""

    verification_status: str
    verification_token: str | None
    dkim_status: str
    dkim_tokens: tuple[str, ...]
    mail_from_status: str
    mail_from_domain: str | None

    @classmethod
    def unknown(cls) -> "_SESIdentityState":
        return cls(
            verification_status=_UNKNOWN,
            verification_token=None,
            dkim_status=_UNKNOWN,
            dkim_tokens=(),
            mail_from_status=_UNKNOWN,
            mail_from_domain=None,
        )

    # SES keeps one MAIL FROM domain per identity, and senders on the same domain can ask for
    # different ones. The status SES reports belongs to whichever was set last.
    def for_mail_from_domain(self, mail_from_domain: str) -> "_SESIdentityState":
        if self.mail_from_domain == mail_from_domain:
            return self
        return replace(self, mail_from_status=_UNKNOWN)

    @property
    def statuses(self) -> frozenset[str]:
        return frozenset((self.verification_status, self.dkim_status, self.mail_from_status))

    def is_ready(self, *, dmarc_published: bool) -> bool:
        return dmarc_published and all(status == "Success" for status in self.statuses)

    def setup_status(self, *, is_ready: bool) -> EmailDomainSetupStatus:
        if is_ready:
            return EmailDomainSetupStatus.VERIFIED
        if "Failed" in self.statuses:
            return EmailDomainSetupStatus.FAILED
        if "TemporaryFailure" in self.statuses:
            return EmailDomainSetupStatus.TEMPORARY_FAILURE
        return EmailDomainSetupStatus.PENDING

    def record_status(self, record: EmailDomainStatusRecord, *, published: bool) -> EmailDomainSetupRecordStatus:
        if self._is_verified(record.kind, published=published):
            return EmailDomainSetupRecordStatus.VERIFIED
        return EmailDomainSetupRecordStatus.FOUND if published else EmailDomainSetupRecordStatus.PENDING

    def _is_verified(self, kind: EmailDomainSetupRecordKind, *, published: bool) -> bool:
        match kind:
            case EmailDomainSetupRecordKind.VERIFICATION:
                return self.verification_status == "Success"
            case EmailDomainSetupRecordKind.DKIM:
                return self.dkim_status == "Success"
            case EmailDomainSetupRecordKind.MAIL_FROM_MX:
                return self.mail_from_status == "Success"
            # SES checks only the MX record of the MAIL FROM domain, so its success says nothing about the SPF record.
            case EmailDomainSetupRecordKind.MAIL_FROM_SPF:
                return published and self.mail_from_status == "Success"
            case EmailDomainSetupRecordKind.DMARC:
                return published
            case _:
                return False


# Throttling is SES pacing a busy account. The next poll retries it, so reporting it adds only noise.
def _is_throttling(error: Exception) -> bool:
    return isinstance(error, ClientError) and error.response["Error"]["Code"] in ("Throttling", "ThrottlingException")


class SESProvider:
    ses_client: "SESClient"
    ses_v2_client: "SESV2Client"
    ses_v2_metrics_client: "SESV2Client"
    ses_v2_recommendations_client: "SESV2Client"

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
        # Separate client for the metric fan-out only, so bounding it cannot slow identity and
        # tenant calls, which are allowed to take longer.
        self.ses_v2_metrics_client = boto3.client(
            "sesv2",
            aws_access_key_id=settings.SES_ACCESS_KEY_ID,
            aws_secret_access_key=settings.SES_SECRET_ACCESS_KEY,
            region_name=settings.SES_REGION,
            config=Config(
                connect_timeout=METRIC_CONNECT_TIMEOUT_SECONDS,
                read_timeout=METRIC_READ_TIMEOUT_SECONDS,
                retries={"max_attempts": 1},
            ),
        )
        self.ses_v2_recommendations_client = boto3.client(
            "sesv2",
            aws_access_key_id=settings.SES_ACCESS_KEY_ID,
            aws_secret_access_key=settings.SES_SECRET_ACCESS_KEY,
            region_name=settings.SES_REGION,
            config=RECOMMENDATIONS_RETRY_CONFIG,
        )

    def _tenant_name_for_team(self, team_id: int) -> str:
        return f"team-{team_id}"

    def get_tenant_reputation(self, team_id: int) -> dict[str, Any] | None:
        """
        Sending status and open reputation findings for the team's SES tenant, or None when the
        tenant doesn't exist. AWS judges tenant reputation from signals we can't see (mailbox
        provider feedback loops, third-party listings), so this is the authoritative health source;
        our own app metrics only provide the per-workflow diagnosis.
        """
        tenant_name = self._tenant_name_for_team(team_id)
        try:
            tenant = self.ses_v2_client.get_tenant(TenantName=tenant_name)["Tenant"]
        except ClientError as e:
            if e.response["Error"]["Code"] in ("NotFoundException", "BadRequestException"):
                return None
            raise

        sending_status: str = tenant.get("SendingStatus", "ENABLED")
        tenant_arn = tenant.get("TenantArn")
        reputation_impact: str | None = None
        findings: list[dict[str, Any]] = []

        if tenant_arn:
            try:
                entity = self.ses_v2_client.get_reputation_entity(
                    ReputationEntityReference=tenant_arn, ReputationEntityType="RESOURCE"
                )["ReputationEntity"]
            except ClientError as e:
                # A tenant with no attributed sends yet has no reputation entity.
                if e.response["Error"]["Code"] != "NotFoundException":
                    raise
                entity = {}
            reputation_impact = entity.get("ReputationImpact")
            # The aggregate folds in both AWS-managed and customer-managed pauses.
            sending_status = entity.get("SendingStatusAggregate", sending_status)

            # RESOURCE_ARN is the only filter key AWS documents as usable on its own with this
            # scoping (see _iter_open_recommendations for why STATUS is filtered locally).
            findings.extend(
                {
                    "finding_type": recommendation.get("Type", ""),
                    "impact": recommendation.get("Impact", "LOW"),
                    "description": recommendation.get("Description", ""),
                    "last_updated_at": recommendation.get("LastUpdatedTimestamp"),
                }
                for recommendation in self._iter_open_recommendations({"RESOURCE_ARN": tenant_arn})
            )

        return {
            "sending_status": sending_status,
            "reputation_impact": reputation_impact,
            "findings": findings,
        }

    def _iter_open_recommendations(
        self, finding_filter: dict[Any, str] | None, client: "SESV2Client | None" = None
    ) -> Iterator["RecommendationTypeDef"]:
        """
        Walk every page of ListRecommendations, yielding only OPEN recommendations. The local
        STATUS check exists for RESOURCE_ARN-filtered calls: AWS documents STATUS as combinable
        only with IMPACT or TYPE, so tenant-scoped listings must drop FIXED entries client-side.
        """
        client = client or self.ses_v2_client
        kwargs: dict[str, Any] = {"PageSize": RECOMMENDATIONS_PAGE_SIZE}
        if finding_filter:
            kwargs["Filter"] = finding_filter
        while True:
            page = client.list_recommendations(**kwargs)
            for recommendation in page.get("Recommendations", []):
                if recommendation.get("Status") == "OPEN":
                    yield recommendation
            next_token = page.get("NextToken")
            if not next_token:
                return
            kwargs["NextToken"] = next_token

    def get_account_enforcement_status(self) -> str:
        """
        Account-level SES verdict from a single GetAccount call, so that it stays cheap enough
        to poll often and cannot fail because of the paged findings listing.
        """
        # Strict access on purpose: a response without EnforcementStatus must fail the poll
        # (surfacing via the staleness alert) rather than be reported as healthy.
        return self.ses_v2_client.get_account()["EnforcementStatus"]

    def get_account_reputation_findings(self) -> list[dict[str, str]]:
        """
        Every open reputation finding on the account, classified by the resource it references.
        AWS opens findings well before it enforces, so this is the earliest account-scoped
        warning available.
        """
        return [
            {
                "finding_type": recommendation.get("Type", ""),
                "impact": recommendation.get("Impact", "LOW"),
                "scope": self._finding_scope(recommendation.get("ResourceArn", "")),
                "description": recommendation.get("Description", ""),
            }
            for recommendation in self._iter_open_recommendations(
                {"STATUS": "OPEN"}, client=self.ses_v2_recommendations_client
            )
        ]

    @staticmethod
    def _finding_scope(resource_arn: str) -> str:
        # Tenant and identity findings are a customer's sender health; anything else
        # (configuration sets, the account itself, an unrecognized or missing ARN) is
        # treated as shared infrastructure so classification errs toward alerting us.
        if ":tenant/" in resource_arn:
            return "tenant"
        if ":identity/" in resource_arn:
            return "identity"
        return "account"

    @cached_property
    def _aws_account_id(self) -> str:
        account_id: str | None = cache.get(AWS_ACCOUNT_ID_CACHE_KEY)
        if account_id is None:
            account_id = self.sts_client.get_caller_identity()["Account"]
            cache.set(AWS_ACCOUNT_ID_CACHE_KEY, account_id, AWS_ACCOUNT_ID_CACHE_SECONDS)
        return account_id

    def _identity_arn(self, domain: str) -> str:
        return f"arn:aws:ses:{settings.SES_REGION}:{self._aws_account_id}:identity/{domain}"

    def _configuration_set_arn(self, name: str) -> str:
        return f"arn:aws:ses:{settings.SES_REGION}:{self._aws_account_id}:configuration-set/{name}"

    def _associate_tenant_resource(self, tenant_name: str, resource_arn: str) -> None:
        try:
            self.ses_v2_client.create_tenant_resource_association(TenantName=tenant_name, ResourceArn=resource_arn)
        except ClientError as e:
            if e.response["Error"]["Code"] != "AlreadyExistsException":
                raise

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

        # Associate the new domain identity with the tenant, plus the configuration sets sends
        # reference — an attributed send fails unless EVERY resource it uses is associated.
        self._associate_tenant_resource(expected_tenant, self._identity_arn(domain))
        for config_set in settings.SES_TENANT_CONFIGURATION_SETS:
            # Unlike the identity (created moments ago in this same call), config sets are
            # provisioned externally — a missing or drifted one must not fail the customer's
            # add-domain request. The gap is caught by migrate_ses_tenants / at attributed send
            # time instead.
            try:
                self._associate_tenant_resource(expected_tenant, self._configuration_set_arn(config_set))
            except (ClientError, BotoCoreError):
                logger.exception(
                    "Failed to associate configuration set '%s' with tenant '%s'", config_set, expected_tenant
                )

    def verify_email_domain(self, domain: str, mail_from_subdomain: str, team_id: int) -> EmailDomainVerification:
        # Validate the domain contains valid characters for a domain name
        DOMAIN_REGEX = r"(?i)^([a-z0-9]+(-[a-z0-9]+)*\.)+[a-z]{2,}$"
        if not re.match(DOMAIN_REGEX, domain):
            raise exceptions.ValidationError("Please enter a valid domain or subdomain name.")

        # Start/ensure domain verification (TXT at _amazonses.domain) ---
        verification_token: str | None = None
        try:
            verify_resp = self.ses_client.verify_domain_identity(Domain=domain)
            verification_token = verify_resp["VerificationToken"]
        except ClientError as e:
            # If already requested/exists, carry on; SES v1 is idempotent-ish here
            if e.response["Error"]["Code"] not in ("InvalidParameterValue",):
                raise

        #  Start/ensure DKIM (three CNAMEs) ---
        dkim_tokens: list[str] = []
        try:
            dkim_resp = self.ses_client.verify_domain_dkim(Domain=domain)
            dkim_tokens = dkim_resp["DkimTokens"]
        except ClientError as e:
            if e.response["Error"]["Code"] not in ("InvalidParameterValue",):
                raise

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

        # DMARC is in the list too: AWS SES has no method to check its presence, so we do a direct
        # DNS lookup further below and include the result in the overall status.
        dns_records = [
            _legacy_dns_record(record)
            for record in build_email_domain_records(
                domain=domain,
                mail_from_subdomain=mail_from_subdomain,
                verification_token=verification_token,
                dkim_tokens=dkim_tokens,
                ses_region=self._ses_region,
            )
        ]

        identity = self._read_identity_state_or_unknown(domain)
        verification_status = identity.verification_status
        dkim_status = identity.dkim_status
        mail_from_status = identity.mail_from_status

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

        # Normalize overall status
        overall: EmailDomainVerificationStatus
        if identity.is_ready(dmarc_published=dmarc_status == "Success"):
            overall = "success"
        elif "Failed" in identity.statuses:
            overall = "failed"
        else:
            overall = "pending"

        if overall == "success" and not self._is_associated_with_team(domain, team_id):
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

    def get_email_domain_status(self, domain: str, mail_from_subdomain: str, team_id: int) -> EmailDomainCheck:
        try:
            return self._check_email_domain(domain, mail_from_subdomain=mail_from_subdomain, team_id=team_id)
        except (ClientError, BotoCoreError) as error:
            if not _is_throttling(error):
                capture_exception(error, {"domain": domain, "team_id": team_id})
            raise EmailProviderUnavailableError(f"Could not read the SES state of {domain}") from error

    def _check_email_domain(self, domain: str, *, mail_from_subdomain: str, team_id: int) -> EmailDomainCheck:
        identity = self._read_identity_state(domain).for_mail_from_domain(f"{mail_from_subdomain}.{domain}")
        if identity.verification_token is None:
            return build_email_domain_check(provider_status=EmailDomainSetupStatus.NOT_STARTED, records=())

        records = build_email_domain_records(
            domain=domain,
            mail_from_subdomain=mail_from_subdomain,
            verification_token=identity.verification_token,
            dkim_tokens=identity.dkim_tokens,
            ses_region=self._ses_region,
        )
        published = find_published_records(domain, records)
        dmarc_published = any(record.kind == EmailDomainSetupRecordKind.DMARC for record in published.records)
        is_ready = (
            identity.is_ready(dmarc_published=dmarc_published)
            and published.every_lookup_answered
            and self._is_associated_with_team(domain, team_id)
        )
        return build_email_domain_check(
            provider_status=identity.setup_status(is_ready=is_ready),
            records=[
                replace(record, status=identity.record_status(record, published=record in published.records))
                for record in records
            ],
            every_dns_lookup_answered=published.every_lookup_answered,
        )

    @property
    def _ses_region(self) -> str:
        return getattr(settings, "SES_REGION", "us-east-1")

    def _is_associated_with_team(self, domain: str, team_id: int) -> bool:
        return self._tenant_name_for_team(team_id) in self._list_identity_tenants(domain)

    def _read_identity_state_or_unknown(self, domain: str) -> "_SESIdentityState":
        try:
            return self._read_identity_state(domain)
        except ClientError:
            logger.warning("Could not read the SES identity attributes for %s", domain, exc_info=True)
            return _SESIdentityState.unknown()

    def _read_identity_state(self, domain: str) -> "_SESIdentityState":
        id_for_domain = self.ses_client.get_identity_verification_attributes(Identities=[domain])[
            "VerificationAttributes"
        ].get(domain)
        dkim_for_domain = self.ses_client.get_identity_dkim_attributes(Identities=[domain])["DkimAttributes"].get(
            domain
        )
        mail_from_for_domain = self.ses_client.get_identity_mail_from_domain_attributes(Identities=[domain])[
            "MailFromDomainAttributes"
        ].get(domain)
        return _SESIdentityState(
            verification_status=id_for_domain["VerificationStatus"] if id_for_domain else _UNKNOWN,
            verification_token=id_for_domain.get("VerificationToken") if id_for_domain else None,
            dkim_status=dkim_for_domain["DkimVerificationStatus"] if dkim_for_domain else _UNKNOWN,
            dkim_tokens=tuple(dkim_for_domain.get("DkimTokens", [])) if dkim_for_domain else (),
            mail_from_status=mail_from_for_domain["MailFromDomainStatus"] if mail_from_for_domain else _UNKNOWN,
            mail_from_domain=mail_from_for_domain.get("MailFromDomain") if mail_from_for_domain else None,
        )

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
        Delete an identity from SES, removing its tenant associations first
        (SES refuses to delete an identity that still has tenant associations)
        """
        try:
            arn = self._identity_arn(identity)
            for tenant_name in self._list_identity_tenants(identity):
                try:
                    self.ses_v2_client.delete_tenant_resource_association(TenantName=tenant_name, ResourceArn=arn)
                except ClientError as e:
                    if e.response["Error"]["Code"] != "NotFoundException":
                        raise
            self.ses_client.delete_identity(Identity=identity)
            logger.info(f"Identity {identity} deleted from SES")
        except (ClientError, BotoCoreError) as e:
            logger.exception(f"SES API error deleting identity: {e}")
            raise

    def _busiest_domains(
        self, domains: Sequence[str], *, start: datetime, end: datetime, limit: int, deadline: float
    ) -> list[str]:
        """The `limit` domains that sent the most over the window.

        One SEND query per domain with no ISP dimension, which is a fraction of the per-provider
        fan-out it decides. A domain whose query fails sorts last rather than raising: losing it is
        the same outcome the unconditional slice already had, and this panel never fails the page.
        Ranking shares the caller's deadline, and running out of it falls back to the first few
        rather than spending the whole budget deciding what to spend it on.
        """
        totals: dict[str, int] = dict.fromkeys(domains, 0)
        subjects = {f"d{index}": domain for index, domain in enumerate(domains)}
        queries = [
            {
                "Id": query_id,
                "Namespace": "VDM",
                "Metric": "SEND",
                "Dimensions": {"EMAIL_IDENTITY": domain},
                "StartDate": start,
                "EndDate": end,
            }
            for query_id, domain in subjects.items()
        ]
        try:
            for batch in batched(queries, METRIC_QUERY_BATCH_SIZE, strict=False):
                if monotonic() + METRIC_CALL_WORST_CASE_SECONDS > deadline:
                    logger.warning("Ran out of budget ranking sending domains; keeping the first few")
                    return list(domains)[:limit]
                response = self.ses_v2_metrics_client.batch_get_metric_data(Queries=list(batch))  # type: ignore[arg-type]
                for result in response.get("Results", []):
                    domain = subjects.get(result["Id"])
                    if domain is not None:
                        totals[domain] = sum(result.get("Values", []) or [])
        except Exception:
            logger.exception("Could not rank sending domains by volume; keeping the first few")
            return list(domains)[:limit]

        # Volume first, then the caller's order, so the choice is stable between refreshes when two
        # domains sent the same amount.
        order = {domain: index for index, domain in enumerate(domains)}
        ranked = sorted(domains, key=lambda domain: (-totals[domain], order[domain]))
        if ranked[limit:]:
            logger.info(
                "Capped the per-provider breakdown to the busiest sending domains",
                extra={"kept": ranked[:limit], "dropped": ranked[limit:]},
            )
        return ranked[:limit]

    def get_identity_isp_metrics(
        self,
        domains: Sequence[str],
        window_days: int,
        isps: Sequence[str] | None = None,
        max_domains: int | None = None,
    ) -> list[IspSendingMetrics]:
        """
        Sending health per mailbox provider, over the given sending domains.

        Counts are summed across `domains` because VDM's EMAIL_IDENTITY dimension is per verified
        domain, while a project's rates are project-wide. Providers that received nothing in the
        window are omitted rather than shown as a row of zeros.
        """
        isps = list(isps) if isps is not None else list(settings.SES_ISP_DIMENSIONS)
        # Several senders can share one domain. A duplicate would query the same series twice and
        # sum it in twice, inflating volume.
        domains = list(dict.fromkeys(domains))
        if not domains or not isps:
            return []

        deadline = monotonic() + METRIC_QUERY_BUDGET_SECONDS

        # VDM rejects the whole batch if either bound is a partial day, so the window is whole UTC
        # days ending at the last midnight. Today is therefore excluded.
        end = datetime.now(tz=UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        start = end - timedelta(days=window_days)

        # Bounding the fan-out by taking an arbitrary slice drops whichever domains sort last, which
        # can be the only one sending today. One cheap query each says which ones actually sent.
        if max_domains is not None and len(domains) > max_domains:
            domains = self._busiest_domains(domains, start=start, end=end, limit=max_domains, deadline=deadline)

        plan = _build_isp_queries(domains, isps, start, end)
        series = self._collect_isp_series(plan, deadline, len(domains))
        return _isp_rows_from_series(isps, series)

    def _collect_isp_series(self, plan: IspQueryPlan, deadline: float, domain_count: int) -> IspMetricSeries:
        """
        Run the queries in batches, returning the daily series and the subjects with no answer.

        A subject in the failed set has an empty series for want of an answer, not because nothing
        happened, so every rate derived from it is reported as unknown rather than as zero.
        """
        buckets_by_subject: dict[IspMetric, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        failed: set[IspMetric] = set()
        for batch in batched(plan.queries, METRIC_QUERY_BATCH_SIZE, strict=False):
            if monotonic() + METRIC_CALL_WORST_CASE_SECONDS > deadline:
                # Raises rather than returning the batches that did answer: a rate built from a
                # partial fan-out is wrong, not merely incomplete. The caller turns this into an
                # absent breakdown, the same degradation as any other SES failure.
                raise TimeoutError(
                    f"SES metric queries exceeded {METRIC_QUERY_BUDGET_SECONDS}s for {domain_count} domain(s)"
                )
            answer = self._answer_metric_batch(batch, plan, deadline)
            failed.update(answer.rejected)
            for response in answer.responses:
                self._absorb_metric_response(response, plan, buckets_by_subject, failed)
        return IspMetricSeries(buckets=buckets_by_subject, failed=frozenset(failed))

    def _answer_metric_batch(
        self, batch: Sequence[dict[str, Any]], plan: IspQueryPlan, deadline: float
    ) -> IspBatchAnswer:
        """
        Run one batch, reissuing it per provider if SES refuses the whole request.

        SES validates dimension values per request, so one name it will not accept fails every
        query sent alongside it. A batch carries several providers, and a subject is keyed by
        provider and metric with no domain, so failing the batch would drop a provider SES does
        accept from the whole breakdown rather than from this request. Reissuing keeps it, and
        costs the extra calls only when a name is bad. Grouping by provider rather than by a fixed
        count keeps each retry whole even when a batch boundary splits a provider.
        """
        try:
            return IspBatchAnswer(
                responses=(self.ses_v2_metrics_client.batch_get_metric_data(Queries=list(batch)),),  # type: ignore[arg-type]
                rejected=frozenset(),
            )
        except ClientError as rejection:
            if rejection.response.get("Error", {}).get("Code") != "BadRequestException":
                raise

        responses: list[Mapping[str, Any]] = []
        rejected: set[IspMetric] = set()
        by_provider: dict[str, list[dict[str, Any]]] = {}
        for query in batch:
            by_provider.setdefault(plan.subjects[query["Id"]].isp, []).append(query)
        for group in by_provider.values():
            if monotonic() + METRIC_CALL_WORST_CASE_SECONDS > deadline:
                raise TimeoutError(
                    f"SES metric queries exceeded {METRIC_QUERY_BUDGET_SECONDS}s splitting a rejected batch"
                )
            subjects = [plan.subjects[query["Id"]] for query in group]
            try:
                responses.append(self.ses_v2_metrics_client.batch_get_metric_data(Queries=list(group)))  # type: ignore[arg-type]
            except ClientError as rejection:
                if rejection.response.get("Error", {}).get("Code") != "BadRequestException":
                    raise
                rejected.update(subjects)
                logger.warning(
                    "SES rejected a metric query; dropping the provider",
                    extra={"provider": subjects[0].isp},
                )
        return IspBatchAnswer(responses=tuple(responses), rejected=frozenset(rejected))

    def _absorb_metric_response(
        self,
        response: Mapping[str, Any],
        plan: IspQueryPlan,
        buckets_by_subject: dict[IspMetric, dict[str, int]],
        failed: set[IspMetric],
    ) -> None:
        """Fold one response into the running series, recording the queries it could not answer."""
        for result in response.get("Results", []):
            buckets = buckets_by_subject[plan.subjects[result["Id"]]]
            # AWS documents Values as "cumulative / sum" without saying which, so this reads
            # them as per-bucket counts. If they are running totals, summed deliveries overshoot
            # sends and every provider pins to a 100% delivery rate against the clamp.
            for timestamp, value in zip(result.get("Timestamps", []), result.get("Values", []), strict=False):
                buckets[timestamp.date().isoformat()] += value
        for error in response.get("Errors", []):
            subject = plan.subjects.get(error.get("Id", ""))
            if subject is not None:
                failed.add(subject)
            # A per-query failure leaves that metric at zero, which understates a rate rather
            # than breaking the panel. Log it so a systematic failure stays visible. A malformed
            # ISP name is different: SES rejects the request rather than the query, which
            # _answer_metric_batch narrows down to the one provider it names.
            # "message" is reserved: LogRecord already has one, and passing it in `extra`
            # raises KeyError inside makeRecord, turning a logged warning into a lost breakdown.
            logger.warning(
                "SES metric query failed",
                extra={
                    "query": subject,
                    "code": error.get("Code"),
                    "error_message": error.get("Message"),
                },
            )
