import time
from typing import Any

from django.core.management.base import BaseCommand
from django.db import connection, transaction

from posthog.integrations import CrossTeamFilter, IntegrationManager
from posthog.models.integration.email import lock_sender_domain

from products.workflows.backend.providers import SESProvider


def _domains_with_senders(domains: list[str]) -> set[str]:
    if not domains:
        return set()
    rows = IntegrationManager.email.any.list_across_teams(CrossTeamFilter(where_in={"domain": tuple(domains)}))
    return {domain for row in rows if (domain := row.config.get("domain"))}


class Command(BaseCommand):
    help = (
        "Delete the SES domain identities of this region whose verification failed and that no email sender uses. "
        "They count against the SES identity quota of the region. Prints the domains and changes nothing unless --apply."
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--apply", action="store_true", help="Delete the identities instead of only listing them")
        parser.add_argument(
            "--pace-seconds", type=float, default=0.5, help="Wait between deletes, to stay under the SES rate limit"
        )

    def handle(self, *args: Any, **options: Any) -> None:
        provider = SESProvider()
        failed = provider.list_failed_domain_identities()
        unused = sorted(set(failed) - _domains_with_senders(failed))

        if not options["apply"]:
            for domain in unused:
                self.stdout.write(f"[DRY-RUN] Would delete the SES identity of {domain}")
            self.stdout.write(f"Summary: {len(unused)} of {len(failed)} failed identities have no sender")
            return

        deleted = 0
        for domain in unused:
            # The domain lock makes a sender added since the listing either finish first or wait for the delete.
            with transaction.atomic():
                with connection.cursor() as cursor:
                    lock_sender_domain(cursor, domain)
                if _domains_with_senders([domain]):
                    self.stdout.write(f"Skipped {domain}: a sender was added after the listing")
                    continue
                provider.delete_identity(domain)
            deleted += 1
            self.stdout.write(f"Deleted the SES identity of {domain}")
            time.sleep(options["pace_seconds"])
        self.stdout.write(self.style.SUCCESS(f"Summary: deleted {deleted} of {len(unused)} unused failed identities"))
