import datetime as dt

from posthog.test.base import BaseTest
from unittest.mock import AsyncMock, MagicMock, patch

from django.test import override_settings

from asgiref.sync import async_to_sync

from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.user import User

from products.growth.backend.enrichment.core import EnrichmentOutcome
from products.growth.backend.enrichment.fields import EnrichmentFields
from products.growth.backend.enrichment.fit_score import IcpFitResult
from products.growth.backend.models import OrganizationEnrichment, OrganizationEnrichmentFetch
from products.growth.backend.temporal.signup_enrichment.reenrichment import (
    IcpReenrichmentSweepInputs,
    ReenrichOrgInputs,
    reenrich_organization_activity,
    select_reenrichment_candidates_activity,
)

_MODULE = "products.growth.backend.temporal.signup_enrichment.reenrichment"


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


@override_settings(CLOUD_DEPLOYMENT="US", GROWTH_SIGNUP_ENRICHMENT_ENABLED=True, GROWTH_ICP_REENRICH_DAILY_CAP=500)
class TestReenrichmentSelection(BaseTest):
    def _org_with_member(self, email: str) -> Organization:
        organization = Organization.objects.create(name=email)
        user = User.objects.create_user(email=email, password=None, first_name="sweep")
        OrganizationMembership.objects.create(organization=organization, user=user)
        return organization

    def _prime(
        self,
        organization: Organization,
        *,
        status: str = "insufficient_data",
        latest_fetch_days_ago: int = 31,
        first_fetch_days_ago: int = 40,
        signup_role: str | None = None,
    ) -> None:
        data: dict = {"icp_fit_status": status, "work_email": True}
        if signup_role:
            data["signup_role"] = signup_role
        OrganizationEnrichment.objects.create(organization=organization, data=data)
        first = OrganizationEnrichmentFetch.objects.create(
            organization=organization, provider="harmonic", payload={"companyFound": False}
        )
        OrganizationEnrichmentFetch.objects.filter(id=first.id).update(
            fetched_at=_now() - dt.timedelta(days=first_fetch_days_ago)
        )
        if latest_fetch_days_ago != first_fetch_days_ago:
            latest = OrganizationEnrichmentFetch.objects.create(
                organization=organization, provider="harmonic", payload={"companyFound": False}, is_recheck=True
            )
            OrganizationEnrichmentFetch.objects.filter(id=latest.id).update(
                fetched_at=_now() - dt.timedelta(days=latest_fetch_days_ago)
            )

    def _select(self, cap: int | None = None):
        with patch(f"{_MODULE}.LOGGER"):
            return async_to_sync(select_reenrichment_candidates_activity)(IcpReenrichmentSweepInputs(cap=cap))

    def test_selects_due_orgs_with_identity_and_role(self):
        organization = self._org_with_member("founder@due.example")
        self._prime(organization, latest_fetch_days_ago=31, first_fetch_days_ago=40, signup_role="engineering")

        candidates = self._select()

        assert len(candidates) == 1
        candidate = candidates[0]
        assert candidate["organization_id"] == str(organization.id)
        assert candidate["domain"] == "due.example"
        assert candidate["role_at_organization"] == "engineering"
        assert candidate["distinct_id"]

    def test_window_and_status_exclusions(self):
        too_recent = self._org_with_member("a@recent.example")
        self._prime(too_recent, latest_fetch_days_ago=10, first_fetch_days_ago=40)

        aged_out = self._org_with_member("b@aged.example")
        self._prime(aged_out, latest_fetch_days_ago=35, first_fetch_days_ago=100)

        already_scored = self._org_with_member("c@scored.example")
        self._prime(already_scored, status="scored", latest_fetch_days_ago=31, first_fetch_days_ago=40)

        due = self._org_with_member("d@due.example")
        self._prime(due, latest_fetch_days_ago=31, first_fetch_days_ago=40)

        candidates = self._select()

        assert [c["organization_id"] for c in candidates] == [str(due.id)]

    def test_cap_takes_the_oldest_fetches_first(self):
        newer = self._org_with_member("newer@cap.example")
        self._prime(newer, latest_fetch_days_ago=31, first_fetch_days_ago=45)
        older = self._org_with_member("older@cap.example")
        self._prime(older, latest_fetch_days_ago=60, first_fetch_days_ago=70)

        candidates = self._select(cap=1)

        assert [c["organization_id"] for c in candidates] == [str(older.id)]

    def test_skips_org_whose_signup_user_left(self):
        organization = Organization.objects.create(name="left.example")
        user = User.objects.create_user(email="late@left.example", password=None, first_name="late")
        membership = OrganizationMembership.objects.create(organization=organization, user=user)
        # The earliest remaining membership joined long after signup: nobody can stand in
        # for the signup identity.
        OrganizationMembership.objects.filter(id=membership.id).update(
            joined_at=organization.created_at + dt.timedelta(hours=6)
        )
        self._prime(organization)

        assert self._select() == []

    @override_settings(GROWTH_SIGNUP_ENRICHMENT_ENABLED=False)
    def test_kill_switch_stops_the_sweep(self):
        organization = self._org_with_member("off@switch.example")
        self._prime(organization)

        assert self._select() == []

    def test_a_new_fetch_resets_the_thirty_day_clock(self):
        organization = self._org_with_member("reset@clock.example")
        self._prime(organization, latest_fetch_days_ago=31, first_fetch_days_ago=40)
        assert len(self._select()) == 1

        # The sweep's own fetch (or any recheck) arrives: no retry for another 30 days.
        fresh = OrganizationEnrichmentFetch.objects.create(
            organization=organization, provider="harmonic", payload={"companyFound": False}, is_recheck=True
        )
        OrganizationEnrichmentFetch.objects.filter(id=fresh.id).update(fetched_at=_now() - dt.timedelta(days=1))
        assert self._select() == []


class TestReenrichOrganizationActivity(BaseTest):
    def _run(self, outcome: EnrichmentOutcome) -> tuple[dict, MagicMock, AsyncMock]:
        pha_client = MagicMock()
        enrich = AsyncMock(return_value=outcome)
        with (
            patch(f"{_MODULE}.get_regional_ph_client", return_value=pha_client),
            patch("products.growth.backend.enrichment.core.enrich_organization", enrich),
        ):
            result = async_to_sync(reenrich_organization_activity)(
                ReenrichOrgInputs(
                    organization_id=str(self.organization.id),
                    distinct_id="signer",
                    domain="stripe.com",
                    role_at_organization="engineering",
                )
            )
        return result, pha_client, enrich

    def test_reenriches_as_a_recheck_and_emits_its_own_event(self):
        outcome = EnrichmentOutcome(
            provider_fields=EnrichmentFields(company_type="STARTUP"),
            fit=IcpFitResult(status="scored", score=48),
        )
        result, pha_client, enrich = self._run(outcome)

        assert result == {"matched": True, "icp_fit_status": "scored"}
        assert enrich.await_args is not None
        assert enrich.await_args.kwargs["is_recheck"] is True
        assert enrich.await_args.kwargs["role_at_organization"] == "engineering"
        event = pha_client.capture.call_args
        assert event.kwargs["event"] == "icp_reenrichment_completed"
        assert event.kwargs["properties"]["icp_fit_status"] == "scored"
        assert event.kwargs["properties"]["matched"] is True
        pha_client.shutdown.assert_called_once()

    def test_still_unmatched_reports_honestly(self):
        outcome = EnrichmentOutcome(provider_fields=None, fit=IcpFitResult(status="not_found"))
        result, pha_client, _ = self._run(outcome)

        assert result == {"matched": False, "icp_fit_status": "not_found"}
        assert pha_client.capture.call_args.kwargs["properties"]["icp_fit_status"] == "not_found"

    def test_skips_an_org_deleted_after_selection_without_writing_anything(self):
        doomed = Organization.objects.create(name="doomed.example")
        organization_id = str(doomed.id)
        doomed.delete()

        pha_client = MagicMock()
        enrich = AsyncMock()
        with (
            patch(f"{_MODULE}.get_regional_ph_client", return_value=pha_client),
            patch("products.growth.backend.enrichment.core.enrich_organization", enrich),
        ):
            result = async_to_sync(reenrich_organization_activity)(
                ReenrichOrgInputs(organization_id=organization_id, distinct_id="signer", domain="stripe.com")
            )

        assert result == {"matched": False, "skipped": "organization_deleted"}
        enrich.assert_not_awaited()
        pha_client.capture.assert_not_called()
