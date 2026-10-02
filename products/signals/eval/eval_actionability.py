"""Pre-emit actionability eval: does each source's actionability gate keep real feedback and drop noise?

Feeds the invented, held-out cases in `fixtures/actionability_data.py` through the production
`check_actionability` call with each source's registered prompt, and measures both directions:
noise let through (false admits) and real feedback dropped (false drops).

Run (needs the LLM gateway env, same as eval_grouping_e2e):
    pytest products/signals/eval/eval_actionability.py -xvs
    pytest products/signals/eval/eval_actionability.py -xvs --no-capture
"""

import sys
import asyncio

from tqdm import tqdm

from products.signals.backend.emission import registry
from products.signals.backend.emission.pipeline import check_actionability
from products.signals.backend.emission.registry import SignalEmitterOutput
from products.signals.eval.capture import EvalMetric, capture_evaluation, deterministic_uuid
from products.signals.eval.conftest import EVAL_TEAM_ID
from products.signals.eval.fixtures.actionability_data import ACTIONABILITY_CASES

MAX_CONCURRENT_CHECKS = 16


class EvalActionability:
    async def eval_actionability_gate(self, gateway_client, posthog_client, no_capture, online, limit):
        cases = ACTIONABILITY_CASES[:limit] if limit else ACTIONABILITY_CASES
        eval_type = "online" if online else "offline"
        configs = {(cfg.source_product, cfg.source_type): cfg for cfg in registry._SIGNAL_TABLE_CONFIGS.values()}
        semaphore = asyncio.Semaphore(MAX_CONCURRENT_CHECKS)

        async def judge(case):
            config = configs[(case.source_product, case.source_type)]
            output = SignalEmitterOutput(
                source_product=case.source_product,
                source_type=case.source_type,
                source_id=case.name,
                description=case.description,
                weight=1.0,
                extra={},
            )
            async with semaphore:
                return await check_actionability(
                    gateway_client,
                    EVAL_TEAM_ID,
                    output,
                    config.actionability_prompt,
                    context_fields=config.actionability_context_fields,
                )

        progress = tqdm(total=len(cases), desc="Actionability", unit="case", file=sys.stderr)

        async def judge_and_tick(case):
            verdict = await judge(case)
            progress.update(1)
            return verdict

        verdicts = await asyncio.gather(*(judge_and_tick(case) for case in cases))
        progress.close()

        false_admits = [case.name for case, verdict in zip(cases, verdicts) if verdict and not case.actionable]
        false_drops = [case.name for case, verdict in zip(cases, verdicts) if not verdict and case.actionable]
        n_negative = sum(1 for case in cases if not case.actionable)
        n_positive = len(cases) - n_negative

        if not no_capture:
            for case, verdict in zip(cases, verdicts):
                correct = verdict == case.actionable
                capture_evaluation(
                    client=posthog_client,
                    experiment_id=deterministic_uuid("actionability-gate"),
                    experiment_name="actionability-gate",
                    item_id=deterministic_uuid(case.name),
                    item_name=case.name,
                    metrics=[
                        EvalMetric(
                            name="correct_classification",
                            result_type="binary",
                            score=1.0 if correct else 0.0,
                            reasoning=case.category,
                        )
                    ],
                    input=case.description,
                    output="ACTIONABLE" if verdict else "NOT_ACTIONABLE",
                    expected="ACTIONABLE" if case.actionable else "NOT_ACTIONABLE",
                    passed=correct,
                    eval_type=eval_type,
                )
            capture_evaluation(
                client=posthog_client,
                experiment_id=deterministic_uuid("actionability-aggregate"),
                experiment_name="actionability-aggregate",
                item_id=deterministic_uuid("actionability-aggregate"),
                item_name="aggregate statistics",
                metrics=[
                    EvalMetric(
                        name="false_admit_rate",
                        description="Fraction of non-actionable records the gate let through",
                        result_type="numeric",
                        score=len(false_admits) / n_negative if n_negative else 0.0,
                        reasoning=f"{len(false_admits)}/{n_negative} non-actionable records admitted",
                    ),
                    EvalMetric(
                        name="false_drop_rate",
                        description="Fraction of actionable records the gate dropped",
                        result_type="numeric",
                        score=len(false_drops) / n_positive if n_positive else 0.0,
                        reasoning=f"{len(false_drops)}/{n_positive} actionable records dropped",
                    ),
                ],
                eval_type=eval_type,
            )

        tqdm.write(
            f"\nActionability ({len(cases)} cases):\n"
            f"  False admits  {len(false_admits)}/{n_negative}: {false_admits}\n"
            f"  False drops   {len(false_drops)}/{n_positive}: {false_drops}",
            file=sys.stderr,
        )
