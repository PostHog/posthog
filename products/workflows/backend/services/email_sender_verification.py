from time import monotonic

import structlog

from posthog.models.integration import EmailIntegration, Integration, defer_repository_cache_fields
from posthog.redis import get_client

logger = structlog.get_logger(__name__)


class EmailSenderVerification:
    LOCK_KEY = "workflows:email_sender_verification:lock"
    CURSOR_KEY = "workflows:email_sender_verification:cursor"
    WORK_BUDGET_SECONDS = 240

    @staticmethod
    def refresh_pending() -> None:
        redis = get_client()
        lock = redis.lock(EmailSenderVerification.LOCK_KEY, timeout=300)
        if not lock.acquire(blocking=False):
            return
        try:
            EmailSenderVerification._refresh_pending()
        finally:
            lock.release()

    @staticmethod
    def _refresh_pending() -> None:
        started_at = monotonic()
        redis = get_client()
        cursor = int(redis.get(EmailSenderVerification.CURSOR_KEY) or 0)
        integrations = defer_repository_cache_fields(
            Integration.objects.filter(
                kind="email", config__provider="ses", config__verified=False, id__gt=cursor
            ).order_by("id")
        )
        checked: set[tuple[int, str, str]] = set()
        for integration in integrations.iterator(chunk_size=500):
            if monotonic() - started_at >= EmailSenderVerification.WORK_BUDGET_SECONDS:
                return
            redis.set(EmailSenderVerification.CURSOR_KEY, integration.id)
            domain = integration.config.get("domain")
            mail_from_subdomain = integration.config.get("mail_from_subdomain", "feedback")
            if not domain:
                continue
            key = (integration.team_id, domain, mail_from_subdomain)
            if key in checked:
                continue
            checked.add(key)
            try:
                EmailIntegration(integration).refresh_verification()
            except Exception:
                logger.exception(
                    "email_sender_verification_failed", team_id=integration.team_id, integration_id=integration.id
                )
        redis.delete(EmailSenderVerification.CURSOR_KEY)
