from datetime import timedelta

import pytest
from unittest.mock import patch

from django.utils import timezone

from products.foundry.backend.facade import api
from products.foundry.backend.facade.contracts import CreateBetInput
from products.foundry.backend.facade.enums import BetEventKind
from products.foundry.backend.logic import scout as scout_module
from products.foundry.backend.tasks.tasks import foundry_scout_task


def _exposed_bet_with_ttl_reached(team, user, slug):
    bet = api.create_bet(
        CreateBetInput(
            team_id=team.id,
            slug=slug,
            hypothesis="checking the scout sweep task",
            success_metric={"name": "n/a"},
            guardrails=[],
            budget={},
            exposure_plan={},
            sources=[],
            ttl=timezone.now() - timedelta(hours=1),
        ),
        user=user,
    )
    api.fund_bet(team.id, bet.id, user=user)
    api.record_event(team.id, bet.id, BetEventKind.RUN_STARTED, {}, user=user)
    api.record_event(team.id, bet.id, BetEventKind.GATE_RESULT, {"pass": True}, user=user)
    api.record_event(team.id, bet.id, BetEventKind.EXPOSURE_STARTED, {}, user=user)
    return bet


@pytest.mark.django_db
class TestFoundryScoutTask:
    def test_sweep_records_a_proposal_per_exposed_bet_with_a_pending_condition(self, team, user):
        bet_a = _exposed_bet_with_ttl_reached(team, user, "scout-sweep-a")
        bet_b = _exposed_bet_with_ttl_reached(team, user, "scout-sweep-b")

        foundry_scout_task()

        for bet in (bet_a, bet_b):
            proposed = [e for e in api.list_events(team.id, bet.id) if e.kind == BetEventKind.VERDICT_PROPOSED]
            assert len(proposed) == 1
            assert proposed[0].payload["recommendation"] == "iterate"
            assert proposed[0].payload["evidence"]["condition"] == "ttl_reached"

    def test_one_bad_bet_does_not_stop_the_sweep(self, team, user):
        bet_a = _exposed_bet_with_ttl_reached(team, user, "scout-sweep-good")
        bet_b = _exposed_bet_with_ttl_reached(team, user, "scout-sweep-bad")

        real_propose = scout_module.propose_verdicts_for_bet

        def _flaky_propose(bet):
            if str(bet.id) == str(bet_b.id):
                raise RuntimeError("simulated failure evaluating this bet")
            return real_propose(bet)

        with patch("products.foundry.backend.logic.scout.propose_verdicts_for_bet", side_effect=_flaky_propose):
            foundry_scout_task()

        good_proposed = [e for e in api.list_events(team.id, bet_a.id) if e.kind == BetEventKind.VERDICT_PROPOSED]
        assert len(good_proposed) == 1
        bad_proposed = [e for e in api.list_events(team.id, bet_b.id) if e.kind == BetEventKind.VERDICT_PROPOSED]
        assert bad_proposed == []
