from posthog.test.base import BaseTest
from unittest.mock import MagicMock

from parameterized import parameterized

from products.growth.backend.enrichment.snapshot import (
    SNAPSHOT_EVENT_NAME,
    SignupEnrichmentSnapshot,
    capture_signup_enrichment_snapshot,
)
from products.growth.backend.models import EnrichmentSignupSnapshot


class TestSignupEnrichmentSnapshot(BaseTest):
    def test_to_event_properties_suffixes_keys_and_drops_none(self) -> None:
        snapshot = SignupEnrichmentSnapshot(
            company_type="startup",
            headcount=42,
            industry="software",
            icp_fit_score=80,
        )

        properties = snapshot.to_event_properties()

        assert properties == {
            "company_type_at_signup": "startup",
            "headcount_at_signup": 42,
            "industry_at_signup": "software",
            "icp_fit_score_at_signup": 80,
        }
        assert "country_at_signup" not in properties

    def test_icp_fit_status_rides_along_without_a_numeric_score(self) -> None:
        # An insufficient_data evaluation at signup snapshots the status alone, keeping
        # "insufficient at signup" distinguishable from "never evaluated" forever.
        snapshot = SignupEnrichmentSnapshot(company_type="startup", icp_fit_status="insufficient_data")
        properties = snapshot.to_event_properties()
        assert properties["icp_fit_status_at_signup"] == "insufficient_data"
        assert "icp_fit_score_at_signup" not in properties

    def test_emits_person_scoped_event_when_snapshot_lands(self) -> None:
        pha_client = MagicMock()
        snapshot = SignupEnrichmentSnapshot(company_type="startup", headcount=42)

        emitted = capture_signup_enrichment_snapshot(
            pha_client,
            organization_id=str(self.organization.id),
            distinct_id="user-distinct-id",
            snapshot=snapshot,
        )

        assert emitted is True
        pha_client.capture.assert_called_once_with(
            distinct_id="user-distinct-id",
            event=SNAPSHOT_EVENT_NAME,
            properties={"company_type_at_signup": "startup", "headcount_at_signup": 42},
            groups={"organization": str(self.organization.id)},
        )
        assert EnrichmentSignupSnapshot.objects.filter(organization_id=self.organization.id).count() == 1

    def test_written_once_second_call_does_not_re_emit(self) -> None:
        pha_client = MagicMock()
        snapshot = SignupEnrichmentSnapshot(company_type="startup")

        first = capture_signup_enrichment_snapshot(
            pha_client,
            organization_id=str(self.organization.id),
            distinct_id="user-distinct-id",
            snapshot=snapshot,
        )
        second = capture_signup_enrichment_snapshot(
            pha_client,
            organization_id=str(self.organization.id),
            distinct_id="user-distinct-id",
            snapshot=SignupEnrichmentSnapshot(company_type="enterprise"),
        )

        assert first is True
        assert second is False
        pha_client.capture.assert_called_once()
        assert EnrichmentSignupSnapshot.objects.filter(organization_id=self.organization.id).count() == 1

    def test_does_not_emit_when_guard_row_preexists(self) -> None:
        pha_client = MagicMock()
        EnrichmentSignupSnapshot.objects.create(organization_id=self.organization.id)

        emitted = capture_signup_enrichment_snapshot(
            pha_client,
            organization_id=str(self.organization.id),
            distinct_id="user-distinct-id",
            snapshot=SignupEnrichmentSnapshot(company_type="startup"),
        )

        assert emitted is False
        pha_client.capture.assert_not_called()

    @parameterized.expand(
        [
            ("present", "v0.5", True),
            ("absent", None, False),
        ]
    )
    def test_icp_fit_version_in_properties(self, _name: str, icp_fit_version: str | None, expect_version: bool) -> None:
        pha_client = MagicMock()
        snapshot = SignupEnrichmentSnapshot(icp_fit_score=90, icp_fit_version=icp_fit_version)

        capture_signup_enrichment_snapshot(
            pha_client,
            organization_id=str(self.organization.id),
            distinct_id="user-distinct-id",
            snapshot=snapshot,
        )

        _, kwargs = pha_client.capture.call_args
        assert kwargs["properties"]["icp_fit_score_at_signup"] == 90
        assert ("icp_fit_version_at_signup" in kwargs["properties"]) is expect_version
        if expect_version:
            assert kwargs["properties"]["icp_fit_version_at_signup"] == icp_fit_version
