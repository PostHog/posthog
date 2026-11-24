import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from django.test import SimpleTestCase

from parameterized import parameterized

from products.tasks.backend.agent_run_policy import agent_policy_for_origin, resolve_agent_run_policy

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
