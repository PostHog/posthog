import time
from collections import defaultdict
from collections.abc import Iterable

from django.conf import settings

from celery import shared_task
from structlog import get_logger

from posthog.integrations import CrossTeamFilter, IntegrationManager, IntegrationRecord
from posthog.models.integration import EmailIntegration
from posthog.scoping_audit import skip_team_scope_audit
from posthog.tasks.utils import CeleryQueue

from products.workflows.backend.facade.enums import EmailDomainSetupRecordKind
from products.workflows.backend.services.email_domain_dns import find_published_records
from products.workflows.backend.services.email_domain_status import build_email_domain_records

logger = get_logger(__name__)

SECONDS_BETWEEN_SES_CHECKS = 5


@shared_task(ignore_result=True, queue=CeleryQueue.LONG_RUNNING.value, time_limit=3600)
@skip_team_scope_audit
def recheck_pending_email_senders() -> None:
    senders = IntegrationManager.email.any.list_across_teams(CrossTeamFilter(where={"provider": "ses"}))
    mail_from_subdomains: dict[str, set[str]] = defaultdict(set)
    for sender in senders:
        mail_from_subdomains[_domain(sender)].add(sender.config.get("mail_from_subdomain", "feedback"))

    checked: set[tuple[int, str]] = set()
    attempted = verified = failed = 0
    for sender in senders:
        domain = _domain(sender)
        if sender.config.get("verified") is not False or not domain or (sender.team_id, domain) in checked:
            continue
        checked.add((sender.team_id, domain))
        if not _mail_from_points_at_ses(domain, mail_from_subdomains[domain]):
            continue
        attempted += 1
        try:
            verified += EmailIntegration(sender).verify().get("status") == "success"
        except Exception:
            failed += 1
            logger.exception("pending email sender recheck failed", integration_id=sender.id)
        time.sleep(SECONDS_BETWEEN_SES_CHECKS)
    logger.info(
        "pending email sender recheck finished",
        checked=len(checked),
        attempted=attempted,
        verified=verified,
        failed=failed,
    )


def _domain(sender: IntegrationRecord) -> str:
    return sender.config.get("domain", "").lower()


def _mail_from_points_at_ses(domain: str, mail_from_subdomains: Iterable[str]) -> bool:
    mail_from_mx = [
        record
        for subdomain in mail_from_subdomains
        for record in build_email_domain_records(
            domain=domain,
            mail_from_subdomain=subdomain,
            verification_token=None,
            dkim_tokens=(),
            ses_region=settings.SES_REGION,
        )
        if record.kind == EmailDomainSetupRecordKind.MAIL_FROM_MX
    ]
    return bool(find_published_records(domain, mail_from_mx).records)
