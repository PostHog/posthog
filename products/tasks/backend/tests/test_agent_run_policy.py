import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from django.test import SimpleTestCase

from parameterized import parameterized

from products.tasks.backend.agent_run_policy import (
    agent_policy_for_origin,
    resolve_agent_run_policy,
    task_agent_run_policy,
)
from products.tasks.backend.models import Task

_CASES = json.loads(
    (Path(__file__).parents[4] / "packages/agent/packages/agent/src/server/launch/run-policy-cases.json").read_text()
)["policy_from_origin"]


class TestSharedRunPolicyContract(SimpleTestCase):
    @parameterized.expand([(case["name"], case) for case in _CASES])
    def test_origin_policy_matches_the_agent(self, _name: str, case: dict[str, Any]) -> None:
        policy = resolve_agent_run_policy(
            agent_policy_for_origin(case["origin_product"]),
            {"end_run_when_done": case["end_run_when_done"], "caller_ends_run": case["caller_ends_run"]},
        )

        self.assertEqual(asdict(policy), case["expected"])


class TestTaskAgentRunPolicy(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "a_profile_over_its_origin",
                Task(origin_product="user_created", profile="review_hog", team_id=1),
                {},
                {"finish_tool": False, "thread_link": False},
            ),
            (
                "the_origin_without_a_profile",
                Task(origin_product="user_created", team_id=1),
                {},
                {"finish_tool": True, "thread_link": True},
            ),
            (
                "the_run_state",
                Task(origin_product="workflow", profile="workflow", team_id=1),
                {"end_run_when_done": True},
                {"finish_tool": True, "finish_report_required": True},
            ),
        ]
    )
    def test_policy_follows(self, _name: str, task: Task, run_state: dict[str, Any], expected: dict[str, Any]) -> None:
        policy = asdict(task_agent_run_policy(task, run_state))

        self.assertEqual({key: policy[key] for key in expected}, expected)
