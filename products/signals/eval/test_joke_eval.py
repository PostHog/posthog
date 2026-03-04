import json

import pytest

from posthoganalytics.ai.openai import AsyncOpenAI

from products.signals.eval.framework import EvalCase, EvalMetric, run_eval

TASK_MODEL = "gpt-5-nano-2025-08-07"
JUDGE_MODEL = "gpt-5.2-2025-12-11"


async def tell_joke(client: AsyncOpenAI, case: EvalCase) -> str:
    topic = case.input["topic"]
    response = await client.chat.completions.create(
        model=TASK_MODEL,
        messages=[{"role": "user", "content": f"Tell me a short joke about {topic}"}],
        posthog_distinct_id="llma_eval",
    )
    return response.choices[0].message.content or ""


async def judge_monkey_joke(client: AsyncOpenAI, case: EvalCase, output: str) -> EvalMetric:
    response = await client.chat.completions.create(
        model=JUDGE_MODEL,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are an eval judge. Determine if the following joke is about monkeys. "
                    'Respond with JSON: {"is_about_monkeys": true/false, "reasoning": "..."}'
                ),
            },
            {"role": "user", "content": output},
        ],
        posthog_distinct_id="llma_eval",
    )
    raw = response.choices[0].message.content or "{}"
    parsed = json.loads(raw)

    return EvalMetric(
        name="is_monkey_joke",
        version="1",
        result_type="binary",
        score=1.0 if parsed.get("is_about_monkeys") else 0.0,
        score_min=0,
        score_max=1,
        reasoning=parsed.get("reasoning", ""),
    )


CASES = [
    EvalCase(name="monkeys", input={"topic": "monkeys"}, expected=1),
    EvalCase(name="cats", input={"topic": "cats"}, expected=0),
    EvalCase(name="programming", input={"topic": "programming"}, expected=0),
    EvalCase(name="bananas_and_monkeys", input={"topic": "bananas and monkeys"}, expected=1),
]


@pytest.mark.django_db
async def test_monkey_joke_eval(posthog_client, openai_client):
    results = await run_eval(
        client=posthog_client,
        openai_client=openai_client,
        experiment_name="joke-monkey-detection",
        cases=CASES,
        task_fn=tell_joke,
        judge_fn=judge_monkey_joke,
    )
    assert len(results) == len(CASES)


async def judge_walrus_joke(client: AsyncOpenAI, case: EvalCase, output: str) -> EvalMetric:
    response = await client.chat.completions.create(
        model=JUDGE_MODEL,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are an eval judge. Determine if the following joke is about walruses. "
                    'Respond with JSON: {"is_about_walruses": true/false, "reasoning": "..."}'
                ),
            },
            {"role": "user", "content": output},
        ],
        posthog_distinct_id="llma_eval",
    )
    raw = response.choices[0].message.content or "{}"
    parsed = json.loads(raw)

    return EvalMetric(
        name="is_walrus_joke",
        version="1",
        result_type="binary",
        score=1.0 if parsed.get("is_about_walruses") else 0.0,
        score_min=0,
        score_max=1,
        reasoning=parsed.get("reasoning", ""),
    )


WALRUS_CASES = [
    EvalCase(name="walruses", input={"topic": "walruses"}, expected=1),
    EvalCase(name="tusks_and_walruses", input={"topic": "tusks and walruses"}, expected=1),
    EvalCase(name="seals", input={"topic": "seals"}, expected=0),
    EvalCase(name="penguins", input={"topic": "penguins"}, expected=0),
]


@pytest.mark.django_db
async def test_walrus_joke_eval(posthog_client, openai_client):
    results = await run_eval(
        client=posthog_client,
        openai_client=openai_client,
        experiment_name="joke-walrus-detection",
        cases=WALRUS_CASES,
        task_fn=tell_joke,
        judge_fn=judge_walrus_joke,
    )
    assert len(results) == len(WALRUS_CASES)
