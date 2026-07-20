"""Re-dispatch signup enrichment for organizations whose enrichment never persisted.

Targets orgs created in a window that were eligible at signup (work email recorded) but have
no archived provider fetch — the archive row is the first write of every enrichment run, so
its absence means the run never completed. Re-dispatch is safe: the workflow id reuse policy
allows a new run once the failed one has closed, and the writers merge rather than clobber.
"""

import time
import datetime as dt
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from posthog.models.organization import Organization, OrganizationMembership
from posthog.temporal.signup_enrichment.trigger import dispatch_signup_enrichment, domain_from_email
from posthog.temporal.signup_enrichment.workflow import SignupEnrichmentInputs
from posthog.utils import get_instance_region


class Command(BaseCommand):
    help = (
        "Re-dispatch signup enrichment for orgs created in [--after, --before) that were eligible "
        "(work email) but have no archived provider fetch, i.e. enrichment never completed."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--after", required=True, help="ISO 8601 datetime (UTC if naive): orgs created at or after")
        parser.add_argument("--before", required=True, help="ISO 8601 datetime (UTC if naive): orgs created before")
        parser.add_argument("--limit", type=int, default=None, help="Dispatch at most this many orgs")
        parser.add_argument("--delay", type=float, default=0.5, help="Seconds between dispatches")
        parser.add_argument("--dry-run", action="store_true", help="List the orgs without dispatching")

    def handle(self, *args: Any, **options: Any) -> None:
        # Enrichment is US-only for v0 (mirrors the signup-path region gate).
        if get_instance_region() != "US":
            raise CommandError("Signup enrichment is US-only; refusing to dispatch in this region")

        after = self._parse_datetime(options["after"])
        before = self._parse_datetime(options["before"])
        if after >= before:
            raise CommandError("--after must be earlier than --before")
        limit: int | None = options["limit"]

        orgs = (
            Organization.objects.filter(
                created_at__gte=after,
                created_at__lt=before,
                enrichment_record__data__work_email=True,
            )
            .exclude(enrichment_fetches__isnull=False)
            .order_by("created_at")
            .iterator()
        )

        dispatched = skipped = 0
        for org in orgs:
            if limit is not None and dispatched >= limit:
                break
            membership = (
                OrganizationMembership.objects.filter(organization=org)
                .select_related("user")
                .order_by("joined_at")
                .first()
            )
            user = membership.user if membership else None
            domain = domain_from_email(user.email) if user else None
            if user is None or not user.distinct_id or not domain:
                skipped += 1
                self.stdout.write(f"skip {org.id} ({org.created_at:%Y-%m-%d %H:%M}) (no usable signup member)")
                continue

            inputs = SignupEnrichmentInputs(organization_id=str(org.id), distinct_id=user.distinct_id, domain=domain)
            if options["dry_run"]:
                self.stdout.write(f"would dispatch {org.id} ({org.created_at:%Y-%m-%d %H:%M}) domain={domain}")
            else:
                dispatch_signup_enrichment(inputs)
                self.stdout.write(f"dispatched {org.id} ({org.created_at:%Y-%m-%d %H:%M}) domain={domain}")
                time.sleep(options["delay"])
            dispatched += 1

        verb = "would dispatch" if options["dry_run"] else "dispatched"
        self.stdout.write(self.style.SUCCESS(f"{verb} {dispatched}, skipped {skipped}"))

    @staticmethod
    def _parse_datetime(value: str) -> dt.datetime:
        try:
            parsed = dt.datetime.fromisoformat(value)
        except ValueError:
            raise CommandError(f"Invalid ISO 8601 datetime: {value!r}")
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.UTC)
