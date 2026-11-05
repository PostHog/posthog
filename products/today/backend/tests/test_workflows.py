import uuid
import asyncio
from collections.abc import AsyncIterator
from threading import Event
from typing import cast

import pytest
from unittest.mock import patch

from django.conf import settings
from django.utils import timezone

import pytest_asyncio
from temporalio import activity
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.models import Team, User
from posthog.sync import database_sync_to_async

from products.today.backend.facade.contracts import HighlightContext, HighlightFindings, HighlightSource, PulseSlot
from products.today.backend.logic import highlights
from products.today.backend.logic.highlight_types import Context
from products.today.backend.models import TodayHighlights
from products.today.backend.temporal.activities import finalize_highlights_activity, run_highlight_source_activity
from products.today.backend.temporal.inputs import (
    HIGHLIGHTS_WORKFLOW_NAME,
    ComputeHighlightsInputs,
    FinalizeHighlightsInputs,
    HighlightSourceInputs,
    HighlightSourceResult,
    PinnedNumber,
    ResolvePinsInputs,
    ResolvePinsResult,
)
from products.today.backend.temporal.workflows import ComputeTodayHighlightsWorkflow
from products.today.backend.tests.test_highlights import HIGHLIGHTS, metric


@pytest_asyncio.fixture(scope="module")
async def environment() -> AsyncIterator[WorkflowEnvironment]:
    async with await WorkflowEnvironment.start_time_skipping() as env:
        yield env


PINS = [PinnedNumber("insight:a"), PinnedNumber("insight:b", dashboard_id=7)]


@pytest.mark.asyncio
@pytest.mark.parametrize("progressive", [False, True])
@pytest.mark.parametrize(
    "pins,pins_fail,asked,pinned",
    [
        ([], False, [], "[]"),
        (PINS, False, [["insight:a", "insight:b"]], "found"),
        (PINS, True, [["insight:a", "insight:b"]], "[]"),
    ],
)
async def test_sources_and_pins_are_resolved_once_and_finalized_together(
    environment: WorkflowEnvironment,
    progressive: bool,
    pins: list[PinnedNumber],
    pins_fail: bool,
    asked: list[list[str]],
    pinned: str,
) -> None:
    finalized: list[FinalizeHighlightsInputs] = []
    resolved: list[list[str]] = []

    @activity.defn(name="run_highlight_source_activity")
    async def run_source(inputs: HighlightSourceInputs) -> HighlightSourceResult:
        assert inputs.highlights_id == ("h-1" if progressive else None)
        if inputs.source_name == "broken":
            raise ApplicationError("The source query failed.")
        return HighlightSourceResult(source_name=inputs.source_name, found="{}", failed=False)

    @activity.defn(name="resolve_pins_activity")
    async def resolve_pins(inputs: ResolvePinsInputs) -> ResolvePinsResult:
        resolved.append([pin.key for pin in inputs.pins])
        if pins_fail:
            raise ApplicationError("The pinned query failed.")
        return ResolvePinsResult(found="found")

    @activity.defn(name="finalize_highlights_activity")
    async def finalize(inputs: FinalizeHighlightsInputs) -> None:
        finalized.append(inputs)

    async with Worker(
        environment.client,
        task_queue=settings.GENERAL_PURPOSE_TASK_QUEUE,
        workflows=[ComputeTodayHighlightsWorkflow],
        activities=[run_source, resolve_pins, finalize],
        workflow_runner=UnsandboxedWorkflowRunner(),
    ):
        await environment.client.execute_workflow(
            HIGHLIGHTS_WORKFLOW_NAME,
            ComputeHighlightsInputs(
                team_id=1,
                user_id=2,
                highlights_id="h-1",
                local_day="2026-10-13",
                scopes=None,
                source_names=["alerts", "broken"],
                pins=pins,
                progressive=progressive,
            ),
            id=str(uuid.uuid4()),
            task_queue=settings.GENERAL_PURPOSE_TASK_QUEUE,
        )

    assert (resolved, [(inputs.results, inputs.pins, inputs.pinned, inputs.pins_failed) for inputs in finalized]) == (
        asked,
        [
            (
                [
                    HighlightSourceResult(source_name="alerts", found="{}", failed=False),
                    HighlightSourceResult(source_name="broken", found=None, failed=True),
                ],
                pins,
                pinned,
                pins_fail,
            )
        ],
    )


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_real_activity_publishes_before_the_workflow_finishes(
    environment: WorkflowEnvironment, team: Team, user: User
) -> None:
    published = Event()
    finish = Event()
    day = timezone.now().astimezone(team.timezone_info).date()

    def create_row() -> TodayHighlights:
        return TodayHighlights.objects.for_team(team.id).create(
            team_id=team.id, user_id=user.id, local_day=day, key="progress-test"
        )

    row = await database_sync_to_async(create_row)()

    def find(context: HighlightContext) -> HighlightFindings:
        publisher = cast(Context, context).publish_pulse
        assert publisher is not None
        publisher(
            HighlightFindings(pulse=(metric("fast"),)),
            [PulseSlot(key="fast", name="Fast"), PulseSlot(key="slow", name="Slow")],
        )
        published.set()
        assert finish.wait(15)
        return HighlightFindings(pulse=(metric("fast"), metric("slow")))

    with patch.object(highlights, "load_sources", return_value=(HighlightSource(name="routine", find=find),)):
        async with Worker(
            environment.client,
            task_queue=settings.GENERAL_PURPOSE_TASK_QUEUE,
            workflows=[ComputeTodayHighlightsWorkflow],
            activities=[run_highlight_source_activity, finalize_highlights_activity],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            handle = await environment.client.start_workflow(
                HIGHLIGHTS_WORKFLOW_NAME,
                ComputeHighlightsInputs(
                    team_id=team.id,
                    user_id=user.id,
                    highlights_id=str(row.id),
                    local_day=day.isoformat(),
                    scopes=None,
                    source_names=["routine"],
                    progressive=True,
                ),
                id=str(uuid.uuid4()),
                task_queue=settings.GENERAL_PURPOSE_TASK_QUEUE,
            )
            try:
                assert await asyncio.to_thread(published.wait, 15)
                await database_sync_to_async(row.refresh_from_db)()
                content = HIGHLIGHTS.validate_python(row.content)
                assert row.status == "computing"
                assert [m.key for m in content.pulse] == ["fast"]
                assert [slot.status for slot in content.pulse_slots or []] == ["ready", "pending"]
            finally:
                finish.set()
            await handle.result()
    await database_sync_to_async(row.refresh_from_db)()
    assert row.status == "ready"
    assert [m.key for m in HIGHLIGHTS.validate_python(row.content).pulse] == ["fast", "slow"]
