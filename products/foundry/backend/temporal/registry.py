"""Workflow and activity registration lists for the foundry Temporal worker.

Kept separate from ``temporal/__init__.py`` (owned elsewhere) so the worker wiring has a
stable import target: ``from products.foundry.backend.temporal.registry import WORKFLOWS, ACTIVITIES``.
"""

from __future__ import annotations

from products.foundry.backend.temporal.activities import record_bet_event_activity, run_node_activity
from products.foundry.backend.temporal.build_activities import check_gate_result_activity, count_gate_results_activity
from products.foundry.backend.temporal.build_workflow import FoundryBuildBetWorkflow
from products.foundry.backend.temporal.expose_activities import evaluate_guardrails_activity, set_flag_rollout_activity
from products.foundry.backend.temporal.expose_workflow import FoundryExposeBetWorkflow
from products.foundry.backend.temporal.gate_activities import (
    provision_gate_sandbox_activity,
    run_command_check_activity,
    run_coverage_check_activity,
    run_flag_guard_check_activity,
    run_mutation_check_activity,
    run_protected_paths_check_activity,
    run_reviewhog_check_activity,
    teardown_gate_sandbox_activity,
)
from products.foundry.backend.temporal.gate_workflow import FoundryGateWorkflow
from products.foundry.backend.temporal.workflow import FoundryNodeWorkflow

WORKFLOWS = [FoundryNodeWorkflow, FoundryGateWorkflow, FoundryBuildBetWorkflow, FoundryExposeBetWorkflow]

ACTIVITIES = [
    run_node_activity,
    record_bet_event_activity,
    provision_gate_sandbox_activity,
    teardown_gate_sandbox_activity,
    run_command_check_activity,
    run_coverage_check_activity,
    run_mutation_check_activity,
    run_protected_paths_check_activity,
    run_flag_guard_check_activity,
    run_reviewhog_check_activity,
    check_gate_result_activity,
    count_gate_results_activity,
    set_flag_rollout_activity,
    evaluate_guardrails_activity,
]

__all__ = ["WORKFLOWS", "ACTIVITIES"]
