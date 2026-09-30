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

from posthog.models.organization import Organization

from products.growth.backend.enrichment import gates
from products.growth.backend.temporal.signup_enrichment.trigger import dispatch_signup_enrichment
from products.growth.backend.temporal.signup_enrichment.workflow import SignupEnrichmentInputs


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
        if not gates.enrichment_enabled():
            raise CommandError("Signup enrichment is disabled (GROWTH_SIGNUP_ENRICHMENT_ENABLED); refusing to dispatch")
        if not gates.region_allowed():
            raise CommandError("Signup enrichment is US/EU-only; refusing to dispatch in this region")

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
            identity = gates.resolve_signup_identity(str(org.id))
            if isinstance(identity, gates.SignupIdentitySkip):
                skipped += 1
                if identity.reason == "signup_user_left":
                    self.stdout.write(
                        f"skip {org.id} ({org.created_at:%Y-%m-%d %H:%M}) (signup user no longer a member)"
                    )
                else:
                    self.stdout.write(f"skip {org.id} ({org.created_at:%Y-%m-%d %H:%M}) (no usable signup member)")
                continue

            inputs = SignupEnrichmentInputs(
                organization_id=str(org.id), distinct_id=identity.distinct_id, domain=identity.domain
            )
            if options["dry_run"]:
                self.stdout.write(f"would dispatch {org.id} ({org.created_at:%Y-%m-%d %H:%M}) domain={identity.domain}")
            else:
                try:
                    dispatch_signup_enrichment(inputs)
                except Exception as e:
                    errored += 1
                    self.stderr.write(f"error {org.id} ({org.created_at:%Y-%m-%d %H:%M}): {e}")
                    continue
                self.stdout.write(f"dispatched {org.id} ({org.created_at:%Y-%m-%d %H:%M}) domain={identity.domain}")
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
