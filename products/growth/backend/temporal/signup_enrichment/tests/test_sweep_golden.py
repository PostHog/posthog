import os
import json
import uuid
import datetime as dt
import dataclasses
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest
import time_machine
from unittest.mock import MagicMock, call, patch

from django.test import override_settings

from asgiref.sync import sync_to_async
from temporalio.client import WorkflowHistory
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Replayer, UnsandboxedWorkflowRunner, Worker

from posthog.models.instance_setting import get_instance_setting, set_instance_setting
from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.user import User

from products.growth.backend.enrichment.bridge import OrganizationBridgeInputs
from products.growth.backend.enrichment.fields import EnrichmentFields
from products.growth.backend.enrichment.icp_lists import clear_lists_cache
from products.growth.backend.enrichment.providers import EnrichmentProvider, ProviderLookup
from products.growth.backend.enrichment.writer import HARMONIC_STATUS_AT_KEY, HARMONIC_STATUS_KEY, HARMONIC_URN_KEY
from products.growth.backend.models import IcpScoringConfig, OrganizationEnrichment, OrganizationEnrichmentFetch
from products.growth.backend.temporal.signup_enrichment import ACTIVITIES, WORKFLOWS, harmonic_status_poll, sweep
from products.growth.backend.temporal.signup_enrichment.harmonic_status_poll import (
    HarmonicEnrichmentStatusPollWorkflow,
    HarmonicStatusPollInputs,
    poll_status_batch_activity,
    report_status_poll_run_activity,
    select_status_poll_candidates_activity,
)
from products.growth.backend.temporal.signup_enrichment.reenrichment import (
    ICP_REENRICHMENT_ATTEMPT_COUNT_KEY,
    ICP_REENRICHMENT_LAST_ATTEMPTED_AT_KEY,
    IcpReenrichmentSweepInputs,
    IcpReenrichmentSweepWorkflow,
    reenrich_organization_activity,
    report_sweep_run_activity,
    select_reenrichment_candidates_activity,
)
from products.growth.backend.temporal.signup_enrichment.sweep import (
    EnrichmentSweepWorkflow,
    sweep_process_batch_activity,
    sweep_report_run_activity,
    sweep_select_activity,
)
from products.growth.backend.temporal.signup_enrichment.sweep_types import SweepInputs, SweepKind

_REENRICHMENT_MODULE = "products.growth.backend.temporal.signup_enrichment.reenrichment"
_POLL_MODULE = "products.growth.backend.temporal.signup_enrichment.harmonic_status_poll"
_SWEEP_MODULE = "products.growth.backend.temporal.signup_enrichment.sweep"
_PROVIDER_CLASS = "products.growth.backend.enrichment.providers.HarmonicEnrichmentProvider"

SWEEP_ACTIVITIES = [sweep_select_activity, sweep_process_batch_activity, sweep_report_run_activity]
FIXTURES = Path(__file__).parent / "fixtures"
REENRICHMENT_HISTORY = "growth_enrichment_sweep_icp_reenrichment_history.json"
STATUS_POLL_HISTORY = "growth_enrichment_sweep_harmonic_status_poll_history.json"
# Set to regenerate the committed histories the Replayer test runs against:
#   GROWTH_SWEEP_WRITE_HISTORY_FIXTURES=1 hogli test .../test_sweep_golden.py
WRITE_HISTORY_FIXTURES = "GROWTH_SWEEP_WRITE_HISTORY_FIXTURES"

# The clock is frozen (tick=False) for seeding and for the whole workflow run, so every stamp
# below is an exact literal. time_machine leaves time.monotonic alone, which is what asyncio and
# the Temporal test server schedule on, so freezing does not stall them.
FROZEN_AT = dt.datetime(2026, 9, 14, 7, 40, tzinfo=dt.UTC)
FROZEN_ISO = "2026-09-14T07:40:00+00:00"

MATCHED_ORG = "00000000-0000-4000-8000-00000000000a"
UNMATCHED_ORG = "00000000-0000-4000-8000-00000000000b"
FAILING_ORG = "00000000-0000-4000-8000-00000000000c"

CHANGED_ORG = "00000000-0000-4000-8000-000000000001"
UNCHANGED_ORG = "00000000-0000-4000-8000-000000000002"
STALLED_ORG = "00000000-0000-4000-8000-000000000003"
MISSING_ORG = "00000000-0000-4000-8000-000000000004"
BOOM_ORG_1 = "00000000-0000-4000-8000-000000000005"
BOOM_ORG_2 = "00000000-0000-4000-8000-000000000006"

MATCHED_COMPANY: dict[str, Any] = {
    "companyType": "STARTUP",
    "headcount": 12,
    "description": "AI developer platform",
    "funding": {"fundingTotal": 12_000_000, "investors": [{"name": "Y Combinator"}]},
    "tagsV2": [
        {"displayValue": "Artificial Intelligence", "type": "MARKET"},
        {"displayValue": "S25", "type": "YC_BATCH"},
    ],
    "tractionMetrics": {
        "webTraffic": {
            "latestMetricValue": 120_000,
            "metrics": [
                {"timestamp": "2026-08-01T00:00:00Z", "metricValue": 120_000},
                {"timestamp": "2026-04-01T00:00:00Z", "metricValue": 70_000},
            ],
        },
        "headcount": {
            "latestMetricValue": 12,
            "metrics": [
                {"timestamp": "2026-08-01T00:00:00Z", "metricValue": 12},
                {"timestamp": "2026-01-01T00:00:00Z", "metricValue": 8},
            ],
        },
        "headcountEngineering": {"latestMetricValue": 8, "metrics": []},
    },
}

MATCHED_FIELDS = EnrichmentFields(company_type="STARTUP", headcount=12, founded_year=2020, ownership_status="PRIVATE")


class _FakeHarmonic(EnrichmentProvider):
    name = "harmonic"

    def __init__(
        self,
        *,
        lookups: dict[str, ProviderLookup | Exception] | None = None,
        statuses: dict[str, str] | None = None,
        raise_for_urns: frozenset[str] = frozenset(),
    ) -> None:
        self._lookups = lookups or {}
        self._statuses = statuses or {}
        self._raise_for_urns = raise_for_urns

    async def enrich_by_domain(self, domain: str) -> ProviderLookup:
        lookup = self._lookups[domain]
        if isinstance(lookup, Exception):
            raise lookup
        return lookup

    async def enrichment_statuses_for(self, urns: list[str]) -> dict[str, str]:
        if self._raise_for_urns & set(urns):
            raise RuntimeError("harmonic is down")
        return {urn: self._statuses[urn] for urn in urns if urn in self._statuses}


def _org_with_member(organization_id: str, *, email: str, distinct_id: str) -> Organization:
    organization = Organization.objects.create(id=uuid.UUID(organization_id), name=email)
    user = User.objects.create_user(email=email, password=None, first_name="sweep", distinct_id=distinct_id)
    OrganizationMembership.objects.create(organization=organization, user=user)
    return organization


def _fetch(organization: Organization, *, payload: dict[str, Any], days_ago: int, is_recheck: bool = False) -> None:
    row = OrganizationEnrichmentFetch.objects.create(
        organization=organization, provider="harmonic", is_recheck=is_recheck, payload=payload
    )
    OrganizationEnrichmentFetch.objects.filter(id=row.id).update(fetched_at=FROZEN_AT - dt.timedelta(days=days_ago))


def _ago(**kwargs: int) -> str:
    return (FROZEN_AT - dt.timedelta(**kwargs)).isoformat()


def seed_reenrichment() -> None:
    matched = _org_with_member(MATCHED_ORG, email="founder@matched.example", distinct_id="signer-a")
    OrganizationEnrichment.objects.create(
        organization=matched,
        data={"icp_fit_status": "insufficient_data", "work_email": True, "signup_role": "engineering"},
    )
    _fetch(matched, payload={"companyFound": False, "enrichmentUrn": "urn:harmonic:enrichment:a-1"}, days_ago=40)

    unmatched = _org_with_member(UNMATCHED_ORG, email="founder@unmatched.example", distinct_id="signer-b")
    OrganizationEnrichment.objects.create(
        organization=unmatched,
        data={
            "icp_fit_status": "not_found",
            "work_email": True,
            ICP_REENRICHMENT_LAST_ATTEMPTED_AT_KEY: _ago(days=45),
            ICP_REENRICHMENT_ATTEMPT_COUNT_KEY: 1,
        },
    )
    _fetch(unmatched, payload={"companyFound": False, "enrichmentUrn": "urn:harmonic:enrichment:b-1"}, days_ago=60)

    failing = _org_with_member(FAILING_ORG, email="founder@failing.example", distinct_id="signer-c")
    OrganizationEnrichment.objects.create(
        organization=failing,
        data={
            "icp_fit_status": "insufficient_data",
            "work_email": True,
            "signup_role": "founder",
            ICP_REENRICHMENT_LAST_ATTEMPTED_AT_KEY: _ago(days=31),
            ICP_REENRICHMENT_ATTEMPT_COUNT_KEY: 2,
        },
    )
    _fetch(failing, payload={"companyFound": False, "enrichmentUrn": "urn:harmonic:enrichment:c-1"}, days_ago=70)


def reenrichment_provider() -> _FakeHarmonic:
    return _FakeHarmonic(
        lookups={
            "matched.example": ProviderLookup(
                fields=MATCHED_FIELDS, raw_payload=MATCHED_COMPANY, enrichment_urn="urn:harmonic:enrichment:a-2"
            ),
            "unmatched.example": ProviderLookup(
                fields=None, raw_payload=None, enrichment_urn="urn:harmonic:enrichment:b-2"
            ),
            "failing.example": RuntimeError("harmonic is down"),
        },
        statuses={
            "urn:harmonic:enrichment:a-1": "COMPLETE",
            "urn:harmonic:enrichment:b-1": "IN_PROGRESS",
            "urn:harmonic:enrichment:c-1": "QUEUED",
        },
    )


REENRICHMENT_RUN_EVENT = call(
    distinct_id="icp-reenrichment-sweep",
    event="icp_reenrichment_sweep_completed",
    properties={"selected": 3, "attempted": 3, "matched": 1, "failed": 1},
)
REENRICHMENT_EMPTY_RUN_EVENT = call(
    distinct_id="icp-reenrichment-sweep",
    event="icp_reenrichment_sweep_completed",
    properties={"selected": 0, "attempted": 0, "matched": 0, "failed": 0},
)

MATCHED_FIT_PROJECTION = {"icp_fit_score": 100, "icp_fit_version": "v0.6", "icp_fit_status": "scored"}


def assert_reenrichment_outcome(pha_client: MagicMock, run_capture: MagicMock) -> None:
    assert pha_client.capture.call_args_list == [
        call(
            distinct_id="signer-a",
            event="icp_reenrichment_completed",
            properties={
                "organization_id": MATCHED_ORG,
                "matched": True,
                "icp_fit_status": "scored",
                "harmonic_enrichment_status": "COMPLETE",
                "previous_status": "insufficient_data",
                "attempt_number": 1,
                "days_since_first_fetch": 40,
            },
            groups={"organization": MATCHED_ORG},
        ),
        call(
            distinct_id="signer-b",
            event="icp_reenrichment_completed",
            properties={
                "organization_id": UNMATCHED_ORG,
                "matched": False,
                "icp_fit_status": "not_found",
                "harmonic_enrichment_status": "IN_PROGRESS",
                "previous_status": "not_found",
                "attempt_number": 2,
                "days_since_first_fetch": 60,
            },
            groups={"organization": UNMATCHED_ORG},
        ),
    ]
    assert pha_client.group_identify.call_args_list == [
        call(
            "organization",
            MATCHED_ORG,
            properties={
                "enrichment_company_type": "STARTUP",
                "icp_employees": 12,
                "enrichment_founded_year": 2020,
                "enrichment_ownership_status": "PRIVATE",
                "icp_score": 7,
                "icp_score_version": "clay-parity-2",
                **MATCHED_FIT_PROJECTION,
            },
        ),
        call("organization", UNMATCHED_ORG, properties={"icp_fit_status": "not_found"}),
    ]
    assert pha_client.set.call_args_list == [
        call(distinct_id="signer-a", properties={"icp_score": 7, "icp_score_version": "clay-parity-2"}),
        call(distinct_id="signer-a", properties=MATCHED_FIT_PROJECTION),
        call(distinct_id="signer-b", properties={"icp_fit_status": "not_found"}),
    ]
    # One regional client per org attempt: the two that completed plus three attempts for the failing org.
    assert pha_client.shutdown.call_count == 5
    assert run_capture.call_args_list == [REENRICHMENT_RUN_EVENT]

    records = {str(r.organization_id): r.data for r in OrganizationEnrichment.objects.all()}
    assert records == {
        MATCHED_ORG: {
            "icp_fit_status": "scored",
            "work_email": True,
            "signup_role": "engineering",
            ICP_REENRICHMENT_LAST_ATTEMPTED_AT_KEY: FROZEN_ISO,
            ICP_REENRICHMENT_ATTEMPT_COUNT_KEY: 1,
            "company_type": "STARTUP",
            "headcount": 12,
            "founded_year": 2020,
            "ownership_status": "PRIVATE",
            "icp_score": 7,
            "icp_score_version": "clay-parity-2",
            "icp_fit_version": "v0.6",
            "icp_fit_lists_version": "test-lists-1",
            "icp_fit_score": 100,
            "icp_fit_components": {
                "traction": 35,
                "capital": 30,
                "ai_pilled": 15,
                "headcount_growth": 10,
                "software_relevance": 10,
            },
            "icp_fit_flags": {
                "quality_investor": True,
                "data_coverage": 4,
                "low_confidence": False,
                "agency_flag": False,
                "nonprofit_flag": False,
                "wizard_ai_sdk": False,
                "ai_pilled_source": "harmonic",
            },
        },
        UNMATCHED_ORG: {
            "icp_fit_status": "not_found",
            "work_email": True,
            ICP_REENRICHMENT_LAST_ATTEMPTED_AT_KEY: FROZEN_ISO,
            ICP_REENRICHMENT_ATTEMPT_COUNT_KEY: 2,
            "icp_fit_version": "v0.6",
            "icp_fit_lists_version": "test-lists-1",
        },
        FAILING_ORG: {
            "icp_fit_status": "insufficient_data",
            "work_email": True,
            "signup_role": "founder",
            ICP_REENRICHMENT_LAST_ATTEMPTED_AT_KEY: FROZEN_ISO,
            ICP_REENRICHMENT_ATTEMPT_COUNT_KEY: 5,
        },
    }

    fetches = list(
        OrganizationEnrichmentFetch.objects.order_by("organization_id", "fetched_at", "id").values_list(
            "organization_id", "is_recheck", "fetched_at", "payload"
        )
    )
    assert [(str(org), recheck, at.isoformat(), payload) for org, recheck, at, payload in fetches] == [
        (
            MATCHED_ORG,
            False,
            _ago(days=40),
            {"companyFound": False, "enrichmentUrn": "urn:harmonic:enrichment:a-1"},
        ),
        (
            MATCHED_ORG,
            True,
            FROZEN_ISO,
            {**MATCHED_COMPANY, "enrichmentUrn": "urn:harmonic:enrichment:a-2", "enrichmentStatus": "COMPLETE"},
        ),
        (
            UNMATCHED_ORG,
            False,
            _ago(days=60),
            {"companyFound": False, "enrichmentUrn": "urn:harmonic:enrichment:b-1"},
        ),
        (
            UNMATCHED_ORG,
            True,
            FROZEN_ISO,
            {"companyFound": False, "enrichmentUrn": "urn:harmonic:enrichment:b-2", "enrichmentStatus": "IN_PROGRESS"},
        ),
        (
            FAILING_ORG,
            False,
            _ago(days=70),
            {"companyFound": False, "enrichmentUrn": "urn:harmonic:enrichment:c-1"},
        ),
    ]


def _poll_org(organization_id: str, *, urn: str, urn_days_ago: int, status: str, status_hours_ago: int) -> None:
    organization = Organization.objects.create(id=uuid.UUID(organization_id), name=organization_id)
    _fetch(organization, payload={"companyFound": True, "enrichmentUrn": urn}, days_ago=urn_days_ago)
    OrganizationEnrichment.objects.create(
        organization=organization,
        data={HARMONIC_STATUS_KEY: status, HARMONIC_URN_KEY: urn, HARMONIC_STATUS_AT_KEY: _ago(hours=status_hours_ago)},
    )


# Six candidates, oldest-checked first, so batches of two are (changed, unchanged), (stalled,
# missing) and (boom, boom). The last batch's Harmonic call raises on every attempt.
def seed_poll() -> None:
    _poll_org(CHANGED_ORG, urn="urn:harmonic:enrichment:p1", urn_days_ago=2, status="QUEUED", status_hours_ago=6)
    _poll_org(UNCHANGED_ORG, urn="urn:harmonic:enrichment:p2", urn_days_ago=1, status="IN_PROGRESS", status_hours_ago=5)
    _poll_org(STALLED_ORG, urn="urn:harmonic:enrichment:p3", urn_days_ago=15, status="IN_PROGRESS", status_hours_ago=4)
    _poll_org(MISSING_ORG, urn="urn:harmonic:enrichment:p4", urn_days_ago=3, status="QUEUED", status_hours_ago=3)
    _poll_org(BOOM_ORG_1, urn="urn:harmonic:enrichment:p5", urn_days_ago=1, status="QUEUED", status_hours_ago=2)
    _poll_org(BOOM_ORG_2, urn="urn:harmonic:enrichment:p6", urn_days_ago=1, status="QUEUED", status_hours_ago=1)


def poll_provider() -> _FakeHarmonic:
    return _FakeHarmonic(
        statuses={
            "urn:harmonic:enrichment:p1": "COMPLETE",
            "urn:harmonic:enrichment:p2": "IN_PROGRESS",
            "urn:harmonic:enrichment:p3": "IN_PROGRESS",
        },
        raise_for_urns=frozenset({"urn:harmonic:enrichment:p5", "urn:harmonic:enrichment:p6"}),
    )


POLL_RUN_EVENT = call(
    distinct_id="harmonic-status-poller",
    event="harmonic_enrichment_status_poll_completed",
    properties={"eligible": 6, "selected": 6, "polled": 3, "unobserved": 1, "changed": 2, "stalled": 1, "errors": 2},
)
POLL_EMPTY_RUN_EVENT = call(
    distinct_id="harmonic-status-poller",
    event="harmonic_enrichment_status_poll_completed",
    properties={"eligible": 0, "selected": 0, "polled": 0, "unobserved": 0, "changed": 0, "stalled": 0, "errors": 0},
)


def assert_poll_outcome(pha_client: MagicMock, run_capture: MagicMock) -> None:
    assert pha_client.capture.call_args_list == [
        call(
            distinct_id=CHANGED_ORG,
            event="harmonic_enrichment_status_changed",
            properties={
                "organization_id": CHANGED_ORG,
                "previous_status": "QUEUED",
                "status": "COMPLETE",
                "hours_since_urn_issued": 48,
            },
            groups={"organization": CHANGED_ORG},
        ),
        call(
            distinct_id=STALLED_ORG,
            event="harmonic_enrichment_status_changed",
            properties={
                "organization_id": STALLED_ORG,
                "previous_status": "IN_PROGRESS",
                "status": "STALLED",
                "hours_since_urn_issued": 360,
            },
            groups={"organization": STALLED_ORG},
        ),
    ]
    assert pha_client.group_identify.call_args_list == [
        call(
            "organization",
            CHANGED_ORG,
            properties={
                HARMONIC_STATUS_KEY: "COMPLETE",
                HARMONIC_STATUS_AT_KEY: FROZEN_ISO,
                HARMONIC_URN_KEY: "urn:harmonic:enrichment:p1",
            },
        ),
        call(
            "organization",
            UNCHANGED_ORG,
            properties={
                HARMONIC_STATUS_KEY: "IN_PROGRESS",
                HARMONIC_STATUS_AT_KEY: FROZEN_ISO,
                HARMONIC_URN_KEY: "urn:harmonic:enrichment:p2",
            },
        ),
        call(
            "organization",
            STALLED_ORG,
            properties={
                HARMONIC_STATUS_KEY: "STALLED",
                HARMONIC_STATUS_AT_KEY: FROZEN_ISO,
                HARMONIC_URN_KEY: "urn:harmonic:enrichment:p3",
            },
        ),
    ]
    assert pha_client.set.call_args_list == []
    # One regional client per batch attempt: two batches that completed plus three attempts for the raising one.
    assert pha_client.shutdown.call_count == 5
    assert run_capture.call_args_list == [POLL_RUN_EVENT]

    records = {str(r.organization_id): r.data for r in OrganizationEnrichment.objects.all()}
    assert records == {
        CHANGED_ORG: {
            HARMONIC_STATUS_KEY: "COMPLETE",
            HARMONIC_URN_KEY: "urn:harmonic:enrichment:p1",
            HARMONIC_STATUS_AT_KEY: FROZEN_ISO,
        },
        UNCHANGED_ORG: {
            HARMONIC_STATUS_KEY: "IN_PROGRESS",
            HARMONIC_URN_KEY: "urn:harmonic:enrichment:p2",
            HARMONIC_STATUS_AT_KEY: FROZEN_ISO,
        },
        STALLED_ORG: {
            HARMONIC_STATUS_KEY: "STALLED",
            HARMONIC_URN_KEY: "urn:harmonic:enrichment:p3",
            HARMONIC_STATUS_AT_KEY: FROZEN_ISO,
        },
        MISSING_ORG: {
            HARMONIC_STATUS_KEY: "QUEUED",
            HARMONIC_URN_KEY: "urn:harmonic:enrichment:p4",
            HARMONIC_STATUS_AT_KEY: _ago(hours=3),
        },
        BOOM_ORG_1: {
            HARMONIC_STATUS_KEY: "QUEUED",
            HARMONIC_URN_KEY: "urn:harmonic:enrichment:p5",
            HARMONIC_STATUS_AT_KEY: _ago(hours=2),
        },
        BOOM_ORG_2: {
            HARMONIC_STATUS_KEY: "QUEUED",
            HARMONIC_URN_KEY: "urn:harmonic:enrichment:p6",
            HARMONIC_STATUS_AT_KEY: _ago(hours=1),
        },
    }
    assert OrganizationEnrichmentFetch.objects.count() == 6


async def run_workflow(workflow_cls: Any, activities: list, inputs: Any) -> tuple[dict[str, Any], WorkflowHistory]:
    task_queue = f"growth-sweep-golden-{uuid.uuid4()}"
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=[workflow_cls],
            activities=activities,
            activity_executor=ThreadPoolExecutor(max_workers=2),
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            handle = await env.client.start_workflow(
                workflow_cls.run, inputs, id=f"growth-sweep-golden-{uuid.uuid4()}", task_queue=task_queue
            )
            result = await handle.result()
            history = await handle.fetch_history()
    return result, history


def _scoped_capture(run_capture: MagicMock) -> MagicMock:
    scoped = MagicMock()
    scoped.__enter__.return_value = run_capture
    return scoped


def _configure_enrichment(*, enabled: bool) -> None:
    IcpScoringConfig.objects.create(
        version="test-lists-1",
        tags=[
            {"tag": "Artificial Intelligence", "recommendation": "ai_positive"},
            {"tag": "Developer Tools", "recommendation": "software_positive"},
        ],
        quality_investors=[{"investor": "Y Combinator", "aliases": ["YC"]}],
        is_active=True,
    )
    clear_lists_cache()
    set_instance_setting("GROWTH_SIGNUP_ENRICHMENT_ENABLED", enabled)
    set_instance_setting("GROWTH_ICP_REENRICH_DAILY_CAP", 500)


_MACHINE_SPECIFIC_KEYS = {"identity": "growth-sweep-golden", "stackTrace": ""}


def _portable(node: Any) -> Any:
    if isinstance(node, dict):
        return {
            key: _MACHINE_SPECIFIC_KEYS[key] if key in _MACHINE_SPECIFIC_KEYS else _portable(value)
            for key, value in node.items()
        }
    if isinstance(node, list):
        return [_portable(value) for value in node]
    return node


def _record_history(name: str, history: WorkflowHistory) -> None:
    if os.environ.get(WRITE_HISTORY_FIXTURES):
        # Identities carry the recording machine's hostname and stack traces its file paths.
        (FIXTURES / name).write_text(json.dumps(_portable(history.to_json_dict()), indent=2) + "\n")


def _reenrichment_patches(pha_client: MagicMock) -> list[Any]:
    return [
        patch(_PROVIDER_CLASS, return_value=reenrichment_provider()),
        patch(f"{_REENRICHMENT_MODULE}.get_regional_ph_client", return_value=pha_client),
        patch(f"{_REENRICHMENT_MODULE}.capture_exception"),
        patch(
            "products.growth.backend.enrichment.core.read_organization_bridge_inputs",
            return_value=OrganizationBridgeInputs(),
        ),
        patch("products.growth.backend.enrichment.core.get_person_by_distinct_id", return_value=None),
    ]


def _poll_patches(pha_client: MagicMock) -> list[Any]:
    return [
        patch(_PROVIDER_CLASS, return_value=poll_provider()),
        patch(f"{_POLL_MODULE}.get_regional_ph_client", return_value=pha_client),
        patch(f"{_POLL_MODULE}.capture_exception"),
    ]


@pytest.mark.django_db(transaction=True)
class TestSweepGolden:
    @pytest.fixture(autouse=True)
    def _isolation(self):
        clear_lists_cache()
        with override_settings(CLOUD_DEPLOYMENT="US"):
            yield
        clear_lists_cache()
        get_instance_setting.cache_clear()  # type: ignore[attr-defined]

    async def _run(
        self, *, patches: list[Any], seed: Any, enabled: bool, workflow_cls: Any, activities: list, inputs: Any
    ) -> tuple[dict[str, Any], WorkflowHistory]:
        with time_machine.travel(FROZEN_AT, tick=False):
            for p in patches:
                p.start()
            try:
                await sync_to_async(_configure_enrichment)(enabled=enabled)
                await sync_to_async(seed)()
                return await run_workflow(workflow_cls, activities, inputs)
            finally:
                for p in reversed(patches):
                    p.stop()

    async def _run_old_reenrichment(self, *, enabled: bool) -> tuple[dict[str, Any], MagicMock, MagicMock]:
        pha_client = MagicMock()
        run_capture = MagicMock()
        result, _ = await self._run(
            patches=[
                *_reenrichment_patches(pha_client),
                patch(f"{_REENRICHMENT_MODULE}.ph_scoped_capture", return_value=_scoped_capture(run_capture)),
            ],
            seed=seed_reenrichment,
            enabled=enabled,
            workflow_cls=IcpReenrichmentSweepWorkflow,
            activities=[
                select_reenrichment_candidates_activity,
                reenrich_organization_activity,
                report_sweep_run_activity,
            ],
            inputs=IcpReenrichmentSweepInputs(),
        )
        return result, pha_client, run_capture

    async def _run_old_poll(self, *, enabled: bool) -> tuple[dict[str, Any], MagicMock, MagicMock]:
        pha_client = MagicMock()
        run_capture = MagicMock()
        result, _ = await self._run(
            patches=[
                *_poll_patches(pha_client),
                patch(f"{_POLL_MODULE}.POLL_BATCH_SIZE", 2),
                patch(f"{_POLL_MODULE}.ph_scoped_capture", return_value=_scoped_capture(run_capture)),
            ],
            seed=seed_poll,
            enabled=enabled,
            workflow_cls=HarmonicEnrichmentStatusPollWorkflow,
            activities=[
                select_status_poll_candidates_activity,
                poll_status_batch_activity,
                report_status_poll_run_activity,
            ],
            inputs=HarmonicStatusPollInputs(),
        )
        return result, pha_client, run_capture

    async def _run_new_reenrichment(
        self, *, enabled: bool
    ) -> tuple[dict[str, Any], MagicMock, MagicMock, WorkflowHistory]:
        pha_client = MagicMock()
        run_capture = MagicMock()
        result, history = await self._run(
            patches=[
                *_reenrichment_patches(pha_client),
                patch(f"{_SWEEP_MODULE}.ph_scoped_capture", return_value=_scoped_capture(run_capture)),
            ],
            seed=seed_reenrichment,
            enabled=enabled,
            workflow_cls=EnrichmentSweepWorkflow,
            activities=SWEEP_ACTIVITIES,
            inputs=SweepInputs(kind=SweepKind.ICP_REENRICHMENT, cap=None),
        )
        return result, pha_client, run_capture, history

    async def _run_new_poll(self, *, enabled: bool) -> tuple[dict[str, Any], MagicMock, MagicMock, WorkflowHistory]:
        pha_client = MagicMock()
        run_capture = MagicMock()
        # The old body batches from POLL_BATCH_SIZE at run time; the generic one batches from the
        # spec inside the select activity, so the same two-per-batch seed patches the spec instead.
        spec = dataclasses.replace(harmonic_status_poll.SPEC, batch_size=2)
        result, history = await self._run(
            patches=[
                *_poll_patches(pha_client),
                patch(f"{_POLL_MODULE}.SPEC", spec),
                patch.dict(sweep.SWEEPS, {SweepKind.HARMONIC_STATUS_POLL: spec}),
                patch(f"{_SWEEP_MODULE}.ph_scoped_capture", return_value=_scoped_capture(run_capture)),
            ],
            seed=seed_poll,
            enabled=enabled,
            workflow_cls=EnrichmentSweepWorkflow,
            activities=SWEEP_ACTIVITIES,
            inputs=SweepInputs(kind=SweepKind.HARMONIC_STATUS_POLL, cap=None),
        )
        return result, pha_client, run_capture, history

    async def test_reenrichment_sweep_pins_events_records_and_fetches(self):
        result, pha_client, run_capture = await self._run_old_reenrichment(enabled=True)

        assert result == {"selected": 3, "attempted": 3, "matched": 1, "failed": 1}
        await sync_to_async(assert_reenrichment_outcome)(pha_client, run_capture)

    async def test_reenrichment_sweep_with_the_kill_switch_off_reports_zero_counts(self):
        result, pha_client, run_capture = await self._run_old_reenrichment(enabled=False)

        assert result == {"selected": 0, "attempted": 0, "matched": 0, "failed": 0}
        pha_client.capture.assert_not_called()
        assert run_capture.call_args_list == [REENRICHMENT_EMPTY_RUN_EVENT]

    async def test_status_poll_pins_events_records_and_counts_failed_items(self):
        result, pha_client, run_capture = await self._run_old_poll(enabled=True)

        assert result == POLL_RUN_EVENT.kwargs["properties"]
        await sync_to_async(assert_poll_outcome)(pha_client, run_capture)

    async def test_status_poll_with_the_kill_switch_off_reports_zero_counts(self):
        result, pha_client, run_capture = await self._run_old_poll(enabled=False)

        assert result == POLL_EMPTY_RUN_EVENT.kwargs["properties"]
        pha_client.capture.assert_not_called()
        assert run_capture.call_args_list == [POLL_EMPTY_RUN_EVENT]

    async def test_generic_sweep_reproduces_the_pinned_reenrichment_run(self):
        result, pha_client, run_capture, history = await self._run_new_reenrichment(enabled=True)

        assert result == REENRICHMENT_RUN_EVENT.kwargs["properties"]
        await sync_to_async(assert_reenrichment_outcome)(pha_client, run_capture)
        _record_history(REENRICHMENT_HISTORY, history)

    async def test_generic_sweep_reenrichment_with_the_kill_switch_off_reports_zero_counts(self):
        result, pha_client, run_capture, _ = await self._run_new_reenrichment(enabled=False)

        assert result == REENRICHMENT_EMPTY_RUN_EVENT.kwargs["properties"]
        pha_client.capture.assert_not_called()
        assert run_capture.call_args_list == [REENRICHMENT_EMPTY_RUN_EVENT]

    async def test_generic_sweep_reproduces_the_pinned_status_poll_run(self):
        result, pha_client, run_capture, history = await self._run_new_poll(enabled=True)

        assert result == POLL_RUN_EVENT.kwargs["properties"]
        await sync_to_async(assert_poll_outcome)(pha_client, run_capture)
        _record_history(STATUS_POLL_HISTORY, history)

    async def test_generic_sweep_status_poll_with_the_kill_switch_off_reports_zero_counts(self):
        result, pha_client, run_capture, _ = await self._run_new_poll(enabled=False)

        assert result == POLL_EMPTY_RUN_EVENT.kwargs["properties"]
        pha_client.capture.assert_not_called()
        assert run_capture.call_args_list == [POLL_EMPTY_RUN_EVENT]


@pytest.mark.parametrize("fixture", [REENRICHMENT_HISTORY, STATUS_POLL_HISTORY])
async def test_committed_history_replays_against_the_generic_sweep(fixture: str):
    history = WorkflowHistory.from_json("growth-sweep-golden", (FIXTURES / fixture).read_text())
    started = history.events[0].workflow_execution_started_event_attributes
    assert started.workflow_type.name == "growth-enrichment-sweep"

    await Replayer(workflows=[EnrichmentSweepWorkflow], workflow_runner=UnsandboxedWorkflowRunner()).replay_workflow(
        history
    )


async def test_worker_accepts_every_growth_workflow_and_activity():
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=f"growth-registration-{uuid.uuid4()}",
            workflows=WORKFLOWS,
            activities=ACTIVITIES,
            activity_executor=ThreadPoolExecutor(max_workers=1),
            workflow_runner=UnsandboxedWorkflowRunner(),
        ) as worker:
            registered_activities = worker.config()["activities"]

    assert len(registered_activities) == 10
    assert {workflow.get_name() for workflow in WORKFLOWS} >= {
        "growth-enrichment-sweep",
        "icp-reenrichment-sweep",
        "harmonic-enrichment-status-poll",
    }
