import logging
from typing import Any

from django.core.management.base import BaseCommand, CommandError

from botocore.exceptions import BotoCoreError, ClientError

from posthog.models.integration import Integration

from products.workflows.backend.providers import SESProvider

logger = logging.getLogger(__name__)


def ses_email_domains(domains: list[str]) -> list[str]:
    query = Integration.objects.filter(kind="email", config__provider="ses")
    if domains:
        query = query.filter(config__domain__in=domains)
    return sorted({domain for domain in query.values_list("config__domain", flat=True) if domain})


class Command(BaseCommand):
    help = (
        "Disable SES email feedback forwarding on the domain identities of SES email integrations. "
        "New domains get this during setup. Run this once for domains created before that. Idempotent."
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--dry-run", action="store_true", help="Print the domains without changing them")
        parser.add_argument("--domains", type=str, help="Comma separated list of email domains to update")

    def handle(self, *args: Any, **options: Any) -> None:
        domains_opt = options.get("domains")
        requested = [d.strip().lower() for d in domains_opt.split(",") if d.strip()] if domains_opt else []
        domains = ses_email_domains(requested)

        if options.get("dry_run"):
            for domain in domains:
                self.stdout.write(f"[DRY-RUN] Would disable feedback forwarding for {domain}")
            self.stdout.write(f"Summary: {len(domains)} domain(s) to update")
            return

        provider = SESProvider()
        failures: list[str] = []
        for domain in domains:
            try:
                provider.disable_feedback_forwarding(domain)
            except ClientError as e:
                # The integration can outlive its SES identity. Nothing forwards for a missing identity.
                if e.response["Error"]["Code"] == "NotFoundException":
                    self.stdout.write(f"Skipped {domain}: no SES identity")
                    continue
                logger.exception("Failed to disable SES feedback forwarding for '%s'", domain)
                failures.append(domain)
            except BotoCoreError:
                logger.exception("Failed to disable SES feedback forwarding for '%s'", domain)
                failures.append(domain)

        self.stdout.write(f"Summary: {len(domains) - len(failures)} domain(s) processed, {len(failures)} failure(s)")
        if failures:
            raise CommandError(f"Failed for {', '.join(failures)}. Rerun with --domains after you fix the cause.")
