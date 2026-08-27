import uuid
from io import StringIO
from typing import Any, Optional

from posthog.test.base import BaseTest
from unittest.mock import AsyncMock, MagicMock, patch

from django.core.management import call_command

from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.user import User

from products.growth.backend.enrichment.fields import EnrichmentFields
from products.growth.backend.enrichment.providers import ProviderLookup
from products.growth.backend.models import OrganizationEnrichment, OrganizationEnrichmentFetch

_COMMAND_MODULE = "products.growth.backend.management.commands.backfill_harmonic_ownership"


def _lookup(
    *,
    ownership_status: Optional[str] = None,
    parent_company: Optional[str] = None,
    parent_company_domain: Optional[str] = None,
    found: bool = True,
) -> ProviderLookup:
    if not found:
        return ProviderLookup(fields=None, raw_payload=None)
    fields = EnrichmentFields(
        company_type="STARTUP",  # a fresh-fetch field the backfill must never write back.
        ownership_status=ownership_status,
        parent_company=parent_company,
        parent_company_domain=parent_company_domain,
    )
    raw_payload = {"companyType": "STARTUP", "ownershipStatus": ownership_status}
    return ProviderLookup(fields=fields, raw_payload=raw_payload)


def _mock_provider(side_effect: list[Any]) -> MagicMock:
    provider_cls = MagicMock()
    provider_cls.return_value.name = "harmonic"
    provider_cls.return_value.enrich_by_domain = AsyncMock(side_effect=side_effect)
    return provider_cls


class _BackfillTestCase(BaseTest):
    def _org(
        self,
        *,
        email: str,
        data: Optional[dict[str, Any]] = None,
        id: Optional[uuid.UUID] = None,
        with_fetch: bool = True,
    ) -> OrganizationEnrichment:
        # with_fetch defaults True: every other test in this file models a work-domain org the
        # live pipeline already enriched, which always leaves a fetch row behind. Only the
        # personal-domain selection test needs the fetch-less shape, via with_fetch=False.
        org = Organization.objects.create(name=email)
        user = User.objects.create_user(email=email, password=None, first_name="t")
        OrganizationMembership.objects.create(organization=org, user=user)
        kwargs: dict[str, Any] = {"organization": org, "data": data if data is not None else {}}
        if id is not None:
            kwargs["id"] = id
        record = OrganizationEnrichment.objects.create(**kwargs)
        if with_fetch:
            OrganizationEnrichmentFetch.objects.create(organization=org, provider="harmonic")
        return record


class TestWritePath(_BackfillTestCase):
    def test_writes_only_the_three_ownership_keys_and_group_props(self):
        record = self._org(email="a@acme.com", data={"company_type": "OLD_VALUE", "headcount": 42})
        pha_client = MagicMock()
        provider_cls = _mock_provider(
            [
                _lookup(
                    ownership_status="ACQUIRED_OR_MERGED",
                    parent_company="Salesforce",
                    parent_company_domain="salesforce.com",
                )
            ]
        )

        with (
            patch(f"{_COMMAND_MODULE}.HarmonicEnrichmentProvider", provider_cls),
            patch(f"{_COMMAND_MODULE}.get_client", return_value=pha_client),
        ):
            call_command("backfill_harmonic_ownership", sleep=0)

        record.refresh_from_db()
        assert record.data == {
            "company_type": "OLD_VALUE",
            "headcount": 42,
            "ownership_status": "ACQUIRED_OR_MERGED",
            "parent_company": "Salesforce",
            "parent_company_domain": "salesforce.com",
        }
        pha_client.group_identify.assert_called_once_with(
            "organization",
            str(record.organization_id),
            properties={
                "enrichment_ownership_status": "ACQUIRED_OR_MERGED",
                "enrichment_parent_company": "Salesforce",
                "enrichment_parent_company_domain": "salesforce.com",
            },
        )
        pha_client.shutdown.assert_called_once()
        fetch = OrganizationEnrichmentFetch.objects.get(organization=record.organization, is_recheck=True)
        assert fetch.provider == "harmonic"
        assert fetch.payload == {"companyType": "STARTUP", "ownershipStatus": "ACQUIRED_OR_MERGED"}

    def test_skips_the_write_but_still_counts_processed_when_ownership_status_is_none(self):
        record = self._org(email="a@acme.com", data={"company_type": "STARTUP"})
        pha_client = MagicMock()
        provider_cls = _mock_provider([_lookup(ownership_status=None)])
        out = StringIO()

        with (
            patch(f"{_COMMAND_MODULE}.HarmonicEnrichmentProvider", provider_cls),
            patch(f"{_COMMAND_MODULE}.get_client", return_value=pha_client),
        ):
            call_command("backfill_harmonic_ownership", sleep=0, stdout=out)

        record.refresh_from_db()
        assert record.data == {"company_type": "STARTUP"}
        pha_client.group_identify.assert_not_called()
        summary = out.getvalue()
        assert "processed 1" in summary
        assert "found_no_ownership_status 1" in summary
        assert "classified 0" in summary
        # The write skip only applies to OrganizationEnrichment.data/group properties — the
        # archive still happens, since it's a distinct, append-only store.
        assert OrganizationEnrichmentFetch.objects.filter(organization=record.organization).exists()


class TestSelection(_BackfillTestCase):
    def test_orgs_already_backfilled_are_skipped(self):
        self._org(email="done@acme.com", data={"ownership_status": "ACTIVE"})
        target = self._org(email="pending@acme.com", data={})
        provider_cls = _mock_provider([_lookup(ownership_status="ACTIVE")])

        with (
            patch(f"{_COMMAND_MODULE}.HarmonicEnrichmentProvider", provider_cls),
            patch(f"{_COMMAND_MODULE}.get_client", return_value=MagicMock()),
        ):
            call_command("backfill_harmonic_ownership", sleep=0)

        provider_cls.return_value.enrich_by_domain.assert_called_once_with("acme.com")
        target.refresh_from_db()
        assert target.data["ownership_status"] == "ACTIVE"

    def test_personal_domain_orgs_without_a_fetch_row_are_excluded(self):
        personal = self._org(email="a@gmail.com", data={"work_email": False}, with_fetch=False)
        work = self._org(email="b@acme.com", data={"work_email": True})
        provider_cls = _mock_provider([_lookup(ownership_status="ACTIVE")])

        with (
            patch(f"{_COMMAND_MODULE}.HarmonicEnrichmentProvider", provider_cls),
            patch(f"{_COMMAND_MODULE}.get_client", return_value=MagicMock()),
        ):
            call_command("backfill_harmonic_ownership", sleep=0)

        provider_cls.return_value.enrich_by_domain.assert_called_once_with("acme.com")
        personal.refresh_from_db()
        work.refresh_from_db()
        assert "ownership_status" not in personal.data
        assert work.data["ownership_status"] == "ACTIVE"

    def test_orgs_flagged_work_email_false_are_excluded_even_with_a_fetch_row(self):
        # Pins the work_email exclude as the deciding factor: this org HAS a fetch row, so
        # only the exclude keeps it out. Deleting the exclude would pass every other test.
        flagged = self._org(email="a@gmail.com", data={"work_email": False})
        self._org(email="b@acme.com", data={})
        provider_cls = _mock_provider([_lookup(ownership_status="ACTIVE")])

        with (
            patch(f"{_COMMAND_MODULE}.HarmonicEnrichmentProvider", provider_cls),
            patch(f"{_COMMAND_MODULE}.get_client", return_value=MagicMock()),
        ):
            call_command("backfill_harmonic_ownership", sleep=0)

        provider_cls.return_value.enrich_by_domain.assert_called_once_with("acme.com")
        flagged.refresh_from_db()
        assert "ownership_status" not in flagged.data


class TestDryRun(_BackfillTestCase):
    def test_dry_run_writes_nothing_and_never_touches_the_network_client(self):
        record = self._org(email="a@acme.com", data={})
        provider_cls = _mock_provider(
            [
                _lookup(
                    ownership_status="ACQUIRED_OR_MERGED",
                    parent_company="Salesforce",
                    parent_company_domain="salesforce.com",
                )
            ]
        )

        with (
            patch(f"{_COMMAND_MODULE}.HarmonicEnrichmentProvider", provider_cls),
            patch(f"{_COMMAND_MODULE}.get_client") as get_client_mock,
        ):
            call_command("backfill_harmonic_ownership", "--dry-run", sleep=0)

        get_client_mock.assert_not_called()
        record.refresh_from_db()
        assert record.data == {}
        assert not OrganizationEnrichmentFetch.objects.filter(
            organization=record.organization, is_recheck=True
        ).exists()


class TestArchive(_BackfillTestCase):
    def test_archives_the_miss_payload_on_a_not_found_fetch(self):
        record = self._org(email="a@acme.com", data={})
        provider_cls = _mock_provider([_lookup(found=False)])

        with (
            patch(f"{_COMMAND_MODULE}.HarmonicEnrichmentProvider", provider_cls),
            patch(f"{_COMMAND_MODULE}.get_client", return_value=MagicMock()),
        ):
            call_command("backfill_harmonic_ownership", sleep=0)

        fetch = OrganizationEnrichmentFetch.objects.get(organization=record.organization, is_recheck=True)
        assert fetch.provider == "harmonic"
        assert fetch.payload == {"companyFound": False}

    def test_a_fetch_failure_archives_nothing(self):
        record = self._org(email="a@acme.com", data={})
        provider_cls = _mock_provider([RuntimeError("harmonic is down")])

        with (
            patch(f"{_COMMAND_MODULE}.HarmonicEnrichmentProvider", provider_cls),
            patch(f"{_COMMAND_MODULE}.get_client", return_value=MagicMock()),
            patch(f"{_COMMAND_MODULE}.capture_exception"),
        ):
            call_command("backfill_harmonic_ownership", sleep=0)

        assert not OrganizationEnrichmentFetch.objects.filter(
            organization=record.organization, is_recheck=True
        ).exists()


class TestResume(_BackfillTestCase):
    def test_after_id_resumes_past_already_seen_orgs(self):
        # Explicit ids (rather than relying on uuid7's real-time ordering) make the id__gt
        # boundary deterministic regardless of how close together the two creates land.
        first = self._org(email="a@acme.com", data={}, id=uuid.UUID(int=1))
        second = self._org(email="b@acme.com", data={}, id=uuid.UUID(int=2))
        provider_cls = _mock_provider([_lookup(ownership_status="ACTIVE")])

        with (
            patch(f"{_COMMAND_MODULE}.HarmonicEnrichmentProvider", provider_cls),
            patch(f"{_COMMAND_MODULE}.get_client", return_value=MagicMock()),
        ):
            call_command("backfill_harmonic_ownership", after_id=str(first.id), sleep=0)

        provider_cls.return_value.enrich_by_domain.assert_called_once_with("acme.com")
        first.refresh_from_db()
        second.refresh_from_db()
        assert "ownership_status" not in first.data
        assert second.data["ownership_status"] == "ACTIVE"


class TestSummary(_BackfillTestCase):
    def test_summary_counts_every_outcome(self):
        self._org(email="acquired-with-parent@acme.com", data={})
        self._org(email="acquired-no-parent@acme.com", data={})
        self._org(email="active@acme.com", data={})
        self._org(email="miss@acme.com", data={})
        self._org(email="broken@acme.com", data={})

        provider_cls = _mock_provider(
            [
                _lookup(
                    ownership_status="ACQUIRED_OR_MERGED",
                    parent_company="Salesforce",
                    parent_company_domain="salesforce.com",
                ),
                _lookup(ownership_status="ACQUIRED_OR_MERGED"),
                _lookup(ownership_status="ACTIVE"),
                _lookup(found=False),
                RuntimeError("harmonic is down"),
            ]
        )
        out = StringIO()
        with (
            patch(f"{_COMMAND_MODULE}.HarmonicEnrichmentProvider", provider_cls),
            patch(f"{_COMMAND_MODULE}.get_client", return_value=MagicMock()),
            patch(f"{_COMMAND_MODULE}.capture_exception") as capture_mock,
        ):
            call_command("backfill_harmonic_ownership", sleep=0, stdout=out)

        summary = out.getvalue()
        assert "processed 5" in summary
        assert "fetch_failures 1" in summary
        assert "not_found 1" in summary
        # The not-found and the failed fetch are unknowns, so they stay out of the rate's
        # denominator: 2 of the 3 orgs Harmonic actually classified, not 2 of 5 attempted.
        assert "classified 3 (60.0% of processed)" in summary
        assert "acquired_or_merged 2 (66.7% of classified)" in summary
        assert "acquired_or_merged_with_parent 1 (50.0% of acquired_or_merged)" in summary
        capture_mock.assert_called_once()
