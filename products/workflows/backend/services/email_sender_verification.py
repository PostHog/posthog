from collections.abc import Callable, Iterable, Iterator
from datetime import timedelta
from functools import cached_property
from itertools import batched
from time import monotonic

from django.utils import timezone

import structlog
from botocore.exceptions import BotoCoreError

from posthog.dataclasses import frozen
from posthog.integrations import IntegrationRecord
from posthog.models.integration import EmailIntegration, PendingSenderWindow, request_domain_verification
from posthog.redis import get_client

from products.workflows.backend.providers.ses import (
    BACKGROUND_CALL_WORST_CASE_SECONDS,
    DNS_LOOKUP_LIFETIME_SECONDS,
    IDENTITY_ATTRIBUTES_BATCH_SIZE,
    IDENTITY_STATUS_READS_PER_BATCH,
    READ_MIN_INTERVAL_SECONDS,
    SESIdentityStatus,
    SESProvider,
)

logger = structlog.get_logger(__name__)


@frozen
class SenderAgeTier:
    name: str
    min_age: timedelta
    max_age: timedelta
    work_budget_seconds: int
    lock_timeout_seconds: int

    def redis_key(self, purpose: str) -> str:
        return f"workflows:email_sender_verification:{self.name}:{purpose}"


NEW_SENDERS = SenderAgeTier(
    name="new",
    min_age=timedelta(),
    max_age=timedelta(hours=1),
    work_budget_seconds=100,
    lock_timeout_seconds=130,
)
SETTLED_SENDERS = SenderAgeTier(
    name="settled",
    min_age=timedelta(hours=1),
    max_age=timedelta(days=7),
    work_budget_seconds=240,
    lock_timeout_seconds=300,
)
SENDER_AGE_TIERS = (NEW_SENDERS, SETTLED_SENDERS)


class EmailSenderVerification:
    TIER_READ_INTERVAL_SECONDS = READ_MIN_INTERVAL_SECONDS * len(SENDER_AGE_TIERS)
    PACED_CALL_WORST_CASE_SECONDS = BACKGROUND_CALL_WORST_CASE_SECONDS + TIER_READ_INTERVAL_SECONDS
    STATUS_READ_WORST_CASE_SECONDS = IDENTITY_STATUS_READS_PER_BATCH * PACED_CALL_WORST_CASE_SECONDS
    SENDER_CHECK_WORST_CASE_SECONDS = (
        PACED_CALL_WORST_CASE_SECONDS + BACKGROUND_CALL_WORST_CASE_SECONDS + DNS_LOOKUP_LIFETIME_SECONDS
    )

    def __init__(self, work_budget_seconds: int) -> None:
        self.deadline = monotonic() + work_budget_seconds

    @cached_property
    def provider(self) -> SESProvider:
        return SESProvider.for_background(read_interval_seconds=self.TIER_READ_INTERVAL_SECONDS)

    @staticmethod
    def refresh_pending(tier: SenderAgeTier) -> None:
        lock = get_client().lock(tier.redis_key("lock"), timeout=tier.lock_timeout_seconds)
        if not lock.acquire(blocking=False):
            return
        try:
            _TierSweep(tier).run()
        finally:
            lock.release()

    @staticmethod
    def request_domain_check(domain: str) -> None:
        request_domain_verification(domain)

    def verify_ready_senders(
        self, senders: Iterable[IntegrationRecord], on_sender: Callable[[IntegrationRecord], None] = lambda _: None
    ) -> bool:
        checked: set[tuple[int, str | None, str]] = set()
        for batch in batched(senders, IDENTITY_ATTRIBUTES_BATCH_SIZE, strict=False):
            if not self._has_time_for(self.STATUS_READ_WORST_CASE_SECONDS):
                return False
            try:
                statuses = self.provider.get_identity_statuses([d for sender in batch if (d := _domain(sender))])
            except BotoCoreError:
                logger.exception("email_sender_verification_ses_unavailable")
                return False
            for sender in batch:
                ready_status = _ready_status(statuses, sender)
                if ready_status and not self._has_time_for(self.SENDER_CHECK_WORST_CASE_SECONDS):
                    return False
                on_sender(sender)
                key = (sender.team_id, _domain(sender), _mail_from_subdomain(sender))
                if ready_status and key not in checked:
                    checked.add(key)
                    self._verify(sender, ready_status)
        return True

    def _has_time_for(self, worst_case_seconds: int) -> bool:
        return monotonic() + worst_case_seconds <= self.deadline

    def _verify(self, sender: IntegrationRecord, status: SESIdentityStatus) -> None:
        try:
            verification = self.provider.get_email_domain_verification(
                sender.config["domain"], _mail_from_subdomain(sender), sender.team_id, identity_status=status
            )
            EmailIntegration(sender).apply_verification(verification)
        except Exception:
            logger.exception("email_sender_verification_failed", team_id=sender.team_id, integration_id=sender.id)


class _TierSweep:
    def __init__(self, tier: SenderAgeTier) -> None:
        self.tier = tier
        self.redis = get_client()

    def run(self) -> None:
        verification = EmailSenderVerification(self.tier.work_budget_seconds)
        if verification.verify_ready_senders(self._senders(), on_sender=self._advance):
            self.redis.delete(self.tier.redis_key("cursor"), self.tier.redis_key("scan_end"))

    def _window(self) -> PendingSenderWindow:
        now = timezone.now()
        return PendingSenderWindow(oldest=now - self.tier.max_age, newest=now - self.tier.min_age)

    def _advance(self, sender: IntegrationRecord) -> None:
        self.redis.set(self.tier.redis_key("cursor"), sender.id)

    def _senders(self) -> Iterator[IntegrationRecord]:
        window = self._window()
        cursor = int(self.redis.get(self.tier.redis_key("cursor")) or 0)
        scan_end = int(self.redis.get(self.tier.redis_key("scan_end")) or 0)
        if not scan_end:
            scan_end = window.last_id()
            self.redis.set(self.tier.redis_key("scan_end"), scan_end)
        return window.senders(after_id=cursor, up_to_id=scan_end)


def _ready_status(statuses: dict[str, SESIdentityStatus], sender: IntegrationRecord) -> SESIdentityStatus | None:
    status = statuses.get(_domain(sender) or "")
    if status is None or not status.is_ready_for(_mail_from_domain(sender)):
        return None
    return status


def _domain(sender: IntegrationRecord) -> str | None:
    return sender.config.get("domain")


def _mail_from_subdomain(sender: IntegrationRecord) -> str:
    return sender.config.get("mail_from_subdomain", "feedback")


def _mail_from_domain(sender: IntegrationRecord) -> str:
    return f"{_mail_from_subdomain(sender)}.{_domain(sender)}"
