import io
import datetime as dt

from posthog.test.base import BaseTest
from unittest.mock import AsyncMock, MagicMock, patch

from django.core.management import call_command
from django.test import override_settings
from django.utils import timezone

from products.growth.backend.models import OrganizationEnrichmentFetch

_COMMAND_MODULE = "products.growth.backend.management.commands.harmonic_enrichment_status"


def _status_response(entries):
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json = AsyncMock(return_value=entries)
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=resp)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


def _mock_session(entries):
    session = MagicMock()
    session.get = MagicMock(return_value=_status_response(entries))
    session_cm = MagicMock()
    session_cm.__aenter__ = AsyncMock(return_value=session)
    session_cm.__aexit__ = AsyncMock(return_value=False)
    return session_cm, session


@override_settings(HARMONIC_API_KEY="test-key")
class TestHarmonicEnrichmentStatusCommand(BaseTest):
    def _fetch(self, *, payload, days_ago=0):
        row = OrganizationEnrichmentFetch.objects.create(
            organization=self.organization, provider="harmonic", payload=payload
        )
        if days_ago:
            OrganizationEnrichmentFetch.objects.filter(id=row.id).update(
                fetched_at=timezone.now() - dt.timedelta(days=days_ago)
            )
        return row

    def test_selects_urns_dedupes_and_reports_per_status_counts(self):
        # In-window hit with a urn, and a second row (the recheck) sharing the same urn.
        self._fetch(payload={"companyFound": True, "enrichmentUrn": "urn:harmonic:enrichment:aaa"})
        self._fetch(payload={"companyFound": True, "enrichmentUrn": "urn:harmonic:enrichment:aaa"})
        # A miss sentinel carrying a urn is still selected.
        self._fetch(payload={"companyFound": False, "enrichmentUrn": "urn:harmonic:enrichment:bbb"})
        # No urn key at all: skipped.
        self._fetch(payload={"companyFound": True})
        # A hit with no pending refresh archives enrichmentUrn as JSON null (key present): skipped.
        self._fetch(payload={"companyFound": True, "enrichmentUrn": None})
        # A urn, but outside the default 7-day window: skipped.
        self._fetch(payload={"companyFound": True, "enrichmentUrn": "urn:harmonic:enrichment:ccc"}, days_ago=10)

        entries = [
            {
                "entity_urn": "urn:harmonic:enrichment:aaa",
                "status": "COMPLETE",
                "enriched_entity_urn": "urn:harmonic:company:1",
            },
            {"entity_urn": "urn:harmonic:enrichment:bbb", "status": "QUEUED", "enriched_entity_urn": None},
        ]
        session_cm, session = _mock_session(entries)
        out = io.StringIO()
        with patch(f"{_COMMAND_MODULE}.aiohttp.ClientSession", return_value=session_cm):
            call_command("harmonic_enrichment_status", stdout=out)
        output = out.getvalue()

        # One HTTP call, with the shared urn sent once, not once per row.
        session.get.assert_called_once()
        sent_urns = [value for key, value in session.get.call_args.kwargs["params"] if key == "urns"]
        assert sorted(sent_urns) == ["urn:harmonic:enrichment:aaa", "urn:harmonic:enrichment:bbb"]

        assert output.count("urn:harmonic:enrichment:aaa") == 2  # printed once per row, not deduped
        assert "urn:harmonic:enrichment:bbb\tQUEUED" in output
        assert "urn:harmonic:enrichment:ccc" not in output  # outside the window
        assert "COMPLETE: 2" in output
        assert "QUEUED: 1" in output

    def test_no_matching_rows_makes_no_http_call(self):
        self._fetch(payload={"companyFound": True})  # no urn

        out = io.StringIO()
        with patch(f"{_COMMAND_MODULE}.aiohttp.ClientSession") as mock_session_cls:
            call_command("harmonic_enrichment_status", stdout=out)

        mock_session_cls.assert_not_called()

    def test_limit_is_spent_on_matching_rows_not_null_urn_rows(self):
        # More recent row has no pending refresh (JSON-null urn); an older row carries a real
        # urn. A --limit applied before the null-urn exclusion would spend its one slot on the
        # non-matching row and starve the real one.
        self._fetch(payload={"companyFound": True, "enrichmentUrn": None})
        self._fetch(payload={"companyFound": False, "enrichmentUrn": "urn:harmonic:enrichment:zzz"}, days_ago=1)

        entries = [{"entity_urn": "urn:harmonic:enrichment:zzz", "status": "QUEUED", "enriched_entity_urn": None}]
        session_cm, session = _mock_session(entries)
        out = io.StringIO()
        with patch(f"{_COMMAND_MODULE}.aiohttp.ClientSession", return_value=session_cm):
            call_command("harmonic_enrichment_status", "--limit=1", stdout=out)

        session.get.assert_called_once()
        sent_urns = [value for key, value in session.get.call_args.kwargs["params"] if key == "urns"]
        assert sent_urns == ["urn:harmonic:enrichment:zzz"]

    def test_non_list_status_body_raises(self):
        self._fetch(payload={"companyFound": True, "enrichmentUrn": "urn:harmonic:enrichment:aaa"})

        session_cm, _ = _mock_session({"error": "not a list"})
        with patch(f"{_COMMAND_MODULE}.aiohttp.ClientSession", return_value=session_cm):
            with self.assertRaises(ValueError):
                call_command("harmonic_enrichment_status")
