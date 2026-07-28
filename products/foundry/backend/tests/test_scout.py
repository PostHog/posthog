from datetime import timedelta

import pytest
from unittest.mock import patch

from django.utils import timezone

from products.experiments.backend.facade.contracts import ExperimentSignificanceResult, ExperimentVariantSignificance
from products.foundry.backend.facade import api
from products.foundry.backend.facade.contracts import CreateBetInput
from products.foundry.backend.facade.enums import BetEventKind, BetVerdict
from products.foundry.backend.logic import scout
from products.foundry.backend.logic.scout import GuardrailEvaluation
from products.foundry.backend.models import Bet, BetEvent

_GUARDRAIL = {
    "name": "error rate",
    "metric": {"metric_kind": "error_rate", "query_ref": "abc"},
    "threshold": 0.05,
    "direction": "above",
}


def _exposed_bet(team, user, *, guardrails=None, ttl=None, exposure_plan=None) -> Bet:
    bet = api.create_bet(
        CreateBetInput(
            team_id=team.id,
            slug="scout-test",
            hypothesis="checking the scout's conclusion conditions",
            success_metric={"name": "n/a"},
            guardrails=guardrails or [],
            budget={},
            exposure_plan=exposure_plan or {},
            sources=[],
            ttl=ttl,
        ),
        user=user,
    )
    api.fund_bet(team.id, bet.id, user=user)
    api.record_event(team.id, bet.id, BetEventKind.RUN_STARTED, {}, user=user)
    api.record_event(team.id, bet.id, BetEventKind.GATE_RESULT, {"pass": True}, user=user)
    api.record_event(team.id, bet.id, BetEventKind.EXPOSURE_STARTED, {}, user=user)
    return Bet.objects.for_team(team.id).get(id=bet.id)


@pytest.mark.django_db
class TestProposeVerdictsForBet:
    def test_non_exposed_bet_has_nothing_to_propose(self, team, user):
        bet_dto = api.create_bet(
            CreateBetInput(
                team_id=team.id,
                slug="drafted-bet",
                hypothesis="h",
                success_metric={"name": "m"},
                guardrails=[],
                budget={},
                exposure_plan={},
                sources=[],
            ),
            user=user,
        )
        bet = Bet.objects.for_team(team.id).get(id=bet_dto.id)
        assert scout.propose_verdicts_for_bet(bet) == []

    def test_guardrail_breach_proposes_rolled_back(self, team, user):
        bet = _exposed_bet(team, user, guardrails=[_GUARDRAIL])

        with patch(
            "products.foundry.backend.logic.scout.evaluate_guardrails",
            return_value=[
                GuardrailEvaluation(name="error rate", parameterized=True, breached=True, detail="0.08 vs 0.05")
            ],
        ):
            proposals = scout.propose_verdicts_for_bet(bet)

        assert [(p.condition, p.recommendation) for p in proposals] == [("guardrail_breach", BetVerdict.ROLLED_BACK)]

    def test_unparameterized_guardrail_never_breaches(self, team, user):
        bet = _exposed_bet(team, user, guardrails=[{"name": "vibes", "constraint": "must feel good"}])

        assert scout.propose_verdicts_for_bet(bet) == []

    def test_experiment_significant_proposes_promoted(self, team, user):
        bet = _exposed_bet(team, user)

        with patch(
            "products.experiments.backend.facade.api.get_experiment_significance",
            return_value=ExperimentSignificanceResult(
                metrics_evaluated=1,
                variants=[ExperimentVariantSignificance(key="test", significant=True)],
                any_significant=True,
            ),
        ):
            proposals = scout.propose_verdicts_for_bet(bet)

        assert [(p.condition, p.recommendation) for p in proposals] == [("experiment_significant", BetVerdict.PROMOTED)]

    @pytest.mark.parametrize("halted_first,expected", [(False, BetVerdict.ITERATE), (True, BetVerdict.ROLLED_BACK)])
    def test_ttl_reached_recommendation_depends_on_a_prior_halt(self, team, user, halted_first, expected):
        bet = _exposed_bet(team, user, ttl=timezone.now() - timedelta(hours=1))
        if halted_first:
            api.record_event(
                team.id, str(bet.id), BetEventKind.EXPOSURE_HALTED, {"reason": "guardrail_breach"}, user=user
            )

        proposals = scout.propose_verdicts_for_bet(bet)

        assert [(p.condition, p.recommendation) for p in proposals] == [("ttl_reached", expected)]

    def test_exposure_completed_and_stable_proposes_promoted(self, team, user):
        exposure_plan = {"steps": [{"rollout_pct": 100, "min_hours": 0.001}], "auto_start": False}
        bet = _exposed_bet(team, user, exposure_plan=exposure_plan)
        api.record_event(
            team.id, str(bet.id), BetEventKind.EXPOSURE_ADVANCED, {"step": 0, "rollout_pct": 100}, user=user
        )
        BetEvent.objects.filter(bet=bet, kind=BetEventKind.EXPOSURE_ADVANCED).update(
            created_at=timezone.now() - timedelta(hours=1)
        )

        proposals = scout.propose_verdicts_for_bet(bet)

        assert [(p.condition, p.recommendation) for p in proposals] == [("exposure_completed", BetVerdict.PROMOTED)]

    def test_exposure_advanced_but_not_yet_stable_proposes_nothing(self, team, user):
        exposure_plan = {"steps": [{"rollout_pct": 100, "min_hours": 0.001}], "auto_start": False}
        bet = _exposed_bet(team, user, exposure_plan=exposure_plan)
        api.record_event(
            team.id, str(bet.id), BetEventKind.EXPOSURE_ADVANCED, {"step": 0, "rollout_pct": 100}, user=user
        )

        assert scout.propose_verdicts_for_bet(bet) == []

    def test_dedup_skips_a_condition_already_proposed(self, team, user):
        bet = _exposed_bet(team, user, guardrails=[_GUARDRAIL])
        api.record_event(
            team.id,
            str(bet.id),
            BetEventKind.VERDICT_PROPOSED,
            {"recommendation": "rolled_back", "evidence": {"condition": "guardrail_breach"}},
            user=user,
        )

        with patch(
            "products.foundry.backend.logic.scout.evaluate_guardrails",
            return_value=[
                GuardrailEvaluation(name="error rate", parameterized=True, breached=True, detail="0.08 vs 0.05")
            ],
        ):
            proposals = scout.propose_verdicts_for_bet(bet)

        assert proposals == []
