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


def judge_actionability(client: OpenAI, case: EvalCase, output: str) -> EvalMetric:
    response = client.chat.completions.create(
        model=JUDGE_MODEL,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are an eval judge for a support ticket actionability classifier. "
                    "The classifier was given a Zendesk support ticket and asked to determine "
                    "if it contains actionable product feedback.\n\n"
                    "The classifier responded with: {output}\n"
                    "The expected classification is: {expected}\n\n"
                    "The ticket description is:\n<ticket>\n{description}\n</ticket>\n\n"
                    "Evaluate whether the classifier's response matches the expected classification. "
                    "A ticket is ACTIONABLE if it describes a bug, feature request, usability issue, "
                    "performance problem, or product question. "
                    "It is NOT_ACTIONABLE if it is spam, routine billing, a thank-you, or auto-generated.\n\n"
                    'Respond with JSON: {{"correct": true/false, "reasoning": "..."}}'
                ).format(output=output, expected=case.expected, description=case.input["description"]),
            },
        ],
        posthog_distinct_id="llma_eval",
    )
    raw = response.choices[0].message.content or "{}"
    parsed = json.loads(raw)

    return EvalMetric(
        name="actionability_correctness",
        version="1",
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
