import json
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import uuid4

import pytest
from unittest.mock import MagicMock

from products.subscriptions.backend.facade import pulse as pulse_facade
from products.subscriptions.backend.facade.pulse import (
    _highest_ranked_eligible_action_key,
    _import_analysis_evidence,
    _parse_analysis_output,
    _publication_reservation,
    _read_dispatch_snapshot,
    _recover_analysis_task_binding,
    _recover_execution_task_binding,
    _server_derived_action_keys,
    _start_analysis,
    advance_pulse_workflow,
    prepare_pulse_workflow,
)
from products.subscriptions.backend.models import Artifact, PulseRun, RunAction
from products.subscriptions.backend.pulse.orchestration import PulseOrchestrationConflict
from products.subscriptions.backend.pulse.temporal.inputs import (
    ProactiveDispatchSnapshot,
    PulseStartInput,
    PulseWorkflowInput,
    PulseWorkflowResult,
)
from products.tasks.backend.facade import contracts as tasks_contracts


def _action(*, kind: str = "recommendation") -> dict[str, object]:
    return {
        "opportunity_key": "opportunity:one",
        "opportunity_title": "Opportunity",
        "opportunity_summary": "Summary",
        "action_key": "action:one",
        "kind": kind,
        "title": "Action",
        "rationale": "Because",
        "expected_impact": "Impact",
        "rank": 1,
        "normalized_target": {"metric": "retention"},
        "evidence_tool_call_ids": [],
        "why_now": "The decline is recent",
        "confidence": 0.8,
        "effort": "small",
        "metric_name": "Retention",
        "metric_unit": "percent",
        "metric_direction": "increase",
        "expected_change_type": "absolute",
        "expected_change_lower": 1,
        "expected_change_upper": 3,
        "readout_after_days": 7,
        "selector": {},
        "baseline_tool_call_id": "baseline",
    }


def test_analysis_output_parser_accepts_bounded_selected_action() -> None:
    actions, selected = _parse_analysis_output(
        {"readouts": [], "actions": [_action(kind="combined")], "selected_action_key": "action:one"}
    )

    assert selected == "action:one"
    assert actions[0].kind == "combined"


@pytest.mark.parametrize(
    "output",
    [
        {"readouts": [], "actions": [_action()], "selected_action_key": None, "agent_note": "untrusted"},
        {"readouts": [], "actions": [{**_action(), "rank": True}], "selected_action_key": None},
        {"readouts": [], "actions": [_action(), _action(), _action(), _action()], "selected_action_key": None},
    ],
)
def test_analysis_output_parser_rejects_unbounded_or_malformed_output(output: dict[str, object]) -> None:
    with pytest.raises(PulseOrchestrationConflict):
        _parse_analysis_output(output)


def test_dispatch_snapshot_requires_the_content_addressed_digest(monkeypatch) -> None:
    payload = b'{"version":1}'
    digest = sha256(payload).hexdigest()
    input = PulseStartInput(
        team_id=1,
        subscription_id=2,
        delivery_id=uuid4(),
        report_snapshot_ref="subscription-delivery:example",
        proactive_snapshot=ProactiveDispatchSnapshot(
            version=1,
            enabled=True,
            config_snapshot_ref=f"subscriptions/pulse/dispatch-snapshots/v1/1/2/{digest}.json",
        ),
    )
    monkeypatch.setattr(pulse_facade.object_storage, "read_bytes", lambda *args, **kwargs: payload)

    assert _read_dispatch_snapshot(input) == {"version": 1}

    wrong = PulseStartInput(
        team_id=input.team_id,
        subscription_id=input.subscription_id,
        delivery_id=input.delivery_id,
        report_snapshot_ref=input.report_snapshot_ref,
        proactive_snapshot=ProactiveDispatchSnapshot(
            version=1,
            enabled=True,
            config_snapshot_ref=f"subscriptions/pulse/dispatch-snapshots/v1/1/2/{'0' * 64}.json",
        ),
    )
    with pytest.raises(PulseOrchestrationConflict):
        _read_dispatch_snapshot(wrong)


def test_server_selects_the_highest_ranked_eligible_action_with_derived_keys() -> None:
    parsed, _ = _parse_analysis_output(
        {
            "readouts": [],
            "actions": [
                {**_action(kind="recommendation"), "rank": 1},
                {**_action(kind="experiment_draft"), "action_key": "other", "rank": 2},
            ],
            "selected_action_key": "model-controlled-key",
        }
    )
    derived = _server_derived_action_keys(parsed)
    run = PulseRun(config_snapshot={"flags": {"allow_draft_pr": False, "allow_experiment_draft": True}})

    assert derived[1].action_key != "other"
    assert _highest_ranked_eligible_action_key(run=run, actions=derived) == derived[1].action_key


def test_analysis_passes_the_immutable_context_window_cap_to_tasks(monkeypatch) -> None:
    outcome_memory = {
        "version": 1,
        "proposals": [{"action_key": f"action-{index}", "summary": "x" * 250} for index in range(20)],
        "buckets": [],
    }
    claimed_outcomes = [
        {
            "plan_id": str(uuid4()),
            "source_action_id": str(uuid4()),
            "measurement_spec_version": 1,
        }
    ]
    assert len(json.dumps(outcome_memory)) > 4_000
    run = PulseRun(
        id=uuid4(),
        team_id=1,
        subscription_id=2,
        delivery_id=uuid4(),
        report_snapshot_ref="subscription-delivery:example",
        config_snapshot={
            "actor_id": 3,
            "limits": {"max_agent_context_tokens": 200_000},
            "outcome_memory": outcome_memory,
            "claimed_outcomes": claimed_outcomes,
        },
    )
    created = MagicMock(task_id=uuid4(), analysis_run_id=uuid4())
    create_staged_task = MagicMock(return_value=created)
    bind_analysis = MagicMock()
    monkeypatch.setattr(pulse_facade, "_repository_binding", lambda _: None)
    monkeypatch.setattr(pulse_facade.tasks_api, "create_staged_task", create_staged_task)
    monkeypatch.setattr(pulse_facade, "bind_pulse_analysis_task", bind_analysis)

    _start_analysis(input=MagicMock(), run=run)

    staged_input = create_staged_task.call_args.args[0]
    assert staged_input.origin_product == "pulse_subscription"
    assert staged_input.context_window == "200k"
    description = json.loads(staged_input.description)
    assert description["outcome_memory"] == outcome_memory
    assert description["claimed_outcomes"] == claimed_outcomes
    assert "pulse-outcome-replay-get" in description["task"]
    assert "call --json" in description["task"]
    assert "acted_on_summary" not in description
    bind_analysis.assert_called_once_with(
        team_id=run.team_id,
        run_id=run.id,
        task_id=created.task_id,
        analysis_task_run_id=created.analysis_run_id,
    )


def test_import_analysis_evidence_copies_only_referenced_successful_calls(monkeypatch) -> None:
    run = PulseRun(
        id=uuid4(),
        team_id=1,
        task_id=uuid4(),
        analysis_task_run_id=uuid4(),
        config_snapshot={"actor_id": 3},
    )
    actions, _ = _parse_analysis_output(
        {
            "readouts": [],
            "actions": [
                {
                    **_action(),
                    "baseline_tool_call_id": "baseline",
                    "evidence_tool_call_ids": ["supporting", "errored", "truncated"],
                }
            ],
            "selected_action_key": None,
        }
    )
    readout_id = uuid4()
    readouts = pulse_facade._parse_outcome_readouts(
        {
            "readouts": [
                {
                    "plan_id": str(readout_id),
                    "evidence_tool_call_id": "readout",
                    "failure_code": None,
                    "not_ready": False,
                }
            ]
        }
    )
    completed_at = datetime(2026, 8, 30, tzinfo=UTC)
    calls = [
        tasks_contracts.CompletedPostHogMCPToolCallDTO(
            tool_call_id=tool_call_id,
            tool_name="query-trends",
            arguments={"date_from": "2026-08-01", "date_to": "2026-08-07"},
            result={"results": [{"count": 10}]},
            completed_at=completed_at,
            is_error=is_error,
            is_truncated=is_truncated,
        )
        for tool_call_id, is_error, is_truncated in (
            ("baseline", False, False),
            ("supporting", False, False),
            ("readout", False, False),
            ("unreferenced", False, False),
            ("errored", True, False),
            ("truncated", False, True),
        )
    ]
    team = MagicMock(id=1)
    actor = MagicMock(id=3)
    team_query = MagicMock()
    team_query.first.return_value = team
    actor_query = MagicMock()
    actor_query.first.return_value = actor
    begin = MagicMock()
    complete = MagicMock()
    monkeypatch.setattr(pulse_facade.Team.objects, "filter", MagicMock(return_value=team_query))
    monkeypatch.setattr(pulse_facade.User.objects, "filter", MagicMock(return_value=actor_query))
    read_calls = MagicMock(return_value=calls)
    monkeypatch.setattr(pulse_facade.tasks_api, "get_completed_posthog_mcp_tool_calls", read_calls)
    monkeypatch.setattr(pulse_facade, "begin_evidence_tool_call", begin)
    monkeypatch.setattr(pulse_facade, "complete_evidence_tool_call", complete)

    _import_analysis_evidence(run=run, actions=actions, readouts=readouts)

    read_calls.assert_called_once_with(run.analysis_task_run_id, run.task_id, run.team_id)
    assert [call.kwargs["tool_call_id"] for call in begin.call_args_list] == ["baseline", "supporting", "readout"]
    assert [call.kwargs["tool_call_id"] for call in complete.call_args_list] == ["baseline", "supporting", "readout"]
    assert all(call.kwargs["tool_schema_version"] == "v1" for call in begin.call_args_list)


def test_publication_reservation_keeps_twenty_minutes_for_gates_and_publication(monkeypatch) -> None:
    current_time = datetime(2026, 8, 30, tzinfo=UTC)
    run = PulseRun(
        wall_clock_deadline_at=current_time + timedelta(minutes=60),
        finalization_deadline_at=current_time + timedelta(minutes=55),
    )
    action = RunAction(action_key="action:one", title="Improve retention", rationale="Because")
    artifact = Artifact(kind=Artifact.Kind.DRAFT_PR, idempotency_key="artifact:one")
    grant = tasks_contracts.RepositoryGrantBindingDTO(
        repository="posthog/posthog",
        github_integration_id=123,
        github_installation_id="456",
        grant_version="grant-v1",
    )
    base = tasks_contracts.RepositoryBaseBindingDTO(
        repository="posthog/posthog", base_sha="a" * 40, base_branch="master"
    )
    monkeypatch.setattr(pulse_facade, "_validate_live_subscription_authority", lambda _: None)
    monkeypatch.setattr(pulse_facade, "_repository_binding", lambda _: (grant, base))
    monkeypatch.setattr(pulse_facade.timezone, "now", lambda: current_time)

    reservation = _publication_reservation(run=run, action=action, artifacts=[artifact])

    assert reservation.starts_before == current_time + timedelta(minutes=35)
    assert reservation.expires_at == current_time + timedelta(minutes=60)


def test_prepare_terminalizes_when_subscription_access_is_removed_after_dispatch(monkeypatch) -> None:
    input = PulseStartInput(
        team_id=1,
        subscription_id=2,
        delivery_id=uuid4(),
        report_snapshot_ref="subscription-delivery:example",
        proactive_snapshot=ProactiveDispatchSnapshot(
            version=1,
            enabled=True,
            config_snapshot_ref="snapshot",
        ),
    )
    team = MagicMock()
    actor = MagicMock()
    skipped = MagicMock()
    build_snapshot = MagicMock()
    team_query = MagicMock()
    team_query.first.return_value = team
    actor_query = MagicMock()
    actor_query.first.return_value = actor
    run_query = MagicMock()
    run_query.filter.return_value.first.return_value = None
    authorized = MagicMock(return_value=False)
    terminalize = MagicMock(return_value=skipped)
    monkeypatch.setattr(pulse_facade, "_read_dispatch_snapshot", lambda _: {"actor_id": 3, "contexts": []})
    monkeypatch.setattr(pulse_facade.PulseRun.objects, "for_team", MagicMock(return_value=run_query))
    monkeypatch.setattr(pulse_facade.Team.objects, "filter", MagicMock(return_value=team_query))
    monkeypatch.setattr(pulse_facade.User.objects, "filter", MagicMock(return_value=actor_query))
    monkeypatch.setattr(pulse_facade, "subscription_snapshot_contexts_are_authorized", authorized)
    monkeypatch.setattr(pulse_facade, "_build_activity_config_snapshot", build_snapshot)
    monkeypatch.setattr(pulse_facade, "_prepare_terminal_skipped_run", terminalize)

    assert prepare_pulse_workflow(input) is skipped
    authorized.assert_called_once_with(team=team, user=actor, subscription_id=2, contexts=[])
    terminalize.assert_called_once_with(input=input, failure_code="authorization_changed")
    build_snapshot.assert_not_called()


def test_publication_reservation_rejects_removed_subscription_context_access(monkeypatch) -> None:
    current_time = datetime(2026, 8, 30, tzinfo=UTC)
    run = PulseRun(
        team_id=1,
        subscription_id=2,
        config_snapshot={"actor_id": 3, "contexts": []},
        wall_clock_deadline_at=current_time + timedelta(minutes=60),
        finalization_deadline_at=current_time + timedelta(minutes=55),
    )
    action = RunAction(action_key="action:one", title="Improve retention", rationale="Because")
    artifact = Artifact(kind=Artifact.Kind.DRAFT_PR, idempotency_key="artifact:one")
    team = MagicMock()
    actor = MagicMock()
    team_query = MagicMock()
    team_query.first.return_value = team
    actor_query = MagicMock()
    actor_query.first.return_value = actor
    authorized = MagicMock(return_value=False)
    grant = tasks_contracts.RepositoryGrantBindingDTO(
        repository="posthog/posthog",
        github_integration_id=123,
        github_installation_id="456",
        grant_version="grant-v1",
    )
    base = tasks_contracts.RepositoryBaseBindingDTO(
        repository="posthog/posthog", base_sha="a" * 40, base_branch="master"
    )
    binding = MagicMock(return_value=(grant, base))
    monkeypatch.setattr(pulse_facade.Team.objects, "filter", MagicMock(return_value=team_query))
    monkeypatch.setattr(pulse_facade.User.objects, "filter", MagicMock(return_value=actor_query))
    monkeypatch.setattr(pulse_facade, "subscription_snapshot_contexts_are_authorized", authorized)
    monkeypatch.setattr(pulse_facade, "_repository_binding", binding)
    monkeypatch.setattr(pulse_facade.timezone, "now", lambda: current_time)

    with pytest.raises(PulseOrchestrationConflict, match="subscription access"):
        _publication_reservation(run=run, action=action, artifacts=[artifact])

    authorized.assert_called_once_with(team=team, user=actor, subscription_id=2, contexts=[])
    binding.assert_not_called()


def test_reconciliation_recovers_an_unbound_analysis_task_by_caller_key(monkeypatch) -> None:
    run = PulseRun(id=uuid4(), team_id=1)
    discovered = MagicMock(task_id=uuid4(), analysis_run_id=uuid4())
    get_staged = MagicMock(return_value=discovered)
    bind = MagicMock(return_value=run)
    monkeypatch.setattr(pulse_facade.tasks_api, "get_staged_task_by_idempotency", get_staged)
    monkeypatch.setattr(pulse_facade, "bind_pulse_analysis_task", bind)

    assert _recover_analysis_task_binding(run) is run
    get_staged.assert_called_once()
    lookup = get_staged.call_args.args[0]
    assert lookup.team_id == run.team_id
    assert lookup.caller_id == run.id
    assert lookup.idempotency_key == f"pulse:{run.id}:analysis"
    bind.assert_called_once_with(
        team_id=run.team_id,
        run_id=run.id,
        task_id=discovered.task_id,
        analysis_task_run_id=discovered.analysis_run_id,
        reconcile_existing=True,
    )


def test_advance_recovers_an_unbound_analysis_before_starting_new_work(monkeypatch) -> None:
    run_id = uuid4()
    delivery_id = uuid4()
    unbound = PulseRun(
        id=run_id,
        team_id=1,
        subscription_id=2,
        delivery_id=delivery_id,
        report_snapshot_ref=f"subscription-delivery:{delivery_id}",
        status=PulseRun.Status.PENDING,
        config_snapshot={},
    )
    bound = PulseRun(
        id=run_id,
        team_id=1,
        subscription_id=2,
        delivery_id=delivery_id,
        report_snapshot_ref=unbound.report_snapshot_ref,
        status=PulseRun.Status.ANALYZING,
        task_id=uuid4(),
        analysis_task_run_id=uuid4(),
        config_snapshot={},
    )
    input = PulseWorkflowInput(
        team_id=1,
        subscription_id=2,
        delivery_id=delivery_id,
        pulse_run_id=run_id,
        report_snapshot_ref=unbound.report_snapshot_ref,
        deadline=datetime(2026, 8, 29, tzinfo=UTC),
        proactive_snapshot=ProactiveDispatchSnapshot(version=1, enabled=True, config_snapshot_ref="snapshot"),
    )
    recover = MagicMock(return_value=bound)
    start = MagicMock()
    task_run = MagicMock(task_id=bound.task_id, is_terminal=False)
    monkeypatch.setattr(pulse_facade, "_load_workflow_run", lambda _: unbound)
    monkeypatch.setattr(pulse_facade, "_validate_live_repository_authority", lambda _: None)
    monkeypatch.setattr(pulse_facade, "_recover_analysis_task_binding", recover)
    monkeypatch.setattr(pulse_facade, "_start_analysis", start)
    monkeypatch.setattr(pulse_facade.tasks_api, "get_task_run", MagicMock(return_value=task_run))

    assert advance_pulse_workflow(input) is None
    recover.assert_called_once_with(unbound)
    start.assert_not_called()


def test_reconciliation_recovers_an_unbound_execution_by_selected_action_key(monkeypatch) -> None:
    run = PulseRun(
        id=uuid4(),
        team_id=1,
        task_id=uuid4(),
        analysis_task_run_id=uuid4(),
        status=PulseRun.Status.RESERVING,
    )
    selected = MagicMock(action_key="server-action-key")
    selected_query = MagicMock()
    selected_query.filter.return_value.only.return_value.first.return_value = selected
    discovered = MagicMock(
        task_id=run.task_id,
        analysis_run_id=run.analysis_task_run_id,
        execution_run_id=uuid4(),
        publication_lease_id=uuid4(),
    )
    get_staged = MagicMock(return_value=discovered)
    bind = MagicMock(return_value=run)
    monkeypatch.setattr(pulse_facade.RunAction.objects, "for_team", selected_query.for_team)
    selected_query.for_team.return_value = selected_query
    monkeypatch.setattr(pulse_facade.tasks_api, "get_staged_execution_by_idempotency", get_staged)
    monkeypatch.setattr(pulse_facade, "bind_pulse_execution_task", bind)

    assert _recover_execution_task_binding(run) is run
    lookup = get_staged.call_args.args[0]
    assert lookup.team_id == run.team_id
    assert lookup.caller_id == run.id
    assert lookup.task_id == run.task_id
    assert lookup.source_run_id == run.analysis_task_run_id
    assert lookup.idempotency_key == f"pulse:{run.id}:server-action-key:execution"
    bind.assert_called_once_with(
        team_id=run.team_id,
        run_id=run.id,
        task_id=discovered.task_id,
        analysis_task_run_id=discovered.analysis_run_id,
        execution_task_run_id=discovered.execution_run_id,
        publication_lease_id=discovered.publication_lease_id,
        reconcile_existing=True,
    )


def test_advance_revokes_staged_work_before_starting_when_live_grant_changed(monkeypatch) -> None:
    run_id = uuid4()
    delivery_id = uuid4()
    run = PulseRun(
        id=run_id,
        team_id=1,
        subscription_id=2,
        delivery_id=delivery_id,
        report_snapshot_ref=f"subscription-delivery:{delivery_id}",
        status=PulseRun.Status.PENDING,
        config_snapshot={"repository_grant": {"id": str(uuid4())}},
    )
    input = PulseWorkflowInput(
        team_id=1,
        subscription_id=2,
        delivery_id=delivery_id,
        pulse_run_id=run_id,
        report_snapshot_ref=run.report_snapshot_ref,
        deadline=datetime(2026, 8, 29, tzinfo=UTC),
        proactive_snapshot=ProactiveDispatchSnapshot(version=1, enabled=True, config_snapshot_ref="snapshot"),
    )
    expected = PulseWorkflowResult(
        pulse_run_id=run_id,
        status="failed",
        result_ref=f"subscriptions/pulse/runs/{run_id}",
        failure_code="repository_grant_revoked",
    )
    start_analysis = MagicMock()
    fail_authority = MagicMock(return_value=expected)
    monkeypatch.setattr(pulse_facade, "_load_workflow_run", lambda _: run)
    monkeypatch.setattr(
        pulse_facade,
        "_validate_live_repository_authority",
        MagicMock(side_effect=PulseOrchestrationConflict("revoked")),
    )
    monkeypatch.setattr(pulse_facade, "_fail_revoked_repository_authority", fail_authority)
    monkeypatch.setattr(pulse_facade, "_start_analysis", start_analysis)

    assert advance_pulse_workflow(input) == expected
    fail_authority.assert_called_once_with(run=run)
    start_analysis.assert_not_called()
