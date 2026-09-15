import uuid
from io import StringIO
from typing import Any, Optional

from posthog.test.base import BaseTest
from unittest.mock import AsyncMock, MagicMock, call, patch

from django.core.management import CommandError, call_command

from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.user import User

from products.growth.backend.enrichment.fields import EnrichmentFields
from products.growth.backend.enrichment.providers import ProviderLookup
from products.growth.backend.models import OrganizationEnrichment, OrganizationEnrichmentFetch

_LOGIC_MODULE = "products.growth.backend.enrichment.ownership_backfill"


def _lookup(
    *,
    ownership_status: Optional[str] = None,
    parent_company: Optional[str] = None,
    parent_company_domain: Optional[str] = None,
    found: bool = True,
    enrichment_urn: Optional[str] = None,
) -> ProviderLookup:
    if not found:
        return ProviderLookup(fields=None, raw_payload=None, enrichment_urn=enrichment_urn)
    fields = EnrichmentFields(
        company_type="STARTUP",  # a fresh-fetch field the backfill must never write back.
        ownership_status=ownership_status,
        parent_company=parent_company,
        parent_company_domain=parent_company_domain,
    )
    raw_payload = {"companyType": "STARTUP", "ownershipStatus": ownership_status}
    return ProviderLookup(fields=fields, raw_payload=raw_payload, enrichment_urn=enrichment_urn)


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
        member: bool = True,
    ) -> OrganizationEnrichment:
        # with_fetch defaults True: every other test in this file models a work-domain org the
        # live pipeline already enriched, which always leaves a fetch row behind. Only the
        # personal-domain selection test needs the fetch-less shape, via with_fetch=False.
        org = Organization.objects.create(name=email)
        if member:
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
                    enrichment_urn="urn:harmonic:enrichment:archived",
                )
            ]
        )

        with (
            patch(f"{_LOGIC_MODULE}.HarmonicEnrichmentProvider", provider_cls),
            patch(f"{_LOGIC_MODULE}.get_client", return_value=pha_client),
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
        assert fetch.payload == {
            "companyType": "STARTUP",
            "ownershipStatus": "ACQUIRED_OR_MERGED",
            "enrichmentUrn": "urn:harmonic:enrichment:archived",
        }

    def test_skips_the_write_but_still_counts_processed_when_ownership_status_is_none(self):
        record = self._org(email="a@acme.com", data={"company_type": "STARTUP"})
        pha_client = MagicMock()
        provider_cls = _mock_provider([_lookup(ownership_status=None)])
        out = StringIO()

        with (
            patch(f"{_LOGIC_MODULE}.HarmonicEnrichmentProvider", provider_cls),
            patch(f"{_LOGIC_MODULE}.get_client", return_value=pha_client),
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
            patch(f"{_LOGIC_MODULE}.HarmonicEnrichmentProvider", provider_cls),
            patch(f"{_LOGIC_MODULE}.get_client", return_value=MagicMock()),
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
            patch(f"{_LOGIC_MODULE}.HarmonicEnrichmentProvider", provider_cls),
            patch(f"{_LOGIC_MODULE}.get_client", return_value=MagicMock()),
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
            patch(f"{_LOGIC_MODULE}.HarmonicEnrichmentProvider", provider_cls),
            patch(f"{_LOGIC_MODULE}.get_client", return_value=MagicMock()),
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
            patch(f"{_LOGIC_MODULE}.HarmonicEnrichmentProvider", provider_cls),
            patch(f"{_LOGIC_MODULE}.get_client") as get_client_mock,
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
        provider_cls = _mock_provider([_lookup(found=False, enrichment_urn="urn:harmonic:enrichment:miss")])

        with (
            patch(f"{_LOGIC_MODULE}.HarmonicEnrichmentProvider", provider_cls),
            patch(f"{_LOGIC_MODULE}.get_client", return_value=MagicMock()),
        ):
            call_command("backfill_harmonic_ownership", sleep=0)

        fetch = OrganizationEnrichmentFetch.objects.get(organization=record.organization, is_recheck=True)
        assert fetch.provider == "harmonic"
        assert fetch.payload == {"companyFound": False, "enrichmentUrn": "urn:harmonic:enrichment:miss"}

    def test_a_fetch_failure_archives_nothing(self):
        record = self._org(email="a@acme.com", data={})
        provider_cls = _mock_provider([RuntimeError("harmonic is down")])

        with (
            patch(f"{_LOGIC_MODULE}.HarmonicEnrichmentProvider", provider_cls),
            patch(f"{_LOGIC_MODULE}.get_client", return_value=MagicMock()),
            patch(f"{_LOGIC_MODULE}.capture_exception"),
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
            patch(f"{_LOGIC_MODULE}.HarmonicEnrichmentProvider", provider_cls),
            patch(f"{_LOGIC_MODULE}.get_client", return_value=MagicMock()),
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
            patch(f"{_LOGIC_MODULE}.HarmonicEnrichmentProvider", provider_cls),
            patch(f"{_LOGIC_MODULE}.get_client", return_value=MagicMock()),
            patch(f"{_LOGIC_MODULE}.capture_exception") as capture_mock,
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


_SEED_FETCH_ROW: tuple[str, bool, dict[str, Any]] = ("harmonic", False, {})


def _fetch_rows(record: OrganizationEnrichment) -> list[tuple[str, bool, dict[str, Any]]]:
    return list(
        OrganizationEnrichmentFetch.objects.filter(organization=record.organization)
        .order_by("id")
        .values_list("provider", "is_recheck", "payload")
    )


def _data(record: OrganizationEnrichment) -> dict[str, Any]:
    record.refresh_from_db()
    return record.data


class TestBackfillHarmonicOwnershipGolden(_BackfillTestCase):
    def setUp(self):
        super().setUp()
        self.pha_client = MagicMock()
        self.get_client = self.enterContext(patch(f"{_LOGIC_MODULE}.get_client", return_value=self.pha_client))
        self.capture_exception = self.enterContext(patch(f"{_LOGIC_MODULE}.capture_exception"))
        self.out = StringIO()

    def _run(self, *args: str, lookups: list[Any], **options: Any) -> str:
        provider_cls = _mock_provider(lookups)
        self.enrich_by_domain = provider_cls.return_value.enrich_by_domain
        with patch(f"{_LOGIC_MODULE}.HarmonicEnrichmentProvider", provider_cls):
            call_command("backfill_harmonic_ownership", *args, sleep=0, stdout=self.out, **options)
        return self.out.getvalue()

    def _four_outcomes(self) -> list[OrganizationEnrichment]:
        return [
            self._org(
                email="a@acquired.com", data={"company_type": "STARTUP", "work_email": True}, id=uuid.UUID(int=1)
            ),
            self._org(email="b@private.com", data={"headcount": 42}, id=uuid.UUID(int=2)),
            self._org(email="c@missing.com", data={}, id=uuid.UUID(int=3)),
            self._org(email="d@silent.com", data={"country": "DE"}, id=uuid.UUID(int=4)),
        ]

    def _four_lookups(self) -> list[Any]:
        return [
            _lookup(
                ownership_status="ACQUIRED_OR_MERGED",
                parent_company="Salesforce",
                parent_company_domain="salesforce.com",
                enrichment_urn="urn:harmonic:enrichment:1",
            ),
            _lookup(ownership_status="PRIVATE", enrichment_urn="urn:harmonic:enrichment:2"),
            _lookup(found=False, enrichment_urn="urn:harmonic:enrichment:3"),
            _lookup(ownership_status=None),
        ]

    def test_writes_archives_and_summarises_every_outcome_in_id_order(self):
        acquired, private, missing, silent = self._four_outcomes()

        stdout = self._run(lookups=self._four_lookups())

        assert stdout == (
            "processed 4, fetch_failures 0, not_found 1, no_domain 0, found_no_ownership_status 1, errors 0, "
            "classified 2 (50.0% of processed), acquired_or_merged 1 (50.0% of classified), "
            "acquired_or_merged_with_parent 1 (100.0% of acquired_or_merged), "
            "last_id=00000000-0000-0000-0000-000000000004\n"
        )
        assert self.enrich_by_domain.call_args_list == [
            call("acquired.com"),
            call("private.com"),
            call("missing.com"),
            call("silent.com"),
        ]
        assert _data(acquired) == {
            "company_type": "STARTUP",
            "work_email": True,
            "ownership_status": "ACQUIRED_OR_MERGED",
            "parent_company": "Salesforce",
            "parent_company_domain": "salesforce.com",
        }
        assert _data(private) == {"headcount": 42, "ownership_status": "PRIVATE"}
        assert _data(missing) == {}
        assert _data(silent) == {"country": "DE"}
        assert _fetch_rows(acquired) == [
            _SEED_FETCH_ROW,
            (
                "harmonic",
                True,
                {
                    "companyType": "STARTUP",
                    "ownershipStatus": "ACQUIRED_OR_MERGED",
                    "enrichmentUrn": "urn:harmonic:enrichment:1",
                },
            ),
        ]
        assert _fetch_rows(private) == [
            _SEED_FETCH_ROW,
            (
                "harmonic",
                True,
                {"companyType": "STARTUP", "ownershipStatus": "PRIVATE", "enrichmentUrn": "urn:harmonic:enrichment:2"},
            ),
        ]
        assert _fetch_rows(missing) == [
            _SEED_FETCH_ROW,
            ("harmonic", True, {"companyFound": False, "enrichmentUrn": "urn:harmonic:enrichment:3"}),
        ]
        assert _fetch_rows(silent) == [
            _SEED_FETCH_ROW,
            ("harmonic", True, {"companyType": "STARTUP", "ownershipStatus": None, "enrichmentUrn": None}),
        ]
        assert self.pha_client.group_identify.call_args_list == [
            call(
                "organization",
                str(acquired.organization_id),
                properties={
                    "enrichment_ownership_status": "ACQUIRED_OR_MERGED",
                    "enrichment_parent_company": "Salesforce",
                    "enrichment_parent_company_domain": "salesforce.com",
                },
            ),
            call(
                "organization",
                str(private.organization_id),
                properties={"enrichment_ownership_status": "PRIVATE"},
            ),
        ]
        self.pha_client.set.assert_not_called()
        self.pha_client.shutdown.assert_called_once()
        self.capture_exception.assert_not_called()

    def test_dry_run_fetches_and_counts_without_writing(self):
        records = self._four_outcomes()

        stdout = self._run("--dry-run", lookups=self._four_lookups())

        assert stdout == (
            "processed 4, fetch_failures 0, not_found 1, no_domain 0, found_no_ownership_status 1, errors 0, "
            "classified 2 (50.0% of processed), acquired_or_merged 1 (50.0% of classified), "
            "acquired_or_merged_with_parent 1 (100.0% of acquired_or_merged), "
            "last_id=00000000-0000-0000-0000-000000000004\n"
        )
        assert self.enrich_by_domain.call_args_list == [
            call("acquired.com"),
            call("private.com"),
            call("missing.com"),
            call("silent.com"),
        ]
        assert [_data(record) for record in records] == [
            {"company_type": "STARTUP", "work_email": True},
            {"headcount": 42},
            {},
            {"country": "DE"},
        ]
        assert [_fetch_rows(record) for record in records] == [[_SEED_FETCH_ROW]] * 4
        self.get_client.assert_not_called()
        self.pha_client.group_identify.assert_not_called()
        self.pha_client.shutdown.assert_not_called()

    def test_a_provider_failure_is_counted_reported_and_skipped_over(self):
        broken = self._org(email="a@broken.com", data={"work_email": True}, id=uuid.UUID(int=1))
        private = self._org(email="b@private.com", data={}, id=uuid.UUID(int=2))
        error = RuntimeError("harmonic is down")

        stdout = self._run(lookups=[error, _lookup(ownership_status="PRIVATE")])

        assert stdout == (
            "processed 2, fetch_failures 1, not_found 0, no_domain 0, found_no_ownership_status 0, errors 0, "
            "classified 1 (50.0% of processed), acquired_or_merged 0 (0.0% of classified), "
            "acquired_or_merged_with_parent 0 (0.0% of acquired_or_merged), "
            "last_id=00000000-0000-0000-0000-000000000002\n"
        )
        assert self.capture_exception.call_args_list == [
            call(error, {"organization_id": str(broken.organization_id), "domain": "broken.com"})
        ]
        assert _data(broken) == {"work_email": True}
        assert _fetch_rows(broken) == [_SEED_FETCH_ROW]
        assert _data(private) == {"ownership_status": "PRIVATE"}
        assert _fetch_rows(private) == [
            _SEED_FETCH_ROW,
            ("harmonic", True, {"companyType": "STARTUP", "ownershipStatus": "PRIVATE", "enrichmentUrn": None}),
        ]
        assert self.pha_client.group_identify.call_args_list == [
            call("organization", str(private.organization_id), properties={"enrichment_ownership_status": "PRIVATE"})
        ]
        self.pha_client.set.assert_not_called()
        self.pha_client.shutdown.assert_called_once()

    def test_after_id_resumes_past_the_given_record(self):
        first = self._org(email="a@first.com", data={}, id=uuid.UUID(int=1))
        second = self._org(email="b@second.com", data={}, id=uuid.UUID(int=2))
        third = self._org(email="c@third.com", data={}, id=uuid.UUID(int=3))

        stdout = self._run(
            after_id=str(first.id),
            lookups=[_lookup(ownership_status="PRIVATE"), _lookup(ownership_status="PUBLIC")],
        )

        assert stdout == (
            "processed 2, fetch_failures 0, not_found 0, no_domain 0, found_no_ownership_status 0, errors 0, "
            "classified 2 (100.0% of processed), acquired_or_merged 0 (0.0% of classified), "
            "acquired_or_merged_with_parent 0 (0.0% of acquired_or_merged), "
            "last_id=00000000-0000-0000-0000-000000000003\n"
        )
        assert self.enrich_by_domain.call_args_list == [call("second.com"), call("third.com")]
        assert _data(first) == {}
        assert _fetch_rows(first) == [_SEED_FETCH_ROW]
        assert _data(second) == {"ownership_status": "PRIVATE"}
        assert _data(third) == {"ownership_status": "PUBLIC"}
        assert self.pha_client.group_identify.call_args_list == [
            call("organization", str(second.organization_id), properties={"enrichment_ownership_status": "PRIVATE"}),
            call("organization", str(third.organization_id), properties={"enrichment_ownership_status": "PUBLIC"}),
        ]
        self.pha_client.shutdown.assert_called_once()

    def test_after_id_past_the_last_record_echoes_it_as_last_id(self):
        self._org(email="a@first.com", data={}, id=uuid.UUID(int=1))

        stdout = self._run(after_id=str(uuid.UUID(int=1)), lookups=[])

        assert stdout == (
            "processed 0, fetch_failures 0, not_found 0, no_domain 0, found_no_ownership_status 0, errors 0, "
            "classified 0 (0.0% of processed), acquired_or_merged 0 (0.0% of classified), "
            "acquired_or_merged_with_parent 0 (0.0% of acquired_or_merged), "
            "last_id=00000000-0000-0000-0000-000000000001\n"
        )
        self.enrich_by_domain.assert_not_called()
        self.pha_client.group_identify.assert_not_called()
        self.pha_client.shutdown.assert_called_once()

    def test_rejects_a_limit_below_one_and_a_negative_sleep(self):
        with self.assertRaises(CommandError) as limit_error:
            self._run(lookups=[], limit=0)
        assert str(limit_error.exception) == "--limit must be at least 1"

        with self.assertRaises(CommandError) as sleep_error:
            call_command("backfill_harmonic_ownership", sleep=-1, stdout=self.out)
        assert str(sleep_error.exception) == "--sleep must be at least 0"

        assert self.out.getvalue() == ""
        self.get_client.assert_not_called()

    def test_counts_a_memberless_org_as_no_domain_and_never_selects_a_personal_domain_record(self):
        memberless = self._org(email="a@nobody.com", data={"work_email": True}, id=uuid.UUID(int=1), member=False)
        personal = self._org(email="b@gmail.com", data={"work_email": False}, id=uuid.UUID(int=2))

        stdout = self._run(lookups=[])

        assert stdout == (
            "processed 1, fetch_failures 0, not_found 0, no_domain 1, found_no_ownership_status 0, errors 0, "
            "classified 0 (0.0% of processed), acquired_or_merged 0 (0.0% of classified), "
            "acquired_or_merged_with_parent 0 (0.0% of acquired_or_merged), "
            "last_id=00000000-0000-0000-0000-000000000001\n"
        )
        self.enrich_by_domain.assert_not_called()
        assert _data(memberless) == {"work_email": True}
        assert _data(personal) == {"work_email": False}
        assert _fetch_rows(memberless) == [_SEED_FETCH_ROW]
        assert _fetch_rows(personal) == [_SEED_FETCH_ROW]
        self.pha_client.group_identify.assert_not_called()
        self.pha_client.shutdown.assert_called_once()
