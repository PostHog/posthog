"""Temporal schedule registration for the weekly autoresearch workflow.

The schedule fires :class:`WeeklyAutoresearchWorkflow` every Sunday at 02:00
UTC (``0 2 * * SUN``) on the ``TASKS_TASK_QUEUE``.

Intentionally **not** auto-registered on worker startup — the weekly run is
expensive (dozens of sandboxes per firing) so we keep registration behind an
explicit management command. Ship by running
``python manage.py register_weekly_autoresearch_schedule`` from a controlled
environment (prod, staging, or a trusted dev session with
``QUERY_PERFORMANCE_AI_ENABLE_SCHEDULE=1`` set).
"""

from __future__ import annotations

import json
from dataclasses import asdict

from django.conf import settings

from temporalio.client import (
    Client,
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleOverlapPolicy,
    SchedulePolicy,
    ScheduleSpec,
)

from posthog.temporal.common.schedule import a_create_schedule, a_schedule_exists, a_update_schedule

from .workflows import WeeklyAutoresearchInput, WeeklyAutoresearchWorkflow

SCHEDULE_ID = "query-performance-autoresearch-weekly"

# Sunday 02:00 UTC — low-traffic window, leaves Monday morning for
# engineers to triage whatever shipped. Temporal accepts standard 5-field
# cron expressions; Sunday is both "0" and "SUN" in most parsers but
# "SUN" is clearer at a glance.
WEEKLY_CRON = "0 2 * * SUN"


async def create_weekly_autoresearch_schedule(client: Client, input_payload: WeeklyAutoresearchInput) -> None:
    """Create or update the weekly autoresearch schedule.

    ``input_payload`` defines which team owns the run (for Slack integration
    lookup), which repo the PR-writing sandbox targets, and candidate
    sampling parameters. Passing this in rather than hardcoding keeps the
    schedule decoupled from environment-specific knobs.
    """
    schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            WeeklyAutoresearchWorkflow.run,
            # PostHogWorkflow's parse_inputs expects a single JSON string
            # argument (see workflows.py), so we serialize here rather than
            # passing the dataclass directly.
            json.dumps(asdict(input_payload)),
            id=SCHEDULE_ID,
            task_queue=settings.TASKS_TASK_QUEUE,
        ),
        spec=ScheduleSpec(cron_expressions=[WEEKLY_CRON]),
        # A weekly job never needs overlap: if last week is still running
        # we want to skip this week rather than pile on sandbox load.
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
    )

    if await a_schedule_exists(client, SCHEDULE_ID):
        await a_update_schedule(client, SCHEDULE_ID, schedule)
    else:
        await a_create_schedule(client, SCHEDULE_ID, schedule, trigger_immediately=False)
