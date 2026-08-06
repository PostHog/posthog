"""Re-dispatch signup enrichment for organizations whose enrichment never persisted.

Targets orgs created in a window that were eligible at signup (work email recorded) but have
no archived provider fetch — the archive row is the first write of every enrichment run, so
its absence means the run never completed. Re-dispatch is safe: the workflow id reuse policy
allows a new run once the failed one has closed, and the writers merge rather than clobber.
"""

import time
import datetime as dt
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser

from posthog.models.organization import Organization, OrganizationMembership
from posthog.temporal.signup_enrichment.trigger import dispatch_signup_enrichment, domain_from_email
from posthog.temporal.signup_enrichment.workflow import SignupEnrichmentInputs
from posthog.utils import GenericEmails, get_instance_region

_generic_emails = GenericEmails()

# The signup creator's membership is written in the signup transaction, so it lands within
# seconds of the org row. An earliest membership older than this window means the signup
# user has left and the remaining members can't stand in for the signup identity.
_SIGNUP_MEMBERSHIP_WINDOW = dt.timedelta(minutes=5)


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
        # The kill switch is the master control for sending org data to the provider; a backfill
        # must not defeat it if it was turned off for a compliance, cost, or vendor reason.
        if not settings.GROWTH_SIGNUP_ENRICHMENT_ENABLED:
            raise CommandError("Signup enrichment is disabled (GROWTH_SIGNUP_ENRICHMENT_ENABLED); refusing to dispatch")
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
            # The write-once snapshot guard row marks a completed first attempt, so a run whose
            # archive write was swallowed (archive_provider_fetch never raises) is still excluded.
            .exclude(enrichment_signup_snapshot__isnull=False)
            .order_by("created_at")
            .iterator()
        )

        dispatched = skipped = errored = 0
        for org in orgs:
            if limit is not None and dispatched >= limit:
                break
            membership = (
                OrganizationMembership.objects.filter(organization=org)
                .select_related("user")
                .order_by("joined_at")
                .first()
            )
            if membership is not None and membership.joined_at - org.created_at > _SIGNUP_MEMBERSHIP_WINDOW:
                skipped += 1
                self.stdout.write(f"skip {org.id} ({org.created_at:%Y-%m-%d %H:%M}) (signup user no longer a member)")
                continue

            user = membership.user if membership else None
            domain = domain_from_email(user.email) if user else None
            # The signup user's email can have changed since signup, so re-check it's a work email.
            if user is None or not user.distinct_id or not domain or _generic_emails.is_generic(user.email):
                skipped += 1
                self.stdout.write(f"skip {org.id} ({org.created_at:%Y-%m-%d %H:%M}) (no usable signup member)")
                continue

            inputs = SignupEnrichmentInputs(organization_id=str(org.id), distinct_id=user.distinct_id, domain=domain)
            if options["dry_run"]:
                self.stdout.write(f"would dispatch {org.id} ({org.created_at:%Y-%m-%d %H:%M}) domain={domain}")
            else:
                try:
                    dispatch_signup_enrichment(inputs)
                except Exception as e:
                    errored += 1
                    self.stderr.write(f"error {org.id} ({org.created_at:%Y-%m-%d %H:%M}): {e}")
                    continue
                self.stdout.write(f"dispatched {org.id} ({org.created_at:%Y-%m-%d %H:%M}) domain={domain}")
                time.sleep(options["delay"])
            dispatched += 1

        verb = "would dispatch" if options["dry_run"] else "dispatched"
        summary = f"{verb} {dispatched}, skipped {skipped}, errored {errored}"
        self.stdout.write(self.style.SUCCESS(summary) if errored == 0 else self.style.WARNING(summary))
        if errored:
            self.stderr.write("re-run the same window to retry errored orgs; completed orgs are excluded")

    @staticmethod
    def _parse_datetime(value: str) -> dt.datetime:
        try:
            parsed = dt.datetime.fromisoformat(value)
        except ValueError:
            raise CommandError(f"Invalid ISO 8601 datetime: {value!r}")
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.UTC)
