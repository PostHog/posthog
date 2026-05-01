import random

import pytest
from unittest.mock import patch

import pytest_asyncio
from asgiref.sync import sync_to_async

from posthog.models import Organization, Team
from posthog.sync import database_sync_to_async

from products.signals.backend.models import SignalReport
from products.signals.backend.temporal.summary import (
    MarkReportFailedInput,
    MarkReportInProgressInput,
    MarkReportReadyInput,
    mark_report_failed_activity,
    mark_report_in_progress_activity,
    mark_report_ready_activity,
)

PIPELINE_MODULE_PATH = "products.signals.backend.temporal.summary"


@pytest_asyncio.fixture
async def aorganization():
    organization = await sync_to_async(Organization.objects.create)(
        name=f"SignalsTelemetryOrg-{random.randint(1, 99999)}",
    )
    yield organization
    await sync_to_async(organization.delete)()


@pytest_asyncio.fixture
async def ateam(aorganization):
    team = await sync_to_async(Team.objects.create)(
        organization=aorganization,
        name=f"SignalsTelemetryTeam-{random.randint(1, 99999)}",
    )
    yield team
    await sync_to_async(team.delete)()


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_started_and_ready_fire_expected_captures(ateam):
    report = await database_sync_to_async(SignalReport.objects.create)(
        team=ateam,
        status=SignalReport.Status.CANDIDATE,
        signal_count=2,
        total_weight=1.2,
    )
    report_id = str(report.id)
    source_products = ["conversations", "zendesk"]

    with patch(f"{PIPELINE_MODULE_PATH}.posthoganalytics.capture") as capture:
        await mark_report_in_progress_activity(
            MarkReportInProgressInput(
                team_id=ateam.id,
                report_id=report_id,
                signal_count=2,
                source_products=source_products,
            )
        )
        await mark_report_ready_activity(
            MarkReportReadyInput(
                team_id=ateam.id,
                report_id=report_id,
                title="title",
                summary="summary",
                processed_signal_count=2,
                source_products=source_products,
            )
        )

    events = [call.kwargs for call in capture.call_args_list]
    assert [e["event"] for e in events] == ["signal_report_started", "signal_report_completed"]
    for e in events:
        assert e["distinct_id"] == str(ateam.uuid)
        assert e["properties"]["report_id"] == report_id
        assert e["properties"]["signal_count"] == 2
        assert e["properties"]["source_products"] == source_products
        assert "run_count" in e["properties"]
        assert "project" in e["groups"]
    assert events[0]["properties"].get("result") is None
    assert events[1]["properties"]["result"] == "ready"


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_failed_fires_completed_with_failure_reason(ateam):
    report = await database_sync_to_async(SignalReport.objects.create)(
        team=ateam,
        status=SignalReport.Status.IN_PROGRESS,
        signal_count=3,
        total_weight=2.0,
    )
    report_id = str(report.id)

    with patch(f"{PIPELINE_MODULE_PATH}.posthoganalytics.capture") as capture:
        await mark_report_failed_activity(
            MarkReportFailedInput(
                team_id=ateam.id,
                report_id=report_id,
                error="Failed safety review: contains PII",
                failure_reason="safety_judge_rejected",
                signal_count=3,
                source_products=["zendesk"],
            )
        )

    capture.assert_called_once()
    kwargs = capture.call_args.kwargs
    assert kwargs["event"] == "signal_report_completed"
    assert kwargs["properties"]["result"] == "failed"
    assert kwargs["properties"]["failure_reason"] == "safety_judge_rejected"
    assert kwargs["properties"]["signal_count"] == 3
    assert kwargs["properties"]["source_products"] == ["zendesk"]
