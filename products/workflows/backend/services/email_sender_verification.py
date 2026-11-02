from collections.abc import Callable, Iterable
from datetime import timedelta
from functools import cached_property
from itertools import batched
from time import monotonic

from django.db.models import Q, QuerySet
from django.utils import timezone

import structlog
from botocore.exceptions import BotoCoreError

from posthog.dataclasses import frozen
from posthog.models.integration import (
    EmailIntegration,
    Integration,
    defer_repository_cache_fields,
    mark_verification_requested,
)
from posthog.redis import get_client

from products.workflows.backend.providers.ses import (
    BACKGROUND_CALL_WORST_CASE_SECONDS,
    IDENTITY_ATTRIBUTES_BATCH_SIZE,
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
    work_budget_seconds=90,
    lock_timeout_seconds=120,
)
SETTLED_SENDERS = SenderAgeTier(
    name="settled",
    min_age=timedelta(hours=1),
    max_age=timedelta(days=7),
    work_budget_seconds=240,
    lock_timeout_seconds=300,
)


class EmailSenderVerification:
    SES_CALLS_PER_STEP = 3
    STEP_WORST_CASE_SECONDS = SES_CALLS_PER_STEP * BACKGROUND_CALL_WORST_CASE_SECONDS + READ_MIN_INTERVAL_SECONDS

    def __init__(self, work_budget_seconds: int) -> None:
        self.deadline = monotonic() + work_budget_seconds

    @cached_property
    def provider(self) -> SESProvider:
        return SESProvider.for_background()

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
        mark_verification_requested(_pending_ses_senders().filter(config__domain__iexact=domain))

    def verify_ready_senders(
        self, senders: Iterable[Integration], on_sender: Callable[[Integration], None] = lambda _: None
    ) -> bool:
        checked: set[tuple[int, str]] = set()
        for batch in batched(senders, IDENTITY_ATTRIBUTES_BATCH_SIZE, strict=False):
            if not self._has_time_for_step():
                return False
            try:
                statuses = self.provider.get_identity_statuses([d for sender in batch if (d := _domain(sender))])
            except BotoCoreError:
                logger.exception("email_sender_verification_ses_unavailable")
                return False
            for sender in batch:
                ready_status = _ready_status(statuses, sender)
                if ready_status and not self._has_time_for_step():
                    return False
                on_sender(sender)
                key = (sender.team_id, _mail_from_domain(sender))
                if ready_status and key not in checked:
                    checked.add(key)
                    self._verify(sender, ready_status)
        return True

    def _has_time_for_step(self) -> bool:
        return monotonic() + self.STEP_WORST_CASE_SECONDS <= self.deadline

    def _verify(self, sender: Integration, status: SESIdentityStatus) -> None:
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
        if verification.verify_ready_senders(self._senders().iterator(chunk_size=500), on_sender=self._advance):
            self.redis.delete(self.tier.redis_key("cursor"), self.tier.redis_key("scan_end"))

    def _in_tier(self) -> Q:
        now = timezone.now()
        newest, oldest = now - self.tier.min_age, now - self.tier.max_age
        requested_in_tier = Q(
            config__verification_requested_at__gt=oldest.timestamp(),
            config__verification_requested_at__lte=newest.timestamp(),
        )
        created_in_tier = Q(
            config__verification_requested_at__isnull=True, created_at__gt=oldest, created_at__lte=newest
        )
        return requested_in_tier | created_in_tier

    def _advance(self, sender: Integration) -> None:
        self.redis.set(self.tier.redis_key("cursor"), sender.id)

    def _senders(self) -> QuerySet[Integration]:
        pending = _pending_ses_senders().filter(self._in_tier())
        cursor = int(self.redis.get(self.tier.redis_key("cursor")) or 0)
        scan_end = int(self.redis.get(self.tier.redis_key("scan_end")) or 0)
        if not scan_end:
            scan_end = pending.order_by("-id").values_list("id", flat=True).first() or 0
            self.redis.set(self.tier.redis_key("scan_end"), scan_end)
        return pending.filter(id__gt=cursor, id__lte=scan_end).order_by("id")


def _pending_ses_senders() -> QuerySet[Integration]:
    return defer_repository_cache_fields(
        Integration.objects.filter(kind="email", config__provider="ses", config__verified=False)
    )


def _ready_status(statuses: dict[str, SESIdentityStatus], sender: Integration) -> SESIdentityStatus | None:
    status = statuses.get(_domain(sender) or "")
    if status is None or not status.is_ready_for(_mail_from_domain(sender)):
        return None
    return status


def _domain(sender: Integration) -> str | None:
    return sender.config.get("domain")


def _mail_from_subdomain(sender: Integration) -> str:
    return sender.config.get("mail_from_subdomain", "feedback")


def _mail_from_domain(sender: Integration) -> str:
    return f"{_mail_from_subdomain(sender)}.{_domain(sender)}"
