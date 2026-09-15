import time
import datetime as dt
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from products.growth.backend.facade import api, contracts

_DISABLED = "Signup enrichment is disabled (GROWTH_SIGNUP_ENRICHMENT_ENABLED); refusing to dispatch"
_REGION_NOT_ALLOWED = "Signup enrichment is US/EU-only; refusing to dispatch in this region"


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
        try:
            api.ensure_signup_backfill_allowed()
        except contracts.EnrichmentDisabled:
            raise CommandError(_DISABLED)
        except contracts.RegionNotAllowed:
            raise CommandError(_REGION_NOT_ALLOWED)

        after = self._parse_datetime(options["after"])
        before = self._parse_datetime(options["before"])
        if after >= before:
            raise CommandError("--after must be earlier than --before")
        limit: int | None = options["limit"]

        try:
            candidates = api.iter_signups_missing_enrichment(after=after, before=before)
        except contracts.EnrichmentDisabled:
            raise CommandError(_DISABLED)
        except contracts.RegionNotAllowed:
            raise CommandError(_REGION_NOT_ALLOWED)

        dispatched = skipped = errored = 0
        while limit is None or dispatched < limit:
            candidate = next(candidates, None)
            if candidate is None:
                break
            stamp = f"{candidate.organization_id} ({candidate.created_at:%Y-%m-%d %H:%M})"
            if isinstance(candidate, contracts.SignupSkip):
                skipped += 1
                if candidate.reason == "signup_user_left":
                    self.stdout.write(f"skip {stamp} (signup user no longer a member)")
                else:
                    self.stdout.write(f"skip {stamp} (no usable signup member)")
                continue

            if options["dry_run"]:
                self.stdout.write(f"would dispatch {stamp} domain={candidate.domain}")
            else:
                try:
                    api.dispatch_signup_enrichment(candidate)
                except Exception as e:
                    errored += 1
                    self.stderr.write(f"error {stamp}: {e}")
                    continue
                self.stdout.write(f"dispatched {stamp} domain={candidate.domain}")
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
