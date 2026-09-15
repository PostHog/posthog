"""Re-dispatch signup enrichment for organizations whose enrichment never persisted.

Targets orgs created in a window that were eligible at signup (work email recorded) but have
no archived provider fetch — the archive row is the first write of every enrichment run, so
its absence means the run never completed. Re-dispatch is safe: the workflow id reuse policy
allows a new run once the failed one has closed, and the writers merge rather than clobber.
"""

import datetime as dt
from collections.abc import Iterator

from posthog.models.organization import Organization

from products.growth.backend.enrichment import gates
from products.growth.backend.facade.contracts import EnrichmentDisabled, RegionNotAllowed, SignupCandidate, SignupSkip
from products.growth.backend.temporal.signup_enrichment.trigger import dispatch_signup_enrichment
from products.growth.backend.temporal.signup_enrichment.workflow import SignupEnrichmentInputs


def ensure_backfill_allowed() -> None:
    # The kill switch is the master control for sending org data to the provider; a backfill
    # must not defeat it if it was turned off for a compliance, cost, or vendor reason.
    if not gates.enrichment_enabled():
        raise EnrichmentDisabled()
    if not gates.region_allowed():
        raise RegionNotAllowed()


def iter_signups_missing_enrichment(
    *, after: dt.datetime, before: dt.datetime
) -> Iterator[SignupCandidate | SignupSkip]:
    ensure_backfill_allowed()
    return _iter_candidates(after=after, before=before)


def _iter_candidates(*, after: dt.datetime, before: dt.datetime) -> Iterator[SignupCandidate | SignupSkip]:
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
    for org in orgs:
        identity = gates.resolve_signup_identity(str(org.id))
        if isinstance(identity, gates.SignupIdentitySkip):
            yield SignupSkip(organization_id=str(org.id), created_at=org.created_at, reason=identity.reason)
            continue
        yield SignupCandidate(
            organization_id=str(org.id),
            created_at=org.created_at,
            distinct_id=identity.distinct_id,
            domain=identity.domain,
        )


def dispatch(candidate: SignupCandidate) -> None:
    dispatch_signup_enrichment(
        SignupEnrichmentInputs(
            organization_id=candidate.organization_id, distinct_id=candidate.distinct_id, domain=candidate.domain
        )
    )
