import json
from pathlib import Path
from typing import Any

import pytest

from google.genai import types
from posthoganalytics.ai.gemini import AsyncClient as AsyncGeminiClient
from posthoganalytics.ai.openai import AsyncOpenAI

from posthog.temporal.data_imports.signals.zendesk_tickets import ZENDESK_ACTIONABILITY_PROMPT, zendesk_ticket_emitter
from posthog.temporal.data_imports.workflow_activities.emit_signals import (
    GEMINI_MODEL,
    LLM_THINKING_BUDGET_TOKENS,
    _extract_thoughts,
)

from products.signals.eval.framework import EvalCase, EvalMetric, run_eval

JUDGE_MODEL = "gpt-5.2-2025-12-11"

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def load_zendesk_cases(expected_labels: dict[str, str] | None = None) -> list[EvalCase]:
    with open(FIXTURES_DIR / "zendesk_tickets.json") as f:
        tickets = json.load(f)

    cases = []
    for ticket in tickets:
        output = zendesk_ticket_emitter(team_id=0, record=ticket)
        if output is None:
            continue
        expected = expected_labels.get(ticket["id"]) if expected_labels else None
        if expected is None:
            continue
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


class TestZendeskActionability:
    NOT_ACTIONABLE_TICKETS = {"00005", "00006", "00009", "00010", "00018", "00019", "00021", "00022"}

    JUDGE_PROMPT = """You are an eval judge for a support ticket actionability classifier.

<rubric>
ACTIONABLE (classifier should output ACTIONABLE):
- A bug report: user describes something broken, an error, or unexpected behavior in the product
- A feature request: user asks for new functionality or an improvement
- A usability issue: user is confused by the product or finds something hard to use
- A performance problem: user reports slowness, timeouts, or high resource usage
- A product question: user asks how to accomplish something with the product or its integrations

Example: "I'm getting a 500 error when I try to export my dashboard as PDF. It worked last week."

NOT_ACTIONABLE (classifier should output NOT_ACTIONABLE):
- Spam, abuse, or profanity with no real feedback
- Routine billing/account admin: refund requests, payment method updates, invoice questions, plan changes (unless they indicate a product bug)
- A generic thank-you or confirmation that an issue was resolved
- Auto-generated or bot messages with no user content
- Internal test messages

Example: "Hi, can you process a refund for our last invoice? We downgraded last month. Thanks!"
</rubric>

<classifier_output>
{output}
</classifier_output>

<expected>
{expected}
</expected>

{thoughts_section}

<ticket>
{description}
</ticket>

<instructions>
First analyze the ticket content against the rubric. If the classifier's reasoning is provided, consider whether its logic is sound. Then determine whether the classifier's output matches the expected classification.

Respond with JSON: {{"reasoning": "...", "correct": true/false}}
</instructions>"""

    @pytest.fixture(autouse=True)
    def _setup(self, posthog_client, openai_client, case_ids):
        self.posthog_client = posthog_client
        self.openai_client = openai_client
        self.case_ids = case_ids

    @staticmethod
    async def task_fn(client: AsyncOpenAI, case: EvalCase) -> dict[str, Any]:
        """Mirrors production: call Gemini with thinking enabled."""
        gemini = AsyncGeminiClient(posthog_client=client._ph_client)
        response = await gemini.models.generate_content(
            model=GEMINI_MODEL,
            contents=[case.input["prompt"]],
            config=types.GenerateContentConfig(
                max_output_tokens=LLM_THINKING_BUDGET_TOKENS + 128,
                thinking_config=types.ThinkingConfig(
                    thinking_budget=LLM_THINKING_BUDGET_TOKENS,
                    include_thoughts=True,
                ),
            ),
            posthog_distinct_id="llma_eval",
        )
        return {
            "answer": (response.text or "").strip().upper(),
            "thoughts": _extract_thoughts(response),
        }

    @classmethod
    async def judge_fn(cls, client: AsyncOpenAI, case: EvalCase, output: dict[str, Any]) -> EvalMetric:
        thoughts = output.get("thoughts")
        thoughts_section = f"\n<classifier_thoughts>\n{thoughts}\n</classifier_thoughts>\n" if thoughts else ""

        response = await client.chat.completions.create(  # type: ignore[call-overload]
            model=JUDGE_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": cls.JUDGE_PROMPT.format(
                        output=output["answer"],
                        expected=case.expected,
                        description=case.input["description"],
                        thoughts_section=thoughts_section,
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
    async def test_actionability(self):
        all_tickets = json.loads((FIXTURES_DIR / "zendesk_tickets.json").read_text())
        all_ids = {t["id"] for t in all_tickets if zendesk_ticket_emitter(team_id=0, record=t) is not None}
        if self.case_ids is not None:
            all_ids = all_ids & self.case_ids
        expected_labels = {
            tid: ("NOT_ACTIONABLE" if tid in self.NOT_ACTIONABLE_TICKETS else "ACTIONABLE") for tid in all_ids
        }
        cases = load_zendesk_cases(expected_labels)
        assert len(cases) > 0, "No zendesk ticket fixtures found"

        results = await run_eval(
            client=self.posthog_client,
            openai_client=self.openai_client,
            experiment_name="zendesk-actionability-check",
            cases=cases,
            task_fn=self.task_fn,
            judge_fn=self.judge_fn,
        )
        assert len(results) == len(cases)
