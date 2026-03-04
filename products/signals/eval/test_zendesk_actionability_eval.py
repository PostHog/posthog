import json
from pathlib import Path

import pytest

from posthoganalytics.ai.openai import OpenAI

from posthog.temporal.data_imports.signals.zendesk_tickets import ZENDESK_ACTIONABILITY_PROMPT, zendesk_ticket_emitter
from posthog.temporal.data_imports.workflow_activities.emit_signals import GEMINI_MODEL

from products.signals.eval.framework import EvalCase, EvalMetric, run_eval

JUDGE_MODEL = "gpt-5.2-2025-12-11"

FIXTURES_DIR = Path(__file__).parent / "fixtures"

NOT_ACTIONABLE_TICKETS = {"00005", "00006"}


def load_zendesk_cases() -> list[EvalCase]:
    with open(FIXTURES_DIR / "zendesk_tickets.json") as f:
        tickets = json.load(f)

    cases = []
    for ticket in tickets:
        output = zendesk_ticket_emitter(team_id=0, record=ticket)
        if output is None:
            continue
        expected = "NOT_ACTIONABLE" if ticket["id"] in NOT_ACTIONABLE_TICKETS else "ACTIONABLE"
        cases.append(
            EvalCase(
                name=f"ticket_{ticket['id']}",
                input={
                    "description": output.description,
                    "prompt": ZENDESK_ACTIONABILITY_PROMPT.format(description=output.description),
                },
                expected=expected,
            )
        )
    return cases


def check_actionability(client: OpenAI, case: EvalCase) -> str:
    """Mirrors production: call Gemini with the actionability prompt."""
    from posthoganalytics.ai.gemini import Client as GeminiClient

    gemini = GeminiClient(posthog_client=client._ph_client)
    response = gemini.models.generate_content(
        model=GEMINI_MODEL,
        contents=[case.input["prompt"]],
        posthog_distinct_id="llma_eval",
    )
    return (response.text or "").strip().upper()


JUDGE_PROMPT = """You are an eval judge for a support ticket actionability classifier.

## Rubric

ACTIONABLE (classifier should output ACTIONABLE):
- A bug report: user describes something broken, an error, or unexpected behavior in the product
- A feature request: user asks for new functionality or an improvement
- A usability issue: user is confused by the product or finds something hard to use
- A performance problem: user reports slowness, timeouts, or high resource usage
- A product question: user asks how to accomplish something with the product or its integrations

Example ACTIONABLE ticket: "I'm getting a 500 error when I try to export my dashboard as PDF. It worked last week."

NOT_ACTIONABLE (classifier should output NOT_ACTIONABLE):
- Spam, abuse, or profanity with no real feedback
- Routine billing/account admin: refund requests, payment method updates, invoice questions, plan changes (unless they indicate a product bug)
- A generic thank-you or confirmation that an issue was resolved
- Auto-generated or bot messages with no user content
- Internal test messages

Example NOT_ACTIONABLE ticket: "Hi, can you process a refund for our last invoice? We downgraded last month. Thanks!"

## Task

The classifier responded with: {output}
The expected classification is: {expected}

<ticket>
{description}
</ticket>

First analyze the ticket content against the rubric above, then determine whether the classifier's output matches the expected classification.

Respond with JSON: {{"reasoning": "...", "correct": true/false}}"""


def judge_actionability(client: OpenAI, case: EvalCase, output: str) -> EvalMetric:
    response = client.chat.completions.create(
        model=JUDGE_MODEL,
        messages=[
            {
                "role": "system",
                "content": JUDGE_PROMPT.format(
                    output=output,
                    expected=case.expected,
                    description=case.input["description"],
                ),
            },
        ],
        posthog_distinct_id="llma_eval",
    )
    raw = response.choices[0].message.content or "{}"
    parsed = json.loads(raw)

    return EvalMetric(
        name="actionability_correctness",
        version="2",
        result_type="binary",
        score=1.0 if parsed.get("correct") else 0.0,
        score_min=0,
        score_max=1,
        reasoning=parsed.get("reasoning", ""),
    )


@pytest.mark.django_db
def test_zendesk_actionability_eval(posthog_client, openai_client):
    cases = load_zendesk_cases()
    assert len(cases) > 0, "No zendesk ticket fixtures found"

    results = run_eval(
        client=posthog_client,
        openai_client=openai_client,
        experiment_name="zendesk-actionability-check",
        cases=cases,
        task_fn=check_actionability,
        judge_fn=judge_actionability,
    )
    assert len(results) == len(cases)
