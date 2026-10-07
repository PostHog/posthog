import structlog

from posthog.models.integration import EmailIntegration, Integration, defer_repository_cache_fields

logger = structlog.get_logger(__name__)


class EmailSenderVerification:
    @staticmethod
    def refresh_pending() -> None:
        integrations = defer_repository_cache_fields(
            Integration.objects.filter(kind="email", config__provider="ses", config__verified=False)
        )
        checked: set[tuple[int, str, str]] = set()
        for integration in integrations.iterator(chunk_size=500):
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
