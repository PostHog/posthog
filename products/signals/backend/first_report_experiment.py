from __future__ import annotations

from typing import TYPE_CHECKING

import posthoganalytics

from posthog.dataclasses import frozen
from posthog.event_usage import groups
from posthog.exceptions_capture import capture_exception

from products.signals.backend.agent_runtime import AgentRuntime
from products.signals.backend.models import SignalReport, SignalScoutRun

if TYPE_CHECKING:
    from posthog.models.team.team import Team

FIRST_REPORT_EXPERIMENT = "self-driving-banger-scout"


@frozen
class FirstReportExperiment:
    variant: str
    agent_runtime: AgentRuntime

    def properties(self) -> dict[str, str]:
        return {
            "experiment_key": FIRST_REPORT_EXPERIMENT,
            "experiment_variant": self.variant,
            f"$feature/{FIRST_REPORT_EXPERIMENT}": self.variant,
            "runtime": self.agent_runtime.runtime,
        }


def resolve_first_report_experiment(team: Team) -> FirstReportExperiment | None:
    try:
        variant = posthoganalytics.get_feature_flag(
            FIRST_REPORT_EXPERIMENT,
            str(team.uuid),
            groups={"project": str(team.uuid)},
            group_properties={"project": {"id": team.id, "uuid": str(team.uuid)}},
            send_feature_flag_events=False,
        )
    except Exception as error:
        capture_exception(error)
        return None
    if variant == "control":
        return FirstReportExperiment(
            variant=variant,
            agent_runtime=AgentRuntime(
                runtime_adapter="codex", model="gpt-6.1-sol", reasoning_effort="high", service_tier="priority"
            ),
        )
    if variant == "deepseek-fast":
        return FirstReportExperiment(
            variant=variant,
            agent_runtime=AgentRuntime(runtime="pi", model="deepseek-ai/deepseek-v4.1-flash-1017-fast"),
        )
    return None


def capture_first_report_exposure(team: Team, experiment: FirstReportExperiment, run_id: str) -> None:
    try:
        posthoganalytics.capture(
            distinct_id=str(team.uuid),
            event="$experiment_exposure",
            groups=groups(team.organization, team),
            properties={
                **experiment.properties(),
                "$feature_flag": FIRST_REPORT_EXPERIMENT,
                "$feature_flag_response": experiment.variant,
                "run_id": run_id,
            },
        )
    except Exception as error:
        capture_exception(error)


def _first_report_outcome_properties(team_id: int, run_id: str) -> dict[str, str | float | bool | None]:
    run = SignalScoutRun.objects.for_team(team_id).select_related("task_run").filter(id=run_id).first()
    if run is None:
        return {
            "first_report_outcome": "incomplete",
            "report_delivered": False,
            "report_delivered_within_five_minutes": False,
        }
    report = (
        SignalReport.objects.filter(
            team_id=team_id,
            id__in=run.emitted_report_ids or [],
            first_visible_at__isnull=False,
        )
        .order_by("first_visible_at")
        .first()
    )
    result = (run.metadata or {}).get("first_report_result", {})
    outcome = result.get("outcome", "incomplete")
    if report is None:
        return {
            "first_report_outcome": "incomplete" if outcome == "report_created" else outcome,
            "report_delivered": False,
            "report_delivered_within_five_minutes": False,
        }
    assert report.first_visible_at is not None
    latency = (report.first_visible_at - run.task_run.created_at).total_seconds()
    return {
        "first_report_outcome": "report_created",
        "report_delivered": True,
        "report_id": str(report.id),
        "first_report_latency_seconds": latency,
        "report_delivered_within_five_minutes": 0 <= latency <= 300,
    }


def first_report_outcome_properties(team_id: int, run_id: str) -> dict[str, str | float | bool | None]:
    try:
        return _first_report_outcome_properties(team_id, run_id)
    except Exception as error:
        capture_exception(error)
        return {"first_report_measurement_failed": True}
