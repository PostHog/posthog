from typing import cast

from posthog.test.base import BaseTest

from django.test import SimpleTestCase

from parameterized import parameterized
from rest_framework import serializers

from posthog.models import Team

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
        validate_run_scout_flow(actions=actions, trigger_config=trigger, trigger_masking=masking, team=None)

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

    @parameterized.expand(
        [
            ("expression_hash", {"ttl": 1800, "hash": "{person.id}"}),
            ("sampling_threshold", {"ttl": 1800, "hash": "'run-scout'", "threshold": 1}),
            ("short_ttl", {"ttl": 600, "hash": "'run-scout'"}),
            ("no_ttl", {"ttl": None, "hash": "'run-scout'"}),
        ]
    )
    def test_rejects_masking_that_fires_more_than_once_per_window(self, _name: str, masking: dict) -> None:
        # Masking is only a flood guard when it collapses a burst to one fire: a per-person hash
        # or a sampling threshold still enqueues one workflow per person or per Nth match, and a
        # window shorter than the scout cooldown only buys guaranteed 429 skips.
        errors = self._errors(actions=[RUN_SCOUT_ACTION], trigger=_event_trigger("$pageview"), masking=masking)

        assert len(errors) == 1
        assert "at most once per window" in errors[0]

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

    def test_ignores_a_single_fire_trigger(self) -> None:
        # A scheduled or manual flow fires at a rate its author chose and can't be fed by the
        # scout's own output, so neither guard applies.
        for trigger in ({"type": "schedule"}, {"type": "manual", "template_id": "x", "inputs": {}}):
            with self.subTest(trigger=trigger["type"]):
                self._validate(actions=[RUN_SCOUT_ACTION], trigger=trigger, masking=None)

    @parameterized.expand([("batch",), ("data-warehouse-table",), ("data-warehouse-view",), ("slack-message",)])
    def test_requires_masking_on_a_per_occurrence_trigger(self, trigger_type: str) -> None:
        # A batch enrolls every audience member and a warehouse trigger fires per row; without
        # masking each one is a run request, of which all but the first are rejected.
        trigger = {"type": trigger_type}
        errors = self._errors(actions=[RUN_SCOUT_ACTION], trigger=trigger, masking=None)
        assert len(errors) == 1
        assert "trigger masking" in errors[0]

        self._validate(actions=[RUN_SCOUT_ACTION], trigger=trigger, masking=MASKING)

    @parameterized.expand([("webhook", "webhook"), ("tracking_pixel", "tracking pixel")])
    def test_rejects_a_trigger_the_masker_never_sees(self, trigger_type: str, label: str) -> None:
        # The source webhooks consumer builds these invocations directly, so masking cannot
        # throttle them even when configured.
        errors = self._errors(actions=[RUN_SCOUT_ACTION], trigger={"type": trigger_type}, masking=MASKING)

        assert len(errors) == 1
        assert f"a {label} trigger" in errors[0]

    def test_skips_the_team_checks_without_a_team(self) -> None:
        # Outside a request there is no team to resolve actions or the environment against; the
        # flow already passed both on the save that activated it.
        self._validate(
            actions=[RUN_SCOUT_ACTION],
            trigger={"type": "event", "filters": {"actions": [{"id": "7", "type": "actions"}]}},
            masking=MASKING,
        )


class TestRunScoutFlowTeamChecks(BaseTest):
    def _action(self, team: Team, *steps: dict) -> Action:
        return Action.objects.create(team=team, name="watched", steps_json=list(steps))

    def _errors_for(self, action: Action | None = None, *, team: Team | None = None) -> list[str]:
        trigger = (
            {"type": "event", "filters": {"actions": [{"id": str(action.id), "type": "actions"}]}}
            if action is not None
            else _event_trigger("$pageview")
        )
        try:
            validate_run_scout_flow(
                actions=[RUN_SCOUT_ACTION], trigger_config=trigger, trigger_masking=MASKING, team=team or self.team
            )
        except serializers.ValidationError as caught:
            return [str(error) for error in cast(dict, caught.detail)["actions"]]
        return []

    def test_accepts_an_action_whose_steps_all_name_ordinary_events(self) -> None:
        assert self._errors_for(self._action(self.team, {"event": "$pageview"}, {"event": "signup"})) == []

    def test_rejects_an_action_with_a_step_on_a_scout_emitted_event(self) -> None:
        errors = self._errors_for(self._action(self.team, {"event": "$pageview"}, {"event": "$scout_report_emitted"}))

        assert len(errors) == 1
        assert "watched" in errors[0]

    def test_rejects_an_action_with_a_step_that_matches_every_event(self) -> None:
        # An event-less step is a match-all: only the other constraints narrow it, and scout
        # events satisfy a step with none.
        errors = self._errors_for(self._action(self.team, {"event": None, "url": "/inbox"}))

        assert len(errors) == 1
        assert "step with no event" in errors[0]

    def test_checks_an_action_from_a_child_environment_of_the_same_project(self) -> None:
        # The trigger compiler resolves actions project-wide, so the guard has to as well.
        env = Team.objects.create(
            organization=self.organization, project=self.team.project, parent_team=self.team, name="env"
        )

        assert len(self._errors_for(self._action(env, {"event": None}))) == 1

    def test_ignores_an_action_from_another_project(self) -> None:
        other_project_team = self.organization.teams.create(name="other")

        assert self._errors_for(self._action(other_project_team, {"event": None})) == []

    def test_rejects_a_workflow_in_a_child_environment(self) -> None:
        # The run endpoint is called by a service token, with no human credential left to check
        # against the environment that owns the scouts, so the node is refused where the human is.
        env = Team.objects.create(
            organization=self.organization, project=self.team.project, parent_team=self.team, name="env"
        )

        errors = self._errors_for(team=env)

        assert len(errors) == 1
        assert "main environment" in errors[0]
