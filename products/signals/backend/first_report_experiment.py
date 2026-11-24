from __future__ import annotations

from typing import TYPE_CHECKING, Any

import posthoganalytics

from posthog.dataclasses import frozen
from posthog.event_usage import groups
from posthog.exceptions_capture import capture_exception
from posthog.ph_client import ph_scoped_capture

from products.signals.backend.agent_runtime import AgentRuntime
from products.signals.backend.models import SignalReport, SignalScoutRun, SignalTeamConfig

if TYPE_CHECKING:
    from posthog.models.team.team import Team

FIRST_REPORT_EXPERIMENT = "self-driving-first-report-model"
FIRST_REPORT_TERRA_VARIANT = "test-terra"
# Values that `self-driving-banger-scout` stored on onboarding state for projects that ran the
# first-report scout. A job still pending from before this experiment reads them.
_LEGACY_FIRST_REPORT_VARIANTS = frozenset({"test-sol", "test-deepseek"})
# Onboarding state key for the variant whose exposure the dispatch captured. It is None for an
# unenrolled project, so the runner checks for the key and not for a value.
DISPATCHED_VARIANT_KEY = "first_report_dispatched_variant"

DEEPSEEK_FIRST_REPORT_RUNTIME = AgentRuntime(runtime="pi", model="deepseek-ai/deepseek-v4.1-flash-1017-fast")
TERRA_FIRST_REPORT_RUNTIME = AgentRuntime(runtime_adapter="codex", model="gpt-6.1-terra", reasoning_effort="medium")


@frozen
class FirstReportExperiment:
    variant: str | None
    agent_runtime: AgentRuntime

    def properties(self) -> dict[str, str]:
        properties = {"runtime": self.agent_runtime.runtime}
        if self.variant is not None:
            properties.update(
                {
                    "experiment_key": FIRST_REPORT_EXPERIMENT,
                    "experiment_variant": self.variant,
                    f"$feature/{FIRST_REPORT_EXPERIMENT}": self.variant,
                }
            )
        return properties


def onboarding_runs_first_report(state: dict[str, Any]) -> bool:
    return state.get("first_report_scout") is True or state.get("first_report_variant") in _LEGACY_FIRST_REPORT_VARIANTS


def resolve_first_report_experiment(team: Team, *, raise_on_error: bool = False) -> FirstReportExperiment:
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
        if raise_on_error:
            raise
        variant = None
    return _experiment_for_variant(variant)


def dispatched_first_report_experiment(team: Team) -> FirstReportExperiment:
    config = SignalTeamConfig.objects.filter(team_id=team.id).only("onboarding").first()
    state = (config.onboarding or {}) if config else {}
    if DISPATCHED_VARIANT_KEY in state:
        return _experiment_for_variant(state[DISPATCHED_VARIANT_KEY])
    return resolve_first_report_experiment(team)


def _experiment_for_variant(variant: object) -> FirstReportExperiment:
    if variant == "control":
        return FirstReportExperiment(variant="control", agent_runtime=DEEPSEEK_FIRST_REPORT_RUNTIME)
    if variant == FIRST_REPORT_TERRA_VARIANT:
        return FirstReportExperiment(variant=FIRST_REPORT_TERRA_VARIANT, agent_runtime=TERRA_FIRST_REPORT_RUNTIME)
    return FirstReportExperiment(variant=None, agent_runtime=DEEPSEEK_FIRST_REPORT_RUNTIME)


def capture_first_report_exposure(team: Team, experiment: FirstReportExperiment) -> None:
    if experiment.variant is None:
        return
    try:
        with ph_scoped_capture() as capture:
            capture(
                distinct_id=str(team.uuid),
                event="$experiment_exposure",
                groups=groups(team.organization, team),
                properties={
                    **experiment.properties(),
                    "$feature_flag": FIRST_REPORT_EXPERIMENT,
                    "$feature_flag_response": experiment.variant,
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
