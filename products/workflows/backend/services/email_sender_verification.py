from datetime import timedelta
from functools import cached_property
from itertools import batched
from time import monotonic

from django.db.models import QuerySet
from django.utils import timezone

import structlog
from botocore.exceptions import BotoCoreError

from posthog.models.integration import EmailIntegration, Integration, defer_repository_cache_fields
from posthog.redis import get_client

from products.workflows.backend.providers.ses import (
    BACKGROUND_CALL_WORST_CASE_SECONDS,
    BACKGROUND_CLIENT_CONFIG,
    IDENTITY_ATTRIBUTES_BATCH_SIZE,
    SESIdentityStatus,
    SESProvider,
)

logger = structlog.get_logger(__name__)


class EmailSenderVerification:
    LOCK_KEY = "workflows:email_sender_verification:lock"
    CURSOR_KEY = "workflows:email_sender_verification:cursor"
    SCAN_END_KEY = "workflows:email_sender_verification:scan_end"
    WORK_BUDGET_SECONDS = 240
    SES_CALLS_PER_STEP = 3
    STEP_WORST_CASE_SECONDS = SES_CALLS_PER_STEP * BACKGROUND_CALL_WORST_CASE_SECONDS
    RECENT_SENDER_WINDOW = timedelta(days=7)

    def __init__(self) -> None:
        self.redis = get_client()
        self.deadline = monotonic() + self.WORK_BUDGET_SECONDS

    @cached_property
    def provider(self) -> SESProvider:
        return SESProvider(client_config=BACKGROUND_CLIENT_CONFIG)

    @staticmethod
    def refresh_pending() -> None:
        lock = get_client().lock(EmailSenderVerification.LOCK_KEY, timeout=300)
        if not lock.acquire(blocking=False):
            return
        try:
            EmailSenderVerification()._refresh_pending()
        finally:
            lock.release()

    def _refresh_pending(self) -> None:
        checked: set[tuple[int, str]] = set()
        for senders in batched(
            self._pending_senders().iterator(chunk_size=500), IDENTITY_ATTRIBUTES_BATCH_SIZE, strict=False
        ):
            if not self._has_time_for_step():
                return
            try:
                statuses = self.provider.get_identity_statuses([d for sender in senders if (d := _domain(sender))])
            except BotoCoreError:
                logger.exception("email_sender_verification_ses_unavailable")
                return
            for sender in senders:
                ready_status = _ready_status(statuses, sender)
                if ready_status and not self._has_time_for_step():
                    return
                self.redis.set(self.CURSOR_KEY, sender.id)
                key = (sender.team_id, _mail_from_domain(sender))
                if ready_status and key not in checked:
                    checked.add(key)
                    self._verify(sender, ready_status)
        self.redis.delete(self.CURSOR_KEY, self.SCAN_END_KEY)

    def _pending_senders(self) -> QuerySet[Integration]:
        pending = Integration.objects.filter(
            kind="email",
            config__provider="ses",
            config__verified=False,
            created_at__gte=timezone.now() - self.RECENT_SENDER_WINDOW,
        )
        cursor = int(self.redis.get(self.CURSOR_KEY) or 0)
        scan_end = int(self.redis.get(self.SCAN_END_KEY) or 0)
        if not scan_end:
            scan_end = pending.order_by("-id").values_list("id", flat=True).first() or 0
            self.redis.set(self.SCAN_END_KEY, scan_end)
        return defer_repository_cache_fields(pending.filter(id__gt=cursor, id__lte=scan_end).order_by("id"))

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


def _domain(sender: Integration) -> str | None:
    return sender.config.get("domain")


def _mail_from_subdomain(sender: Integration) -> str:
    return sender.config.get("mail_from_subdomain", "feedback")


def _mail_from_domain(sender: Integration) -> str:
    return f"{_mail_from_subdomain(sender)}.{_domain(sender)}"


def _ready_status(statuses: dict[str, SESIdentityStatus], sender: Integration) -> SESIdentityStatus | None:
    status = statuses.get(_domain(sender) or "")
    if status is None or not status.is_ready_for(_mail_from_domain(sender)):
        return None
    return status
