import datetime as dt

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.test import override_settings

from asgiref.sync import async_to_sync

from posthog.models.instance_setting import override_instance_config
from posthog.models.organization import Organization

from products.growth.backend.enrichment.writer import HARMONIC_STATUS_AT_KEY, HARMONIC_STATUS_KEY, HARMONIC_URN_KEY
from products.growth.backend.models import OrganizationEnrichment, OrganizationEnrichmentFetch
from products.growth.backend.temporal.signup_enrichment.harmonic_status_poll import (
    STALL_AGE_HOURS,
    HarmonicStatusPollInputs,
    HarmonicStatusPollRunSummary,
    poll_status_batch_activity,
    report_status_poll_run_activity,
    select_status_poll_candidates_activity,
)

_MODULE = "products.growth.backend.temporal.signup_enrichment.harmonic_status_poll"


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _fetch(organization: Organization, *, urn: str | None, days_ago: float = 0, is_recheck: bool = False):
    row = OrganizationEnrichmentFetch.objects.create(
        organization=organization,
        provider="harmonic",
        is_recheck=is_recheck,
        payload={"companyFound": True, "enrichmentUrn": urn},
    )
    OrganizationEnrichmentFetch.objects.filter(id=row.id).update(fetched_at=_now() - dt.timedelta(days=days_ago))
    return row


@override_settings(CLOUD_DEPLOYMENT="US")
class TestSelectStatusPollCandidates(BaseTest):
    def setUp(self):
        super().setUp()
        self.enterContext(override_instance_config("GROWTH_SIGNUP_ENRICHMENT_ENABLED", True))

    def _select_result(self):
        with patch(f"{_MODULE}.LOGGER"):
            return async_to_sync(select_status_poll_candidates_activity)(HarmonicStatusPollInputs())

    def _select(self):
        return self._select_result()["candidates"]

    def test_selects_an_org_with_a_fresh_open_urn_and_no_stored_status(self):
        organization = Organization.objects.create(name="open.example")
        _fetch(organization, urn="urn:harmonic:enrichment:open", days_ago=1)

        candidates = self._select()

        assert len(candidates) == 1
        assert candidates[0]["organization_id"] == str(organization.id)
        assert candidates[0]["enrichment_urn"] == "urn:harmonic:enrichment:open"
        assert candidates[0]["previous_status"] is None

    def test_excludes_an_org_whose_open_urn_is_30_days_or_older(self):
        organization = Organization.objects.create(name="stale.example")
        _fetch(organization, urn="urn:harmonic:enrichment:stale", days_ago=31)

        assert self._select() == []

    def test_excludes_an_org_with_a_terminal_stored_status_for_the_same_urn(self):
        for status in ("COMPLETE", "FAILED", "NOT_FOUND"):
            organization = Organization.objects.create(name=f"{status.lower()}.example")
            urn = f"urn:harmonic:enrichment:{status}"
            _fetch(organization, urn=urn, days_ago=2)
            OrganizationEnrichment.objects.create(
                organization=organization, data={HARMONIC_STATUS_KEY: status, HARMONIC_URN_KEY: urn}
            )

        assert self._select() == []

    def test_includes_an_org_whose_terminal_stamp_is_for_an_older_urn(self):
        # A re-lookup (backfill_harmonic_ownership, a manual recheck) can issue a fresh URN for
        # an org whose old one already resolved. The old terminal stamp must not block the new
        # URN from ever being polled.
        organization = Organization.objects.create(name="rearmed.example")
        _fetch(organization, urn="urn:harmonic:enrichment:A", days_ago=10)
        _fetch(organization, urn="urn:harmonic:enrichment:B", days_ago=1)
        OrganizationEnrichment.objects.create(
            organization=organization,
            data={HARMONIC_STATUS_KEY: "COMPLETE", HARMONIC_URN_KEY: "urn:harmonic:enrichment:A"},
        )

        candidates = self._select()

        assert len(candidates) == 1
        assert candidates[0]["enrichment_urn"] == "urn:harmonic:enrichment:B"
        assert candidates[0]["previous_status"] is None

    def test_includes_an_org_with_a_pending_or_stalled_stored_status(self):
        for status in ("QUEUED", "IN_PROGRESS", "STALLED"):
            organization = Organization.objects.create(name=f"{status.lower()}.example")
            _fetch(organization, urn=f"urn:harmonic:enrichment:{status}", days_ago=2)
            OrganizationEnrichment.objects.create(organization=organization, data={HARMONIC_STATUS_KEY: status})

        assert len(self._select()) == 3

    def test_a_later_null_urn_fetch_does_not_shadow_the_earlier_open_urn(self):
        # Same gotcha _latest_archived_urn documents: a recheck that lands on an already-matched
        # company archives a null URN, and a naive "latest row" read would shadow the earlier,
        # still-open tracking URN with it.
        organization = Organization.objects.create(name="shadow.example")
        _fetch(organization, urn="urn:harmonic:enrichment:first", days_ago=5)
        _fetch(organization, urn=None, days_ago=1, is_recheck=True)

        candidates = self._select()

        assert len(candidates) == 1
        assert candidates[0]["enrichment_urn"] == "urn:harmonic:enrichment:first"

    def test_caps_selection_never_polled_first_then_oldest_checked(self):
        fresh = Organization.objects.create(name="fresh.example")
        _fetch(fresh, urn="urn:harmonic:enrichment:fresh", days_ago=1)

        old_check = Organization.objects.create(name="old-check.example")
        _fetch(old_check, urn="urn:harmonic:enrichment:old-check", days_ago=2)
        OrganizationEnrichment.objects.create(
            organization=old_check,
            data={
                HARMONIC_STATUS_KEY: "QUEUED",
                HARMONIC_URN_KEY: "urn:harmonic:enrichment:old-check",
                HARMONIC_STATUS_AT_KEY: (_now() - dt.timedelta(days=5)).isoformat(),
            },
        )

        recent_check = Organization.objects.create(name="recent-check.example")
        _fetch(recent_check, urn="urn:harmonic:enrichment:recent-check", days_ago=2)
        OrganizationEnrichment.objects.create(
            organization=recent_check,
            data={
                HARMONIC_STATUS_KEY: "QUEUED",
                HARMONIC_URN_KEY: "urn:harmonic:enrichment:recent-check",
                HARMONIC_STATUS_AT_KEY: (_now() - dt.timedelta(hours=1)).isoformat(),
            },
        )

        with patch(f"{_MODULE}.MAX_CANDIDATES_PER_RUN", 2):
            result = self._select_result()

        assert result["eligible"] == 3
        assert [c["organization_id"] for c in result["candidates"]] == [str(fresh.id), str(old_check.id)]

    def test_kill_switch_stops_selection(self):
        organization = Organization.objects.create(name="off.example")
        _fetch(organization, urn="urn:harmonic:enrichment:off", days_ago=1)

        with override_instance_config("GROWTH_SIGNUP_ENRICHMENT_ENABLED", False):
            assert self._select() == []

    def test_region_gate_stops_selection(self):
        organization = Organization.objects.create(name="region.example")
        _fetch(organization, urn="urn:harmonic:enrichment:region", days_ago=1)

        with override_settings(CLOUD_DEPLOYMENT="DEV"):
            assert self._select() == []


@override_settings(CLOUD_DEPLOYMENT="US")
class TestPollStatusBatchActivity(BaseTest):
    def setUp(self):
        super().setUp()
        self.enterContext(override_instance_config("GROWTH_SIGNUP_ENRICHMENT_ENABLED", True))

    def _candidate(self, organization: Organization, *, urn: str, hours_ago: float = 1.0):
        return {
            "organization_id": str(organization.id),
            "enrichment_urn": urn,
            "urn_fetched_at": (_now() - dt.timedelta(hours=hours_ago)).isoformat(),
            "previous_status": None,
        }

    def _run(self, candidates, statuses: dict[str, str]):
        pha_client = MagicMock()
        provider = MagicMock()

        async def _statuses_for(urns):
            return statuses

        provider.enrichment_statuses_for = _statuses_for
        with (
            patch(f"{_MODULE}.get_regional_ph_client", return_value=pha_client),
            patch("products.growth.backend.enrichment.providers.HarmonicEnrichmentProvider", return_value=provider),
        ):
            result = async_to_sync(poll_status_batch_activity)(candidates)
        return result, pha_client

    def test_stamps_the_record_and_projects_the_group_properties(self):
        organization = Organization.objects.create(name="stamp.example")
        candidate = self._candidate(organization, urn="urn:harmonic:enrichment:stamp")

        result, pha_client = self._run([candidate], {"urn:harmonic:enrichment:stamp": "COMPLETE"})

        assert result == {"polled": 1, "unobserved": 0, "changed": 1, "stalled": 0}
        record = OrganizationEnrichment.objects.get(organization=organization)
        assert record.data[HARMONIC_STATUS_KEY] == "COMPLETE"
        assert record.data[HARMONIC_URN_KEY] == "urn:harmonic:enrichment:stamp"
        assert record.data[HARMONIC_STATUS_AT_KEY]
        pha_client.group_identify.assert_called_once()
        group_call = pha_client.group_identify.call_args
        assert group_call.args == ("organization", str(organization.id))
        assert group_call.kwargs["properties"][HARMONIC_STATUS_KEY] == "COMPLETE"

    def test_emits_a_transition_event_only_when_the_stored_status_actually_changes(self):
        organization = Organization.objects.create(name="unchanged.example")
        OrganizationEnrichment.objects.create(organization=organization, data={HARMONIC_STATUS_KEY: "QUEUED"})
        candidate = self._candidate(organization, urn="urn:harmonic:enrichment:same")

        result, pha_client = self._run([candidate], {"urn:harmonic:enrichment:same": "QUEUED"})

        assert result == {"polled": 1, "unobserved": 0, "changed": 0, "stalled": 0}
        pha_client.capture.assert_not_called()

    def test_a_retried_batch_that_repeats_a_write_emits_no_event(self):
        # The retry replays the same batch after a partial failure; selection-time
        # previous_status ("QUEUED") is stale by the time this write lands, because the first
        # attempt already wrote IN_PROGRESS. Only the record's actual stored status must gate
        # the event.
        organization = Organization.objects.create(name="retried.example")
        OrganizationEnrichment.objects.create(organization=organization, data={HARMONIC_STATUS_KEY: "IN_PROGRESS"})
        candidate = self._candidate(organization, urn="urn:harmonic:enrichment:retried")
        candidate["previous_status"] = "QUEUED"

        result, pha_client = self._run([candidate], {"urn:harmonic:enrichment:retried": "IN_PROGRESS"})

        assert result == {"polled": 1, "unobserved": 0, "changed": 0, "stalled": 0}
        pha_client.capture.assert_not_called()

    def test_transition_event_carries_previous_status_and_hours_since_urn_issued(self):
        organization = Organization.objects.create(name="transition.example")
        OrganizationEnrichment.objects.create(organization=organization, data={HARMONIC_STATUS_KEY: "QUEUED"})
        candidate = self._candidate(organization, urn="urn:harmonic:enrichment:transition", hours_ago=6)

        _, pha_client = self._run([candidate], {"urn:harmonic:enrichment:transition": "COMPLETE"})

        pha_client.capture.assert_called_once()
        call = pha_client.capture.call_args
        assert call.kwargs["event"] == "harmonic_enrichment_status_changed"
        assert call.kwargs["distinct_id"] == str(organization.id)
        assert call.kwargs["groups"] == {"organization": str(organization.id)}
        properties = call.kwargs["properties"]
        assert properties["previous_status"] == "QUEUED"
        assert properties["status"] == "COMPLETE"
        assert properties["hours_since_urn_issued"] == 6

    def test_stalled_status_is_stamped_once_the_urn_is_14_days_old_and_still_pending(self):
        organization = Organization.objects.create(name="stalled.example")
        OrganizationEnrichment.objects.create(organization=organization, data={HARMONIC_STATUS_KEY: "IN_PROGRESS"})
        candidate = self._candidate(organization, urn="urn:harmonic:enrichment:stalled", hours_ago=STALL_AGE_HOURS)

        result, _ = self._run([candidate], {"urn:harmonic:enrichment:stalled": "IN_PROGRESS"})

        assert result == {"polled": 1, "unobserved": 0, "changed": 1, "stalled": 1}
        record = OrganizationEnrichment.objects.get(organization=organization)
        assert record.data[HARMONIC_STATUS_KEY] == "STALLED"

    def test_a_stalled_org_that_completes_late_records_the_transition(self):
        organization = Organization.objects.create(name="latecomplete.example")
        OrganizationEnrichment.objects.create(organization=organization, data={HARMONIC_STATUS_KEY: "STALLED"})
        candidate = self._candidate(
            organization, urn="urn:harmonic:enrichment:late", hours_ago=STALL_AGE_HOURS + 24 * 5
        )

        result, _ = self._run([candidate], {"urn:harmonic:enrichment:late": "COMPLETE"})

        assert result == {"polled": 1, "unobserved": 0, "changed": 1, "stalled": 0}
        record = OrganizationEnrichment.objects.get(organization=organization)
        assert record.data[HARMONIC_STATUS_KEY] == "COMPLETE"

    def test_a_stalled_org_still_pending_stays_stalled_without_a_transition(self):
        organization = Organization.objects.create(name="stillstalled.example")
        OrganizationEnrichment.objects.create(organization=organization, data={HARMONIC_STATUS_KEY: "STALLED"})
        candidate = self._candidate(organization, urn="urn:harmonic:enrichment:still", hours_ago=STALL_AGE_HOURS + 24)

        result, _ = self._run([candidate], {"urn:harmonic:enrichment:still": "IN_PROGRESS"})

        assert result == {"polled": 1, "unobserved": 0, "changed": 0, "stalled": 1}
        record = OrganizationEnrichment.objects.get(organization=organization)
        assert record.data[HARMONIC_STATUS_KEY] == "STALLED"

    def test_a_urn_still_under_the_stall_age_stays_pending(self):
        organization = Organization.objects.create(name="notyetstalled.example")
        OrganizationEnrichment.objects.create(organization=organization, data={HARMONIC_STATUS_KEY: "IN_PROGRESS"})
        candidate = self._candidate(organization, urn="urn:harmonic:enrichment:notyet", hours_ago=STALL_AGE_HOURS - 1)

        result, _ = self._run([candidate], {"urn:harmonic:enrichment:notyet": "IN_PROGRESS"})

        assert result == {"polled": 1, "unobserved": 0, "changed": 0, "stalled": 0}
        record = OrganizationEnrichment.objects.get(organization=organization)
        assert record.data[HARMONIC_STATUS_KEY] == "IN_PROGRESS"

    def test_leaves_the_stamp_untouched_for_a_urn_missing_from_the_response(self):
        organization = Organization.objects.create(name="missing.example")
        candidate = self._candidate(organization, urn="urn:harmonic:enrichment:missing")

        result, _ = self._run([candidate], {})

        assert result == {"polled": 0, "unobserved": 1, "changed": 0, "stalled": 0}
        assert not OrganizationEnrichment.objects.filter(organization=organization).exists()

    def test_a_batch_failure_captures_the_exception_writes_nothing_and_reraises(self):
        organization = Organization.objects.create(name="boom.example")
        candidate = self._candidate(organization, urn="urn:harmonic:enrichment:boom")
        pha_client = MagicMock()
        provider = MagicMock()

        async def _raise(urns):
            raise RuntimeError("harmonic is down")

        provider.enrichment_statuses_for = _raise
        with (
            patch(f"{_MODULE}.get_regional_ph_client", return_value=pha_client),
            patch("products.growth.backend.enrichment.providers.HarmonicEnrichmentProvider", return_value=provider),
            patch(f"{_MODULE}.capture_exception") as mock_capture,
        ):
            with self.assertRaises(RuntimeError):
                async_to_sync(poll_status_batch_activity)([candidate])

        mock_capture.assert_called_once()
        assert not OrganizationEnrichment.objects.filter(organization=organization).exists()
        pha_client.shutdown.assert_called_once()

    def test_kill_switch_skips_the_batch_without_calling_the_provider(self):
        organization = Organization.objects.create(name="killed.example")
        candidate = self._candidate(organization, urn="urn:harmonic:enrichment:killed")

        with override_instance_config("GROWTH_SIGNUP_ENRICHMENT_ENABLED", False):
            with patch("products.growth.backend.enrichment.providers.HarmonicEnrichmentProvider") as provider_cls:
                result = async_to_sync(poll_status_batch_activity)([candidate])

        assert result == {"polled": 0, "unobserved": 0, "changed": 0, "stalled": 0}
        provider_cls.assert_not_called()
        assert not OrganizationEnrichment.objects.filter(organization=organization).exists()


class TestReportStatusPollRunActivity(BaseTest):
    def test_emits_one_event_with_the_counts(self):
        capture = MagicMock()
        scoped_capture = MagicMock()
        scoped_capture.__enter__.return_value = capture
        with (
            patch(f"{_MODULE}.get_instance_region", return_value="EU"),
            patch(f"{_MODULE}.ph_scoped_capture", return_value=scoped_capture) as scoped_capture_factory,
        ):
            report_status_poll_run_activity(
                HarmonicStatusPollRunSummary(
                    eligible=8, selected=5, polled=5, unobserved=0, changed=2, stalled=1, errors=0
                )
            )

        scoped_capture_factory.assert_called_once_with(region="EU")
        event = capture.call_args.kwargs
        assert event["event"] == "harmonic_enrichment_status_poll_completed"
        assert event["properties"] == {
            "eligible": 8,
            "selected": 5,
            "polled": 5,
            "unobserved": 0,
            "changed": 2,
            "stalled": 1,
            "errors": 0,
        }
        scoped_capture.__exit__.assert_called_once()

    def test_skips_outside_a_cloud_region(self):
        with (
            patch(f"{_MODULE}.get_instance_region", return_value=None),
            patch(f"{_MODULE}.ph_scoped_capture") as scoped_capture_factory,
        ):
            report_status_poll_run_activity(
                HarmonicStatusPollRunSummary(
                    eligible=0, selected=0, polled=0, unobserved=0, changed=0, stalled=0, errors=0
                )
            )

        scoped_capture_factory.assert_not_called()
