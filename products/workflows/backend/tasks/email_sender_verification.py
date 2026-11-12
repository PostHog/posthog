import time
from collections.abc import Iterator

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
_PAGE_SIZE = 500


@shared_task(ignore_result=True, queue=CeleryQueue.LONG_RUNNING.value, time_limit=3600)
@skip_team_scope_audit
def recheck_pending_email_senders() -> None:
    checked: set[tuple[int, str]] = set()
    verified = failed = 0
    for sender in _pending_ses_senders():
        domain_key = (sender.team_id, sender.config.get("domain", ""))
        if domain_key in checked or not _mail_from_points_at_ses(sender):
            continue
        checked.add(domain_key)
        try:
            verified += EmailIntegration(sender).verify().get("status") == "success"
        except Exception:
            failed += 1
            logger.exception("pending email sender recheck failed", integration_id=sender.id)
        time.sleep(SECONDS_BETWEEN_SES_CHECKS)
    logger.info("pending email sender recheck finished", checked=len(checked), verified=verified, failed=failed)


def _pending_ses_senders() -> Iterator[IntegrationRecord]:
    after_id: int | None = None
    while True:
        page = IntegrationManager.email.any.list_across_teams(
            CrossTeamFilter(where={"provider": "ses", "verified": False}, limit=_PAGE_SIZE, after_id=after_id)
        )
        yield from page
        if len(page) < _PAGE_SIZE:
            return
        after_id = page[-1].id


def _mail_from_points_at_ses(sender: IntegrationRecord) -> bool:
    domain = sender.config.get("domain")
    if not domain:
        return False
    records = build_email_domain_records(
        domain=domain,
        mail_from_subdomain=sender.config.get("mail_from_subdomain", "feedback"),
        verification_token=None,
        dkim_tokens=(),
        ses_region=getattr(settings, "SES_REGION", "us-east-1"),
    )
    mail_from_mx = [record for record in records if record.kind == EmailDomainSetupRecordKind.MAIL_FROM_MX]
    return bool(find_published_records(domain, mail_from_mx).records)
