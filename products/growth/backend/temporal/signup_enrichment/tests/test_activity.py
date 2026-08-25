import threading
import dataclasses

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from asgiref.sync import sync_to_async
from temporalio.testing import ActivityEnvironment

from posthog.models import Organization

from products.growth.backend.enrichment.core import EnrichmentOutcome
from products.growth.backend.enrichment.fields import EnrichmentFields
from products.growth.backend.enrichment.fit_score import IcpFitResult
from products.growth.backend.enrichment.snapshot import SNAPSHOT_EVENT_NAME
from products.growth.backend.models import EnrichmentSignupSnapshot
from products.growth.backend.temporal.signup_enrichment.workflow import (
    MAX_ENRICH_ATTEMPTS,
    SignupEnrichmentInputs,
    enrich_signup_organization_activity,
)

pytestmark = pytest.mark.asyncio

_MODULE = "products.growth.backend.temporal.signup_enrichment.workflow"
_INPUTS = SignupEnrichmentInputs(organization_id="org-1", distinct_id="d1", domain="stripe.com")


def _patches(*, enrich_return, deterministic=None):
    pha_client = MagicMock()
    return pha_client, (
        patch(f"{_MODULE}.get_regional_ph_client", return_value=pha_client),
        patch(f"{_MODULE}.enrich_organization", AsyncMock(**enrich_return)),
        patch(f"{_MODULE}._deterministic_company_type", return_value=deterministic),
        patch(f"{_MODULE}.capture_signup_enrichment_snapshot"),
    )


async def test_emits_success_signal_and_snapshot_on_match():
    outcome = EnrichmentOutcome(
        provider_fields=EnrichmentFields(company_type="STARTUP", headcount=130, industry="Fintech"),
        fit=IcpFitResult(status="scored", score=77, lists_version="lists-1"),
    )
    pha_client, (get_client, enrich, det, snapshot) = _patches(enrich_return={"return_value": outcome})
    with get_client, enrich, det, snapshot as snapshot_mock:
        result = await ActivityEnvironment().run(enrich_signup_organization_activity, _INPUTS)

    assert result == {"matched": True, "fields_filled": 3}
    # Snapshot captured once, built from the enriched fields plus the at-signup fit evaluation.
    snapshot_mock.assert_called_once()
    snapshot_arg = snapshot_mock.call_args.kwargs["snapshot"]
    assert snapshot_arg.company_type == "STARTUP"
    assert snapshot_arg.icp_fit_score == 77
    assert snapshot_arg.icp_fit_version == "v0.5"
    assert snapshot_arg.icp_fit_status == "scored"
    # Launch signal emitted with success + the filled field keys + the fit status.
    signal = next(c for c in pha_client.capture.call_args_list if c.kwargs["event"] == "signup_enrichment_completed")
    assert signal.kwargs["properties"]["success"] is True
    assert signal.kwargs["properties"]["matched"] is True
    assert signal.kwargs["properties"]["icp_fit_status"] == "scored"


async def test_falls_back_to_deterministic_company_type_on_miss():
    outcome = EnrichmentOutcome(provider_fields=None, fit=IcpFitResult(status="not_found"))
    pha_client, (get_client, enrich, det, snapshot) = _patches(
        enrich_return={"return_value": outcome}, deterministic="yc"
    )
    with get_client, enrich, det, snapshot as snapshot_mock:
        result = await ActivityEnvironment().run(enrich_signup_organization_activity, _INPUTS)

    assert result == {"matched": False, "fields_filled": 0}
    snapshot_arg = snapshot_mock.call_args.kwargs["snapshot"]
    assert snapshot_arg.company_type == "yc"
    # A score-less evaluation snapshots the status alone: no number, no version.
    assert snapshot_arg.icp_fit_score is None
    assert snapshot_arg.icp_fit_version is None
    assert snapshot_arg.icp_fit_status == "not_found"


async def test_skipped_fit_scoring_leaves_the_write_once_snapshot_unclaimed():
    outcome = EnrichmentOutcome(provider_fields=EnrichmentFields(company_type="STARTUP"), fit=None)
    pha_client, (get_client, enrich, det, snapshot) = _patches(enrich_return={"return_value": outcome})
    with get_client, enrich, det, snapshot as snapshot_mock:
        await ActivityEnvironment().run(enrich_signup_organization_activity, _INPUTS)

    snapshot_mock.assert_not_called()
    signal = next(c for c in pha_client.capture.call_args_list if c.kwargs["event"] == "signup_enrichment_completed")
    assert signal.kwargs["properties"]["icp_fit_status"] is None


async def test_connection_cleanup_runs_on_the_orm_thread():
    # Django connections are thread-local and the ORM work runs on asgiref's shared sync-executor
    # thread. Cleanup on any other thread is a no-op, and a dead connection in the executor thread
    # then fails every activity on the worker until the pod is replaced.
    cleanup_threads = []

    pha_client, (get_client, enrich, det, snapshot) = _patches(
        enrich_return={"return_value": EnrichmentOutcome(provider_fields=None, fit=None)}
    )
    with (
        get_client,
        enrich,
        det,
        snapshot,
        patch(
            "posthog.temporal.common.utils._close_initialized_connections",
            side_effect=lambda: cleanup_threads.append(threading.get_ident()),
        ),
        patch("posthog.temporal.common.utils.settings.TEST", False),
    ):
        await ActivityEnvironment().run(enrich_signup_organization_activity, _INPUTS)

    orm_thread = await sync_to_async(threading.get_ident)()
    assert cleanup_threads and all(t == orm_thread for t in cleanup_threads)
    assert orm_thread != threading.get_ident()


@pytest.mark.parametrize("attempt,expect_signal", [(1, False), (MAX_ENRICH_ATTEMPTS, True)])
async def test_failure_signal_emitted_only_on_final_attempt(attempt, expect_signal):
    pha_client, (get_client, enrich, det, snapshot) = _patches(enrich_return={"side_effect": RuntimeError("boom")})
    env = ActivityEnvironment()
    env.info = dataclasses.replace(env.info, attempt=attempt)
    with get_client, enrich, det, snapshot, pytest.raises(RuntimeError):
        await env.run(enrich_signup_organization_activity, _INPUTS)

    signals = [c for c in pha_client.capture.call_args_list if c.kwargs["event"] == "signup_enrichment_completed"]
    if expect_signal:
        assert len(signals) == 1
        assert signals[0].kwargs["properties"]["success"] is False
        assert signals[0].kwargs["properties"]["error"] == "RuntimeError"
    else:
        assert signals == []


@pytest.mark.django_db
class TestWriteOnceSnapshotEligibility:
    """Exercises the real EnrichmentSignupSnapshot row rather than a mocked call site."""

    async def test_skip_leaves_the_org_eligible_for_a_later_capture(self):
        organization = await sync_to_async(Organization.objects.create)(name="Acme")
        inputs = SignupEnrichmentInputs(organization_id=str(organization.id), distinct_id="d1", domain="acme.com")
        fields = EnrichmentFields(company_type="STARTUP")
        pha_client = MagicMock()

        with (
            patch(f"{_MODULE}.get_regional_ph_client", return_value=pha_client),
            patch(
                f"{_MODULE}.enrich_organization",
                AsyncMock(return_value=EnrichmentOutcome(provider_fields=fields, fit=None)),
            ),
            patch(f"{_MODULE}._deterministic_company_type", return_value=None),
        ):
            await ActivityEnvironment().run(enrich_signup_organization_activity, inputs)

        exists = await sync_to_async(EnrichmentSignupSnapshot.objects.filter(organization_id=organization.id).exists)()
        assert exists is False
        assert not any(c.kwargs["event"] == SNAPSHOT_EVENT_NAME for c in pha_client.capture.call_args_list)

        evaluated = EnrichmentOutcome(provider_fields=fields, fit=IcpFitResult(status="insufficient_data"))
        with (
            patch(f"{_MODULE}.get_regional_ph_client", return_value=pha_client),
            patch(f"{_MODULE}.enrich_organization", AsyncMock(return_value=evaluated)),
            patch(f"{_MODULE}._deterministic_company_type", return_value=None),
        ):
            await ActivityEnvironment().run(enrich_signup_organization_activity, inputs)

        exists = await sync_to_async(EnrichmentSignupSnapshot.objects.filter(organization_id=organization.id).exists)()
        assert exists is True
        snapshot_events = [c for c in pha_client.capture.call_args_list if c.kwargs["event"] == SNAPSHOT_EVENT_NAME]
        assert len(snapshot_events) == 1
        assert snapshot_events[0].kwargs["properties"]["icp_fit_status_at_signup"] == "insufficient_data"

    async def test_insufficient_data_evaluation_claims_the_snapshot(self):
        organization = await sync_to_async(Organization.objects.create)(name="Acme")
        inputs = SignupEnrichmentInputs(organization_id=str(organization.id), distinct_id="d1", domain="acme.com")
        outcome = EnrichmentOutcome(provider_fields=None, fit=IcpFitResult(status="insufficient_data"))
        pha_client = MagicMock()

        with (
            patch(f"{_MODULE}.get_regional_ph_client", return_value=pha_client),
            patch(f"{_MODULE}.enrich_organization", AsyncMock(return_value=outcome)),
            patch(f"{_MODULE}._deterministic_company_type", return_value=None),
        ):
            await ActivityEnvironment().run(enrich_signup_organization_activity, inputs)

        exists = await sync_to_async(EnrichmentSignupSnapshot.objects.filter(organization_id=organization.id).exists)()
        assert exists is True
