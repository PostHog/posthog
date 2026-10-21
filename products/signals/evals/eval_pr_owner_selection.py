from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

from products.posthog_ai.eval_harness.config import BaseEvalCase
from products.posthog_ai.eval_harness.harness.context import EvalContext
from products.posthog_ai.eval_harness.harness.requirements import SuiteKind
from products.posthog_ai.eval_harness.one_shot import OneShotPrivateEval
from products.posthog_ai.eval_harness.scorers.contract import Score, Scorer
from products.signals.backend.artefact_schemas import PROwnerDecision, PROwnerInput
from products.signals.backend.pr_owner_selection import (
    dri_candidate_logins,
    ordered_owner_logins,
    select_pr_owner,
    validate_owner_decision,
)
from products.signals.backend.pr_owning_team import OwningTeam

SUITE_KIND = SuiteKind.ONE_SHOT
CASES = json.loads((Path(__file__).parent / "fixtures/pr_owner_selection.json").read_text())


async def compare_owner_policies(case: dict[str, Any], *, team_id: int, replay: bool = False) -> dict[str, Any]:
    inputs = PROwnerInput.model_validate(case["inputs"])
    baseline = case["baseline"]
    old = dri_candidate_logins(
        claimant=baseline["claimant"],
        opted_in=set(baseline["opted_in"]),
        team=OwningTeam(slug=baseline["team_slug"], logins=tuple(baseline["team_logins"])),
        reviewers=baseline["reviewers"],
    )
    started = time.monotonic()
    try:
        decision = (
            PROwnerDecision.model_validate(case["recorded_decision"])
            if replay
            else await select_pr_owner(inputs, team_id=team_id, trace_id=str(uuid4()))
        )
        validate_owner_decision(decision, inputs)
        proposed = ordered_owner_logins(
            decision, {identity.login for identity in inputs.identities if identity.opted_in}
        )
        outcome = decision.outcome
    except Exception as error:
        proposed, outcome = [], "lookup_failed"
        decision = PROwnerDecision(outcome="lookup_failed", reason=type(error).__name__)
    return {
        "baseline_owner": old[0] if old else None,
        "proposed_owner": proposed[0] if proposed else None,
        "outcome": outcome,
        "decision": decision.model_dump(mode="json"),
        "label_source": case["label_source"],
        "mode": "recorded-output-replay" if replay else "model",
        "model_latency_seconds": None if replay else time.monotonic() - started,
        "model_cost_usd": 0 if replay else None,
    }


class AcceptableOwner(Scorer):
    def __init__(self, policy: str) -> None:
        self.policy = policy

    def _name(self) -> str:
        return f"{self.policy}_acceptable_owner"

    def _run_eval_sync(self, output: dict | None, expected: dict | None = None, **kwargs: Any) -> Score:
        if output is None or expected is None:
            return Score(name=self._name(), score=0)
        acceptable = expected["acceptable_owners"]
        owner = output[f"{self.policy}_owner"]
        if self.policy == "proposed" and output["outcome"] == "lookup_failed":
            return Score(name=self._name(), score=0)
        return Score(name=self._name(), score=float(owner in acceptable if acceptable else owner is None))


async def eval_pr_owner_selection(ctx: EvalContext) -> None:
    async def task(case: BaseEvalCase, task_ctx: EvalContext) -> dict[str, Any]:
        if task_ctx.demo_data is None:
            raise RuntimeError("PR owner evaluation requires a demo billing team")
        saved = next(saved for saved in CASES if saved["name"] == case.name)
        return await compare_owner_policies(saved, team_id=task_ctx.demo_data.master_team_id)

    await OneShotPrivateEval(
        experiment_name="signals-pr-owner-selection",
        cases=[
            BaseEvalCase(
                name=case["name"],
                prompt=json.dumps(case["inputs"]),
                expected={"acceptable_owners": case["acceptable_owners"]},
            )
            for case in CASES
        ],
        scorers=[AcceptableOwner("baseline"), AcceptableOwner("proposed")],
        task=task,
        ctx=ctx,
        send_to_posthog=False,
    )
