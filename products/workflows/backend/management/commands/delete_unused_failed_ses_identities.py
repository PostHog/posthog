import time
import argparse
from typing import Any

from django.core.management.base import BaseCommand
from django.db import connection, transaction

from posthog.integrations import CrossTeamFilter, IntegrationManager
from posthog.models.integration.email import lock_sender_domain

from products.workflows.backend.providers import SESProvider


def _has_sender(domain: str) -> bool:
    return bool(IntegrationManager.email.any.list_across_teams(CrossTeamFilter(where={"domain": domain}, limit=1)))


def _non_negative_seconds(value: str) -> float:
    seconds = float(value)
    if seconds < 0:
        raise argparse.ArgumentTypeError("must be zero or more")
    return seconds


class Command(BaseCommand):
    help = (
        "Delete the SES domain identities of this region whose verification failed and that no email sender uses. "
        "They count against the SES identity quota of the region. Prints the domains and changes nothing unless --apply."
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--apply", action="store_true", help="Delete the identities instead of only listing them")
        parser.add_argument(
            "--pace-seconds",
            type=_non_negative_seconds,
            default=1.0,
            help="Wait between deletes. SES accepts one DeleteIdentity call per second.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        provider = SESProvider()
        failed = sorted(provider.list_failed_domain_identities())
        unused = 0
        for domain in failed:
            # Under the domain lock, a sender added at the same time either commits first and keeps the identity,
            # or waits until the delete ends and then creates the identity again.
            with transaction.atomic():
                with connection.cursor() as cursor:
                    lock_sender_domain(cursor, domain)
                if _has_sender(domain):
                    continue
                unused += 1
                if not options["apply"]:
                    self.stdout.write(f"[DRY-RUN] Would delete the SES identity of {domain}")
                    continue
                provider.delete_identity(domain)
            self.stdout.write(f"Deleted the SES identity of {domain}")
            time.sleep(options["pace_seconds"])
        verb = "deleted" if options["apply"] else "would delete"
        self.stdout.write(f"Summary: {verb} {unused} of {len(failed)} failed identities, which no sender uses")
