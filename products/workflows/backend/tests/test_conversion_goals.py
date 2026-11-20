from io import StringIO
from typing import Any

import time_machine
from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.core.management import call_command
from django.db import DatabaseError
from django.test import SimpleTestCase

from parameterized import parameterized

from products.workflows.backend.models.hog_flow.hog_flow import HogFlow
from products.workflows.backend.models.hog_flow_conversion_goal import HogFlowConversionGoal
from products.workflows.backend.models.hog_flow_revision import HogFlowRevision
from products.workflows.backend.services.conversion_goals import goal_event_names, pin_conversion_goal

PROPERTY_BYTECODE = ["_H", 1, 32, "Chrome", 32, "$browser", 32, "properties", 32, "person", 1, 3, 11]
EVENT_BYTECODE = ["_H", 1, 32, "purchase", 32, "event", 1, 1, 11]
OTHER_EVENT_BYTECODE = ["_H", 1, 32, "signup", 32, "event", 1, 1, 11]


def _event_entry(bytecode: list, target: str = "events") -> dict:
    return {"filters": {target: [{"id": "purchase", "type": target}], "bytecode": bytecode}}


class TestPinConversionGoal(SimpleTestCase):
    @parameterized.expand(
        [
            ("no conversion", None, None),
            ("not an object", "purchase", None),
            ("no filters or events", {"filters": [], "events": [], "window_minutes": 60}, None),
            (
                "property goal",
                {"filters": [{"key": "$browser"}], "bytecode": PROPERTY_BYTECODE},
                {"properties": PROPERTY_BYTECODE},
            ),
            ("property bytecode without filters", {"filters": [], "bytecode": PROPERTY_BYTECODE}, None),
            ("property filters as an object", {"filters": {"events": []}, "bytecode": PROPERTY_BYTECODE}, None),
            ("event goal", {"events": [_event_entry(EVENT_BYTECODE)]}, {"events": [EVENT_BYTECODE]}),
            ("action goal", {"events": [_event_entry(EVENT_BYTECODE, "actions")]}, {"events": [EVENT_BYTECODE]}),
            ("entry with no target", {"events": [{"filters": {"bytecode": EVENT_BYTECODE}}]}, None),
            ("entry with empty bytecode", {"events": [_event_entry([])]}, None),
            (
                "entry that is not an object",
                {"events": ["purchase", _event_entry(EVENT_BYTECODE)]},
                {"events": [EVENT_BYTECODE]},
            ),
            (
                "both branches",
                {
                    "filters": [{"key": "$browser"}],
                    "bytecode": PROPERTY_BYTECODE,
                    "events": [_event_entry(EVENT_BYTECODE)],
                },
                {"properties": PROPERTY_BYTECODE, "events": [EVENT_BYTECODE]},
            ),
        ]
    )
    def test_pins_what_a_run_stores(self, _name: str, conversion: Any, expected: Any) -> None:
        assert pin_conversion_goal(conversion) == expected


class TestGoalEventNames(SimpleTestCase):
    @parameterized.expand(
        [
            ("no goal", {"filters": [], "events": []}, None),
            ("property goal", {"filters": [{"key": "$browser"}], "bytecode": PROPERTY_BYTECODE}, None),
            ("event goal", {"events": [_event_entry(EVENT_BYTECODE)]}, ["purchase"]),
            (
                "two event entries",
                {
                    "events": [
                        _event_entry(EVENT_BYTECODE),
                        {"filters": {"events": [{"id": "signup", "type": "events"}], "bytecode": OTHER_EVENT_BYTECODE}},
                    ]
                },
                ["purchase", "signup"],
            ),
            ("action goal", {"events": [_event_entry(EVENT_BYTECODE, "actions")]}, None),
            (
                "any event",
                {"events": [{"filters": {"events": [{"id": None, "type": "events"}], "bytecode": EVENT_BYTECODE}}]},
                None,
            ),
            (
                "an entry without bytecode is ignored, even a malformed one",
                {"events": [{"filters": {"events": 1}}, _event_entry(EVENT_BYTECODE)]},
                ["purchase"],
            ),
            (
                "an entry with no target is ignored",
                {"events": [{"filters": {"bytecode": EVENT_BYTECODE}}, _event_entry(EVENT_BYTECODE)]},
                ["purchase"],
            ),
        ]
    )
    def test_names_only_what_the_goal_can_match(self, _name: str, conversion: Any, expected: Any) -> None:
        assert goal_event_names(conversion) == expected


class TestConversionGoalsRecordedOnSave(APIBaseTest):
    def _flow(self, conversion: dict, status: str = "active") -> dict:
        return {
            "name": "Goal flow",
            "status": status,
            "actions": [
                {
                    "id": "trigger_node",
                    "name": "trigger_1",
                    "type": "trigger",
                    "config": {
                        "type": "event",
                        "filters": {"events": [{"id": "$pageview", "name": "$pageview", "type": "events", "order": 0}]},
                    },
                },
                {"id": "exit_node", "name": "exit", "type": "exit", "config": {}},
            ],
            "edges": [{"from": "trigger_node", "to": "exit_node", "type": "continue"}],
            "conversion": conversion,
        }

    def _event_goal(self, event: str) -> dict:
        return {"events": [{"filters": {"events": [{"id": event, "name": event, "type": "events", "order": 0}]}}]}

    def _goals(self, flow_id: str) -> dict[str, HogFlowConversionGoal]:
        goals = HogFlowConversionGoal.objects.unscoped().filter(hog_flow_id=flow_id)
        return {bytecode[3]: goal for goal in goals for bytecode in goal.goal["events"]}

    def _create(self, conversion: dict, status: str = "active") -> str:
        created = self.client.post(f"/api/projects/{self.team.id}/hog_flows", self._flow(conversion, status))
        assert created.status_code == 201, created.json()
        return created.json()["id"]

    def _patch(self, flow_id: str, body: dict) -> None:
        response = self.client.patch(f"/api/projects/{self.team.id}/hog_flows/{flow_id}", body)
        assert response.status_code == 200, response.json()

    def test_every_goal_a_workflow_had_live_is_kept_until_the_workflow_is_deleted(self) -> None:
        with time_machine.travel("2026-11-01T10:00:00Z", tick=False):
            flow_id = self._create(self._event_goal("purchase"))
        assert sorted(self._goals(flow_id)) == ["purchase"]
        assert self._goals(flow_id)["purchase"].event_names == ["purchase"]
        # A workflow saved before goals were recorded: the edit still keeps the goal its runs hold.
        HogFlowConversionGoal.objects.unscoped().filter(hog_flow_id=flow_id).delete()

        with time_machine.travel("2026-11-02T10:00:00Z", tick=False):
            self._patch(flow_id, {"conversion": self._event_goal("signup")})
        goals = self._goals(flow_id)
        assert sorted(goals) == ["purchase", "signup"]
        assert goals["purchase"].last_live_at.isoformat() == "2026-11-02T10:00:00+00:00"

        with time_machine.travel("2026-11-03T10:00:00Z", tick=False):
            self._patch(flow_id, {"status": "draft"})
        goals = self._goals(flow_id)
        assert goals["signup"].last_live_at.isoformat() == "2026-11-03T10:00:00+00:00"
        assert goals["purchase"].last_live_at.isoformat() == "2026-11-02T10:00:00+00:00"

        # Paused, the workflow starts no runs, so a goal edited in now is not one a run can hold.
        self._patch(flow_id, {"conversion": self._event_goal("trial")})
        assert sorted(self._goals(flow_id)) == ["purchase", "signup"]

        deleted = self.client.delete(f"/api/projects/{self.team.id}/hog_flows/{flow_id}")
        assert deleted.status_code == 204
        assert self._goals(flow_id) == {}

    def test_a_draft_records_its_goal_only_when_it_goes_live(self) -> None:
        flow_id = self._create(self._event_goal("purchase"), status="draft")
        self._patch(flow_id, {"conversion": self._event_goal("signup")})
        assert self._goals(flow_id) == {}

        self._patch(flow_id, {"status": "active"})
        assert sorted(self._goals(flow_id)) == ["signup"]

    def test_a_failed_goal_write_rolls_the_save_back(self) -> None:
        flow_id = self._create(self._event_goal("purchase"))

        with patch(
            "products.workflows.backend.services.conversion_goals.HogFlowConversionGoal.objects.unscoped",
            side_effect=DatabaseError("goal write failed"),
        ):
            failed = self.client.patch(
                f"/api/projects/{self.team.id}/hog_flows/{flow_id}", {"conversion": self._event_goal("signup")}
            )
        assert failed.status_code == 500

        flow = HogFlow.objects.get(pk=flow_id)
        assert flow.conversion is not None
        assert flow.conversion["events"][0]["filters"]["events"][0]["id"] == "purchase"
        assert sorted(self._goals(flow_id)) == ["purchase"]

    def test_backfill_records_live_and_revision_goals(self) -> None:
        active_id = self._create(self._event_goal("signup"))
        paused_id = self._create(self._event_goal("trial"), status="draft")
        active = HogFlow.objects.get(pk=active_id)
        HogFlowRevision.objects.unscoped().create(
            team_id=self.team.id,
            hog_flow=active,
            version=active.version + 100,
            content={"conversion": {"events": [_event_entry(EVENT_BYTECODE)]}},
        )
        HogFlow.objects.filter(pk__in=[active_id, paused_id]).update(updated_at="2026-06-01T00:00:00Z")
        HogFlowConversionGoal.objects.unscoped().all().delete()

        call_command("backfill_hog_flow_conversion_goals", stdout=StringIO())
        assert self._goals(active_id) == {}

        with time_machine.travel("2026-11-20T00:00:00Z", tick=False):
            for _ in range(2):
                call_command("backfill_hog_flow_conversion_goals", "--live-run", stdout=StringIO())
                active_goals, paused_goals = self._goals(active_id), self._goals(paused_id)
                # The current goal of an active workflow is live now; any other goal stopped by its last change.
                assert {name: goal.last_live_at.isoformat() for name, goal in active_goals.items()} == {
                    "signup": "2026-11-20T00:00:00+00:00",
                    "purchase": "2026-06-01T00:00:00+00:00",
                }
                assert {name: goal.last_live_at.isoformat() for name, goal in paused_goals.items()} == {
                    "trial": "2026-06-01T00:00:00+00:00"
                }
