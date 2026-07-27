import pytest

from products.foundry.backend.facade import api
from products.foundry.backend.facade.contracts import CreateBetInput
from products.foundry.backend.facade.enums import BetEventKind, BetState, BetVerdict
from products.foundry.backend.logic import BetStateError
from products.foundry.backend.models import Bet


def _create_bet(team, slug="checkout-friction"):
    return api.create_bet(
        CreateBetInput(
            team_id=team.id,
            slug=slug,
            hypothesis="Reducing checkout steps from 3 to 1 raises purchase conversion",
            success_metric={"name": "purchase conversion rate", "target": "+10%"},
            guardrails=[{"name": "error rate", "constraint": "must not rise"}],
            budget={"usd": 50, "time_hours": 24, "iterations": 3},
            exposure_plan={},
            sources=[{"label": "report: checkout friction", "url": "https://example.com/report/1"}],
        )
    )


def _drive_to(team, bet_id, target: BetState):
    api.fund_bet(team.id, bet_id)
    if target == BetState.FUNDED:
        return
    api.record_event(team.id, bet_id, BetEventKind.RUN_STARTED, {})
    if target == BetState.BUILDING:
        return
    api.record_event(team.id, bet_id, BetEventKind.GATE_RESULT, {"pass": True, "violations": []})
    if target == BetState.GATED:
        return
    api.record_event(team.id, bet_id, BetEventKind.EXPOSURE_STARTED, {})


@pytest.mark.django_db
class TestBetLifecycle:
    def test_funding_creates_flag_and_draft_experiment(self, team):
        bet = _create_bet(team)
        assert bet.state == BetState.DRAFTED

        funded = api.fund_bet(team.id, bet.id)

        assert funded.state == BetState.FUNDED
        assert funded.feature_flag_key == "bet-checkout-friction"
        assert funded.feature_flag_id is not None
        assert funded.experiment_id is not None

        row = Bet.objects.for_team(team.id).get(id=bet.id)
        assert row.experiment.start_date is None  # draft
        assert row.feature_flag.active is False  # draft experiment keeps its flag off

    def test_full_lifecycle_to_promoted(self, team):
        bet = _create_bet(team)
        api.fund_bet(team.id, bet.id)

        assert api.record_event(team.id, bet.id, BetEventKind.RUN_STARTED, {}).kind == BetEventKind.RUN_STARTED
        assert api.get_bet(team.id, bet.id).state == BetState.BUILDING

        api.record_event(
            team.id,
            bet.id,
            BetEventKind.GATE_RESULT,
            {"pass": False, "violations": [{"code": "tests", "message": "2 failing", "severity": "error"}]},
        )
        assert api.get_bet(team.id, bet.id).state == BetState.BUILDING

        api.record_event(team.id, bet.id, BetEventKind.GATE_RESULT, {"pass": True, "violations": []})
        assert api.get_bet(team.id, bet.id).state == BetState.GATED

        api.record_event(team.id, bet.id, BetEventKind.EXPOSURE_STARTED, {})
        assert api.get_bet(team.id, bet.id).state == BetState.EXPOSED

        final = api.record_verdict(team.id, bet.id, BetVerdict.PROMOTED)
        assert final.state == BetState.ARCHIVED
        assert final.verdict == BetVerdict.PROMOTED

        kinds = [e.kind for e in api.list_events(team.id, bet.id)]
        assert kinds.count(BetEventKind.STATE_CHANGED) == 5
        assert kinds.count(BetEventKind.GATE_RESULT) == 2

        with pytest.raises(BetStateError):
            api.record_event(team.id, bet.id, BetEventKind.NOTE, {"text": "too late"})

    def test_iterate_returns_to_building_and_increments_iteration(self, team):
        bet = _create_bet(team)
        _drive_to(team, bet.id, BetState.EXPOSED)

        iterated = api.record_verdict(team.id, bet.id, BetVerdict.ITERATE)

        assert iterated.state == BetState.BUILDING
        assert iterated.verdict is None
        assert iterated.iteration == 2

        api.record_event(team.id, bet.id, BetEventKind.GATE_RESULT, {"pass": True, "violations": []})
        assert api.get_bet(team.id, bet.id).state == BetState.GATED

    @pytest.mark.parametrize(
        "target_state,action",
        [
            (BetState.FUNDED, lambda api, team_id, bet_id: api.fund_bet(team_id, bet_id)),
            (
                BetState.DRAFTED,
                lambda api, team_id, bet_id: api.record_verdict(team_id, bet_id, BetVerdict.PROMOTED),
            ),
            (
                BetState.FUNDED,
                lambda api, team_id, bet_id: api.record_event(
                    team_id, bet_id, BetEventKind.GATE_RESULT, {"pass": True}
                ),
            ),
            (
                BetState.BUILDING,
                lambda api, team_id, bet_id: api.record_event(team_id, bet_id, BetEventKind.EXPOSURE_STARTED, {}),
            ),
            (
                BetState.FUNDED,
                lambda api, team_id, bet_id: api.record_event(team_id, bet_id, BetEventKind.STATE_CHANGED, {}),
            ),
        ],
    )
    def test_invalid_actions_rejected(self, team, target_state, action):
        bet = _create_bet(team)
        if target_state != BetState.DRAFTED:
            _drive_to(team, bet.id, target_state)

        with pytest.raises(BetStateError):
            action(api, team.id, bet.id)
