from typing import cast

from posthog.test.base import BaseTest

from django.test import SimpleTestCase

from rest_framework import serializers

from products.actions.backend.models import Action
from products.signals.backend.facade.api import SCOUT_EMITTED_EVENTS
from products.workflows.backend.api.run_scout_validation import RUN_SCOUT_TEMPLATE_ID, validate_run_scout_flow

RUN_SCOUT_ACTION = {"id": "run_scout_1", "type": "function", "config": {"template_id": RUN_SCOUT_TEMPLATE_ID}}
EMAIL_ACTION = {"id": "email_1", "type": "function_email", "config": {"template_id": "template-email"}}
MASKING = {"ttl": 1800, "hash": "'run-scout'"}


def _event_trigger(*event_ids: str) -> dict:
    return {"type": "event", "filters": {"events": [{"id": event_id, "type": "events"} for event_id in event_ids]}}


class TestRunScoutFlowValidation(SimpleTestCase):
    def _validate(self, *, actions: list[dict], trigger: dict, masking: dict | None) -> None:
        validate_run_scout_flow(actions=actions, trigger_config=trigger, trigger_masking=masking, team_id=None)

    def _errors(self, *, actions: list[dict], trigger: dict, masking: dict | None) -> list[str]:
        with self.assertRaises(serializers.ValidationError) as caught:
            self._validate(actions=actions, trigger=trigger, masking=masking)
        return [str(error) for error in cast(dict, caught.exception.detail)["actions"]]

    def test_accepts_a_masked_flow_on_a_non_scout_event(self) -> None:
        self._validate(actions=[RUN_SCOUT_ACTION], trigger=_event_trigger("$pageview"), masking=MASKING)

    def test_requires_masking(self) -> None:
        errors = self._errors(actions=[RUN_SCOUT_ACTION], trigger=_event_trigger("$pageview"), masking=None)

        assert len(errors) == 1
        assert "trigger masking" in errors[0]

    def test_rejects_a_trigger_on_a_scout_emitted_event(self) -> None:
        for event in sorted(SCOUT_EMITTED_EVENTS):
            with self.subTest(event=event):
                errors = self._errors(actions=[RUN_SCOUT_ACTION], trigger=_event_trigger(event), masking=MASKING)
                assert len(errors) == 1
                assert event in errors[0]

    def test_rejects_a_trigger_that_matches_every_event(self) -> None:
        # No events and no actions compiles to always-true, so scout output would match it too.
        errors = self._errors(actions=[RUN_SCOUT_ACTION], trigger={"type": "event", "filters": {}}, masking=MASKING)

        assert len(errors) == 1
        assert "matches every event" in errors[0]

    def test_reports_both_problems_at_once(self) -> None:
        errors = self._errors(actions=[RUN_SCOUT_ACTION], trigger=_event_trigger("$scout_report_emitted"), masking=None)

        assert len(errors) == 2

    def test_ignores_a_flow_with_no_run_scout_action(self) -> None:
        # An unmasked catch-all event trigger is perfectly normal without a scout node.
        self._validate(actions=[EMAIL_ACTION], trigger={"type": "event", "filters": {}}, masking=None)

    def test_ignores_a_non_event_trigger(self) -> None:
        # A scheduled or manual flow fires at a rate its author chose and can't be fed by the
        # scout's own output, so neither guard applies.
        for trigger in ({"type": "schedule"}, {"type": "manual", "template_id": "x", "inputs": {}}):
            with self.subTest(trigger=trigger["type"]):
                self._validate(actions=[RUN_SCOUT_ACTION], trigger=trigger, masking=None)

    def test_skips_the_action_check_without_a_team(self) -> None:
        # Outside a request there is no team to resolve actions against; the flow already passed
        # the check on the save that activated it.
        self._validate(
            actions=[RUN_SCOUT_ACTION],
            trigger={"type": "event", "filters": {"actions": [{"id": "7", "type": "actions"}]}},
            masking=MASKING,
        )


class TestRunScoutFlowActionTriggers(BaseTest):
    def _action(self, *steps: dict) -> Action:
        return Action.objects.create(team=self.team, name="watched", steps_json=list(steps))

    def _errors_for(self, action: Action) -> list[str]:
        trigger = {"type": "event", "filters": {"actions": [{"id": str(action.id), "type": "actions"}]}}
        try:
            validate_run_scout_flow(
                actions=[RUN_SCOUT_ACTION], trigger_config=trigger, trigger_masking=MASKING, team_id=self.team.id
            )
        except serializers.ValidationError as caught:
            return [str(error) for error in cast(dict, caught.detail)["actions"]]
        return []

    def test_accepts_an_action_whose_steps_all_name_ordinary_events(self) -> None:
        assert self._errors_for(self._action({"event": "$pageview"}, {"event": "signup"})) == []

    def test_rejects_an_action_with_a_step_on_a_scout_emitted_event(self) -> None:
        errors = self._errors_for(self._action({"event": "$pageview"}, {"event": "$scout_report_emitted"}))

        assert len(errors) == 1
        assert "watched" in errors[0]

    def test_rejects_an_action_with_a_step_that_matches_every_event(self) -> None:
        # An event-less step is a match-all: only the other constraints narrow it, and scout
        # events satisfy a step with none.
        errors = self._errors_for(self._action({"event": None, "url": "/inbox"}))

        assert len(errors) == 1
        assert "step with no event" in errors[0]

    def test_ignores_another_teams_action(self) -> None:
        other_team = self.organization.teams.create(name="other")
        foreign = Action.objects.create(team=other_team, name="foreign", steps_json=[{"event": None}])

        assert self._errors_for(foreign) == []
