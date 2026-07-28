from products.foundry.backend.temporal.activities import record_bet_event_activity, run_node_activity
from products.foundry.backend.temporal.build_activities import check_gate_result_activity, count_gate_results_activity
from products.foundry.backend.temporal.build_workflow import FoundryBuildBetWorkflow
from products.foundry.backend.temporal.expose_activities import evaluate_guardrails_activity, set_flag_rollout_activity
from products.foundry.backend.temporal.expose_workflow import FoundryExposeBetWorkflow
from products.foundry.backend.temporal.registry import ACTIVITIES, WORKFLOWS


def test_build_loop_activities_and_workflow_are_registered():
    """An activity a workflow calls but that's missing from registry.ACTIVITIES fails at
    runtime with "Activity function ... is not registered on this worker" — a real bet
    run hit exactly this for count_gate_results_activity, since the Temporal-testing-
    framework tests build their own explicit activities list and never exercise the
    registry wiring itself. This guards the wiring those tests can't."""
    assert run_node_activity in ACTIVITIES
    assert record_bet_event_activity in ACTIVITIES
    assert check_gate_result_activity in ACTIVITIES
    assert count_gate_results_activity in ACTIVITIES
    assert FoundryBuildBetWorkflow in WORKFLOWS


def test_expose_bet_activities_and_workflow_are_registered():
    """Same class of gap as above, for ADR-6's foundry-expose-bet workflow."""
    assert set_flag_rollout_activity in ACTIVITIES
    assert evaluate_guardrails_activity in ACTIVITIES
    assert FoundryExposeBetWorkflow in WORKFLOWS
