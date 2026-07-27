import pytest
from unittest.mock import patch

from products.foundry.backend.facade import api
from products.foundry.backend.facade.contracts import CreateBetInput
from products.foundry.backend.facade.enums import BetEventKind, BetState
from products.review_hog.backend.facade.contracts import ReviewReportStatus, ReviewViolation, TriggerReviewResult


def _bet_in_building(team, user, **create_kwargs):
    bet = api.create_bet(
        CreateBetInput(
            team_id=team.id,
            slug="gate-test",
            hypothesis="checking the automatic gate hook",
            success_metric={"name": "n/a"},
            guardrails=[],
            budget={},
            exposure_plan={},
            sources=[],
            **create_kwargs,
        ),
        user=user,
    )
    api.fund_bet(team.id, bet.id, user=user)
    api.record_event(team.id, bet.id, BetEventKind.RUN_STARTED, {}, user=user)
    return bet


@pytest.mark.django_db
class TestReviewHogGate:
    def test_flag_off_leaves_bet_building_for_manual_gate(self, team, user):
        """No automatic gate.result lands when foundry-reviewhog-gate is off (the default)."""
        with patch("products.foundry.backend.logic.gate.reviewhog_gate_enabled", return_value=False):
            bet = _bet_in_building(team, user)
            api.record_event(team.id, bet.id, BetEventKind.RUN_FINISHED, {}, user=user)

        assert api.get_bet(team.id, bet.id).state == BetState.BUILDING
        kinds = [e.kind for e in api.list_events(team.id, bet.id)]
        assert BetEventKind.GATE_RESULT not in kinds

        # the grey-box escape hatch: manual gate.result still works regardless
        api.record_event(team.id, bet.id, BetEventKind.GATE_RESULT, {"pass": True, "violations": []}, user=user)
        assert api.get_bet(team.id, bet.id).state == BetState.GATED

    def test_flag_on_but_no_pr_url_skips_gracefully(self, team, user, django_capture_on_commit_callbacks):
        with (
            patch("products.foundry.backend.logic.gate.reviewhog_gate_enabled", return_value=True),
            django_capture_on_commit_callbacks(execute=True),
        ):
            bet = _bet_in_building(team, user)
            api.record_event(team.id, bet.id, BetEventKind.RUN_FINISHED, {}, user=user)

        assert api.get_bet(team.id, bet.id).state == BetState.BUILDING
        events = api.list_events(team.id, bet.id)
        gate_events = [e for e in events if e.kind == BetEventKind.GATE_RESULT]
        assert len(gate_events) == 1
        assert gate_events[0].payload["skipped"] is True

    def test_flag_on_and_reviewhog_unavailable_skips_gracefully(self, team, user, django_capture_on_commit_callbacks):
        with (
            patch("products.foundry.backend.logic.gate.reviewhog_gate_enabled", return_value=True),
            patch("products.review_hog.backend.facade.api.is_review_available_for_team", return_value=False),
            django_capture_on_commit_callbacks(execute=True),
        ):
            bet = _bet_in_building(team, user)
            api.record_event(
                team.id, bet.id, BetEventKind.ARTIFACT_READY, {"pr_url": "https://github.com/o/r/pull/1"}, user=user
            )

        assert api.get_bet(team.id, bet.id).state == BetState.BUILDING
        gate_events = [e for e in api.list_events(team.id, bet.id) if e.kind == BetEventKind.GATE_RESULT]
        assert len(gate_events) == 1
        assert gate_events[0].payload["skipped"] is True

    def test_flag_on_and_review_completes_maps_violations_to_gate_result(
        self, team, user, django_capture_on_commit_callbacks
    ):
        with (
            patch("products.foundry.backend.logic.gate.reviewhog_gate_enabled", return_value=True),
            patch("products.review_hog.backend.facade.api.is_review_available_for_team", return_value=True),
            patch(
                "products.review_hog.backend.facade.api.trigger_review",
                return_value=TriggerReviewResult(started=True, review_id="review-1", reason=None),
            ),
            patch(
                "products.review_hog.backend.facade.api.get_review_status",
                return_value=ReviewReportStatus(
                    review_id="review-1",
                    in_progress=False,
                    violations=[ReviewViolation(code="bug", message="off-by-one", severity="must_fix")],
                ),
            ),
            django_capture_on_commit_callbacks(execute=True),
        ):
            bet = _bet_in_building(team, user)
            api.record_event(
                team.id, bet.id, BetEventKind.ARTIFACT_READY, {"pr_url": "https://github.com/o/r/pull/1"}, user=user
            )

        # a must_fix violation blocks the transition — state stays building, matching a manual gate.result{pass:false}
        assert api.get_bet(team.id, bet.id).state == BetState.BUILDING
        gate_events = [e for e in api.list_events(team.id, bet.id) if e.kind == BetEventKind.GATE_RESULT]
        assert len(gate_events) == 1
        assert gate_events[0].payload["pass"] is False
        assert gate_events[0].payload["violations"] == [
            {"code": "bug", "message": "off-by-one", "severity": "must_fix"}
        ]
        assert gate_events[0].payload["review_id"] == "review-1"
