import pytest
from unittest.mock import patch

from products.foundry.backend.facade import api
from products.foundry.backend.facade.contracts import CreateBetInput
from products.foundry.backend.facade.enums import BetEventKind, BetState
from products.foundry.backend.logic import BetStateError


def _gated_bet(team, user, *, exposure_plan=None, guardrails=None):
    bet = api.create_bet(
        CreateBetInput(
            team_id=team.id,
            slug="exposure-hook-test",
            hypothesis="checking the automatic exposure-ramp hook",
            success_metric={"name": "n/a"},
            guardrails=guardrails or [],
            budget={},
            exposure_plan=exposure_plan or {},
            sources=[],
        ),
        user=user,
    )
    api.fund_bet(team.id, bet.id, user=user)
    api.record_event(team.id, bet.id, BetEventKind.RUN_STARTED, {}, user=user)
    api.record_event(team.id, bet.id, BetEventKind.GATE_RESULT, {"pass": True, "violations": []}, user=user)
    return bet


@pytest.mark.django_db
class TestExposureAutoStartHook:
    def test_no_steps_or_auto_start_leaves_ramp_entirely_manual(self, team, user, django_capture_on_commit_callbacks):
        """ADR-6 criterion 2: no steps / auto_start false must not start a workflow — the
        grey-box path (manual flag edits) stays exactly as before this iteration."""
        bet = _gated_bet(
            team, user, exposure_plan={"auto_start": False, "steps": [{"rollout_pct": 100, "min_hours": 1}]}
        )

        with (
            patch(
                "products.foundry.backend.temporal.expose_client.execute_foundry_expose_bet_workflow"
            ) as mock_execute,
            django_capture_on_commit_callbacks(execute=True),
        ):
            api.record_event(team.id, bet.id, BetEventKind.EXPOSURE_STARTED, {}, user=user)

        mock_execute.assert_not_called()
        assert api.get_bet(team.id, bet.id).state == BetState.EXPOSED

    def test_auto_start_plan_schedules_the_exposure_workflow(self, team, user, django_capture_on_commit_callbacks):
        exposure_plan = {
            "auto_start": True,
            "steps": [{"rollout_pct": 10, "min_hours": 0.01}, {"rollout_pct": 100, "min_hours": 0.01}],
        }
        guardrails = [{"name": "error rate", "constraint": "must not rise"}]
        bet = _gated_bet(team, user, exposure_plan=exposure_plan, guardrails=guardrails)

        with (
            patch(
                "products.foundry.backend.temporal.expose_client.execute_foundry_expose_bet_workflow"
            ) as mock_execute,
            django_capture_on_commit_callbacks(execute=True),
        ):
            api.record_event(team.id, bet.id, BetEventKind.EXPOSURE_STARTED, {}, user=user)

        assert api.get_bet(team.id, bet.id).state == BetState.EXPOSED
        mock_execute.assert_called_once()
        call_kwargs = mock_execute.call_args.kwargs
        assert call_kwargs["bet_id"] == str(bet.id)
        assert call_kwargs["guardrails"] == guardrails
        assert call_kwargs["steps"] == exposure_plan["steps"]

    def test_temporal_unavailable_degrades_gracefully_bet_stays_exposed(
        self, team, user, django_capture_on_commit_callbacks
    ):
        """No Celery-degrade path for this hook (unlike the gate hook) — a start failure is
        just logged, and the bet still ends up exposed for a human to ramp by hand."""
        exposure_plan = {"auto_start": True, "steps": [{"rollout_pct": 100, "min_hours": 1}]}
        bet = _gated_bet(team, user, exposure_plan=exposure_plan)

        with (
            patch(
                "products.foundry.backend.temporal.expose_client.execute_foundry_expose_bet_workflow",
                side_effect=RuntimeError("no Temporal server reachable"),
            ),
            django_capture_on_commit_callbacks(execute=True),
        ):
            api.record_event(team.id, bet.id, BetEventKind.EXPOSURE_STARTED, {}, user=user)

        assert api.get_bet(team.id, bet.id).state == BetState.EXPOSED

    def test_duplicate_exposure_started_is_rejected_by_the_state_machine(self, team, user):
        """A second exposure.started can't reach this hook at all once the bet has left
        GATED — the state machine itself prevents double-driving the flag."""
        bet = _gated_bet(
            team, user, exposure_plan={"auto_start": True, "steps": [{"rollout_pct": 100, "min_hours": 1}]}
        )
        with patch("products.foundry.backend.temporal.expose_client.execute_foundry_expose_bet_workflow"):
            api.record_event(team.id, bet.id, BetEventKind.EXPOSURE_STARTED, {}, user=user)

        with pytest.raises(BetStateError):
            api.record_event(team.id, bet.id, BetEventKind.EXPOSURE_STARTED, {}, user=user)
