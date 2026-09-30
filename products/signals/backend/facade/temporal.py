"""Production Temporal registrations needed to execute and judge scout comparisons."""

from products.signals.backend.temporal.agentic.scout_scheduler import (
    RunSignalsScoutWorkflow,
    resume_signals_scout_workflow_step,
    run_signals_scout_activity,
)
from products.signals.backend.temporal.agentic.scout_trial_comparison import (
    RunScoutTrialComparisonWorkflow,
    dispatch_scout_trial_comparison_activity,
    fail_scout_trial_comparison_activity,
    finish_scout_trial_comparison_activity,
    prepare_scout_trial_comparison_evaluation_activity,
)
from products.signals.backend.temporal.agentic.scout_trial_evaluation import (
    RunScoutTrialEvaluationWorkflow,
    finish_scout_trial_evaluation_activity,
    judge_scout_trial_run_activity,
    load_scout_trial_evaluation_activity,
)

SCOUT_COMPARISON_WORKFLOWS = [
    RunScoutTrialComparisonWorkflow,
    RunSignalsScoutWorkflow,
    RunScoutTrialEvaluationWorkflow,
]

SCOUT_COMPARISON_ACTIVITIES = [
    dispatch_scout_trial_comparison_activity,
    prepare_scout_trial_comparison_evaluation_activity,
    finish_scout_trial_comparison_activity,
    fail_scout_trial_comparison_activity,
    run_signals_scout_activity,
    resume_signals_scout_workflow_step,
    load_scout_trial_evaluation_activity,
    judge_scout_trial_run_activity,
    finish_scout_trial_evaluation_activity,
]

__all__ = ["SCOUT_COMPARISON_ACTIVITIES", "SCOUT_COMPARISON_WORKFLOWS"]
