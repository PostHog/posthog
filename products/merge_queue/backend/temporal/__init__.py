"""Stampede Temporal surface — the worker registers `WORKFLOWS` and `ACTIVITIES`."""

from products.merge_queue.backend.temporal.activities import mark_trial_running, record_trial_result, run_full_suite
from products.merge_queue.backend.temporal.trial_workflow import TrialWorkflow

WORKFLOWS = [TrialWorkflow]

ACTIVITIES = [
    mark_trial_running,
    run_full_suite,
    record_trial_result,
]
