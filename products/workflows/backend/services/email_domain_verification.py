from collections import defaultdict

import structlog

from posthog.models.integration import EmailIntegration, Integration

from products.workflows.backend.providers.ses import SESProvider

logger = structlog.get_logger(__name__)


def revoke_lost_email_domain_verifications(provider: SESProvider | None = None) -> int:
    """Mark the senders of a domain as unverified when SES no longer verifies that domain.

    The send path refuses a sender that is not verified, so this stops the sends before they reach
    SES, which would reject each one. When the customer verifies the domain again (email/verify), the
    senders become verified and the sends start again. Returns the number of senders it changed.
    """
    senders_by_domain: dict[str, list[Integration]] = defaultdict(list)
    for sender in Integration.objects.filter(kind="email", config__verified=True).order_by("id"):
        config = sender.config or {}
        if config.get("provider", "ses") == "ses" and config.get("domain"):
            senders_by_domain[config["domain"]].append(sender)
    if not senders_by_domain:
        return 0

    revoked_domains = (provider or SESProvider()).find_domains_with_revoked_verification(senders_by_domain.keys())

    revoked_count = 0
    for domain in sorted(revoked_domains):
        # A domain can be shared by teams of one organization, and each team keeps its own senders.
        sender_per_team: dict[int, Integration] = {}
        for sender in senders_by_domain[domain]:
            sender_per_team.setdefault(sender.team_id, sender)
        for team_id, sender in sorted(sender_per_team.items()):
            changed = EmailIntegration(sender).mark_domain_unverified()
            revoked_count += len(changed)
            logger.warning(
                "Email domain lost its SES verification, so its senders stop sending",
                team_id=team_id,
                domain=domain,
                sender_ids=[changed_sender.id for changed_sender in changed],
            )
    return revoked_count
