from django.test import SimpleTestCase

from rest_framework import serializers

from products.signals.backend.facade.api import SCOUT_EMITTED_EVENTS
from products.workflows.backend.api.run_scout_validation import RUN_SCOUT_TEMPLATE_ID, validate_run_scout_flow

RUN_SCOUT_ACTION = {"id": "run_scout_1", "type": "function", "config": {"template_id": RUN_SCOUT_TEMPLATE_ID}}
EMAIL_ACTION = {"id": "email_1", "type": "function_email", "config": {"template_id": "template-email"}}
MASKING = {"ttl": 1800, "hash": "'run-scout'"}


def _event_trigger(*event_ids: str) -> dict:
    return {"type": "event", "filters": {"events": [{"id": event_id, "type": "events"} for event_id in event_ids]}}


class TestRunScoutFlowValidation(SimpleTestCase):
    def _validate(self, *, actions: list[dict], trigger: dict, masking: dict | None) -> None:
        validate_run_scout_flow(actions=actions, trigger_config=trigger, trigger_masking=masking)

    def _errors(self, *, actions: list[dict], trigger: dict, masking: dict | None) -> list[str]:
        with self.assertRaises(serializers.ValidationError) as caught:
            self._validate(actions=actions, trigger=trigger, masking=masking)
        return [str(error) for error in caught.exception.detail["actions"]]

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

    def test_accepts_an_action_based_trigger(self) -> None:
        # Action-targeted triggers are narrow by construction, so they don't hit the catch-all rule.
        self._validate(
            actions=[RUN_SCOUT_ACTION],
            trigger={"type": "event", "filters": {"actions": [{"id": "7", "type": "actions"}]}},
            masking=MASKING,
        )
