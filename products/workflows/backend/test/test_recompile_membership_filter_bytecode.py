import json
from copy import deepcopy

from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase

from posthog.hogql.compiler.bytecode import create_bytecode

from posthog.cdp.filters import compile_filters_expr
from posthog.models.user import User

from products.cdp.backend.models.hog_functions.hog_function import HogFunction
from products.workflows.backend.models.hog_flow.hog_flow import HogFlow

from common.hogvm.python.execute import execute_bytecode
from common.hogvm.python.operation import Operation

# A numeric event property filtered with a multi-value "exact" — the shape that used to compile to a
# strict IN and never match a numeric value (e.g. a survey rating sent as a number).
FILTERS_DEF = {
    "properties": [
        {
            "key": "$survey_response_x",
            "value": ["1", "2", "3", "4", "5", "6"],
            "operator": "exact",
            "type": "event",
        }
    ]
}


@patch("products.workflows.backend.models.hog_flow.hog_flow.reload_hog_flows_on_workers")
class TestRecompileMembershipFilterBytecode(TestCase):
    def setUp(self):
        super().setUp()
        _org, team, _user = User.objects.bootstrap("Test org", "ben@posthog.com", None)
        self.team = team
        # The genuine pre-fix bytecode: compile the expr directly, bypassing compile_filters_bytecode's
        # rewrite, so we get the strict IN opcode a row would have been stored with before this change.
        # json round-trip normalizes Operation enum members to the ints a JSONField round-trip yields.
        self.stale_bytecode = json.loads(
            json.dumps(create_bytecode(compile_filters_expr(FILTERS_DEF, self.team)).bytecode)
        )

    def _stale_filters(self):
        return {**deepcopy(FILTERS_DEF), "bytecode": deepcopy(self.stale_bytecode)}

    def _seed_function(self, type="destination"):
        fn = HogFunction.objects.create(team=self.team, name="fn", type=type, hog="return event")
        # .update() bypasses HogFunction.save(), which would recompile (and fix) the filters.
        HogFunction.objects.filter(pk=fn.pk).update(filters=self._stale_filters())
        fn.refresh_from_db()
        return fn

    def _seed_flow(self):
        flow = HogFlow.objects.create(name="flow", team=self.team)
        actions = [
            {"id": "trigger_node", "type": "trigger", "config": {}},
            {
                "id": "branch",
                "type": "conditional_branch",
                "config": {"conditions": [{"filters": self._stale_filters()}]},
            },
        ]
        HogFlow.objects.filter(pk=flow.pk).update(actions=actions)
        flow.refresh_from_db()
        return flow

    @staticmethod
    def _flow_condition_bytecode(flow):
        return flow.actions[1]["config"]["conditions"][0]["filters"]["bytecode"]

    def test_seeded_bytecode_reproduces_the_bug(self, _mock_reload):
        # Sanity check: the strict-IN bytecode genuinely fails to match a numeric value.
        assert Operation.IN in self.stale_bytecode
        assert execute_bytecode(self.stale_bytecode, {"properties": {"$survey_response_x": 6}}).result is False

    def test_dry_run_changes_nothing(self, _mock_reload):
        fn = self._seed_function()
        flow = self._seed_flow()

        call_command("recompile_membership_filter_bytecode")

        fn.refresh_from_db()
        flow.refresh_from_db()
        assert fn.filters["bytecode"] == self.stale_bytecode
        assert self._flow_condition_bytecode(flow) == self.stale_bytecode

    def test_live_run_recompiles_function_and_workflow(self, _mock_reload):
        fn = self._seed_function()
        flow = self._seed_flow()

        call_command("recompile_membership_filter_bytecode", "--live-run")

        fn.refresh_from_db()
        flow.refresh_from_db()
        for bytecode in (fn.filters["bytecode"], self._flow_condition_bytecode(flow)):
            # The strict IN is gone, replaced by a coercing equality chain that matches the number.
            assert Operation.IN not in bytecode
            assert execute_bytecode(bytecode, {"properties": {"$survey_response_x": 6}}).result is True
            assert execute_bytecode(bytecode, {"properties": {"$survey_response_x": 7}}).result is False

    def test_live_run_is_idempotent(self, _mock_reload):
        fn = self._seed_function()

        call_command("recompile_membership_filter_bytecode", "--live-run")
        fn.refresh_from_db()
        recompiled = fn.filters["bytecode"]

        # A second live run recompiles to the same bytecode, so nothing is rewritten again.
        call_command("recompile_membership_filter_bytecode", "--live-run")
        fn.refresh_from_db()
        assert fn.filters["bytecode"] == recompiled

    def test_internal_destinations_skipped_unless_opted_in(self, _mock_reload):
        fn = self._seed_function(type="internal_destination")

        call_command("recompile_membership_filter_bytecode", "--live-run")
        fn.refresh_from_db()
        assert fn.filters["bytecode"] == self.stale_bytecode  # untouched by default

        call_command("recompile_membership_filter_bytecode", "--live-run", "--include-internal")
        fn.refresh_from_db()
        assert Operation.IN not in fn.filters["bytecode"]

    def test_team_id_scopes_the_backfill(self, _mock_reload):
        fn = self._seed_function()
        _other_org, other_team, _other_user = User.objects.bootstrap("Other org", "other@posthog.com", None)

        call_command("recompile_membership_filter_bytecode", "--live-run", f"--team-id={other_team.id}")
        fn.refresh_from_db()
        assert fn.filters["bytecode"] == self.stale_bytecode  # different team, untouched
