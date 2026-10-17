"""
Runs the experiment health checks of `products/experiments/backend/health/` as scheduled platform health checks.

The rules stay in the pure checks, so the experiment API and these scheduled runs give the same findings.
This module only loads the experiments of a team batch and maps each finding to a health issue.
"""

from collections.abc import Callable, Iterator

import structlog
import posthoganalytics

from posthog.models import Team
from posthog.models.health_issue import HealthIssue
from posthog.ph_client import get_feature_flag_or_none
from posthog.temporal.health_checks.framework import AlertContent
from posthog.temporal.health_checks.models import HealthCheckResult

from products.experiments.backend.facade.contracts import ExperimentHealthFinding
from products.experiments.backend.health.context import HealthContext, load_health_context
from products.experiments.backend.health.registry import HealthCheck as ExperimentHealthCheck
from products.experiments.backend.models.experiment import Experiment

logger = structlog.get_logger(__name__)

LIVE_GATE_FLAG = "experiments-health-checks"

# One issue per experiment and subcode. A subcode change, such as a paused flag that goes to a 0% rollout,
# resolves the old issue and opens a new one, because the fix is different.
HASH_KEYS = ["experiment_id", "subcode"]

# Experiment names are project data that lands in alerts and in LLM context, so bound them.
_MAX_EXPERIMENT_NAME_LENGTH = 200

_ITERATOR_CHUNK_SIZE = 500

ExperimentScope = Callable[[HealthContext], bool]


def any_experiment(ctx: HealthContext) -> bool:
    return True


def running_experiment(ctx: HealthContext) -> bool:
    return ctx.is_running


def live_gate_team_ids(team_ids: list[int]) -> list[int]:
    """Only the teams `LIVE_GATE_FLAG` answers `True` for.

    A team left out keeps its open issues, so turning the flag off for a team stops new issues
    without closing the old ones.
    """
    # Each flag read retries the definitions load while no definitions are loaded, so check once per batch.
    if posthoganalytics.disabled or not posthoganalytics.feature_flag_definitions():
        logger.warning("experiments_health_checks_live_gate_unreadable", team_count=len(team_ids))
        return []
    teams = Team.objects.filter(id__in=team_ids).order_by("id").values_list("id", "uuid", "organization_id")
    return [
        team_id
        for team_id, team_uuid, organization_id in teams
        if _live_gate_answer(team_id, str(team_uuid), str(organization_id)) is True
    ]


def _live_gate_answer(team_id: int, team_uuid: str, organization_id: str) -> bool | str | None:
    # A team id repeats across PostHog instances, so a flag that must reach one project matches on the uuid.
    return get_feature_flag_or_none(
        LIVE_GATE_FLAG,
        team_uuid,
        groups={"organization": organization_id, "project": str(team_id)},
        group_properties={
            "organization": {"id": organization_id},
            "project": {"id": str(team_id), "uuid": team_uuid},
        },
        only_evaluate_locally=True,
        send_feature_flag_events=False,
    )


def detect_experiment_findings(
    team_ids: list[int],
    check: ExperimentHealthCheck,
    scope: ExperimentScope = any_experiment,
) -> dict[int, list[HealthCheckResult]]:
    """The findings of one experiment health check for every experiment of the given teams.

    The framework resolves the open issues of a team that this result does not hold, so the result must
    cover every experiment of each team. Archived and deleted experiments are left out, so their issues
    resolve. A check error fails the batch, because a missing finding would resolve the open issue.
    """
    results: dict[int, list[HealthCheckResult]] = {}
    for experiment in _experiments(team_ids):
        ctx = load_health_context(experiment)
        if not scope(ctx):
            continue
        finding = check(ctx)
        if finding is not None:
            results.setdefault(experiment.team_id, []).append(_health_check_result(experiment, finding))
    return results


def _experiments(team_ids: list[int]) -> Iterator[Experiment]:
    return (
        Experiment.objects.filter(team_id__in=team_ids, archived=False)
        .exclude(deleted=True)
        .select_related("feature_flag")
        # `load_health_context` counts the shared metrics, so prefetch them to avoid one query per experiment.
        .prefetch_related("experimenttosavedmetric_set")
        .order_by("id")
        .iterator(chunk_size=_ITERATOR_CHUNK_SIZE)
    )


def _health_check_result(experiment: Experiment, finding: ExperimentHealthFinding) -> HealthCheckResult:
    return HealthCheckResult(
        # The finding severities use the health issue severity values on purpose, see `ExperimentHealthFindingSeverity`.
        severity=HealthIssue.Severity(finding.severity.value),
        payload={
            "experiment_id": experiment.id,
            "experiment_name": (experiment.name or "")[:_MAX_EXPERIMENT_NAME_LENGTH],
            # The health page links the "open_feature_flag" action to the flag.
            "feature_flag_id": experiment.feature_flag_id,
            "code": finding.code.value,
            "subcode": finding.subcode,
            "title": finding.title,
            "detail": finding.detail,
            "evidence": dict(finding.evidence),
            "actions": [action.value for action in finding.actions],
            "diagnostic_ref": finding.diagnostic_ref,
        },
        hash_keys=HASH_KEYS,
    )


def render_finding_alert(issue: HealthIssue) -> AlertContent:
    payload = issue.payload
    return AlertContent(
        title=str(payload.get("title") or "Experiment health issue"),
        summary=f"{_experiment_label(payload)}: {payload.get('detail') or ''}".strip(),
        link=_experiment_link(payload),
    )


def _experiment_label(payload: dict) -> str:
    name = str(payload.get("experiment_name") or "")[:_MAX_EXPERIMENT_NAME_LENGTH]
    return f'Experiment "{name}"' if name else f"Experiment {payload.get('experiment_id')}"


def _experiment_link(payload: dict) -> str:
    experiment_id = payload.get("experiment_id")
    return f"/experiments/{experiment_id}" if experiment_id is not None else "/experiments"
