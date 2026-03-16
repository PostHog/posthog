import json
from pathlib import Path
from typing import Any

import pytest

from google.genai import types
from posthoganalytics.ai.gemini import AsyncClient as AsyncGeminiClient
from posthoganalytics.ai.openai import AsyncOpenAI

from posthog.temporal.data_imports.signals.linear_issues import LINEAR_ACTIONABILITY_PROMPT, linear_issue_emitter
from posthog.temporal.data_imports.workflow_activities.emit_signals import (
    GEMINI_MODEL,
    LLM_THINKING_BUDGET_TOKENS,
    _extract_thoughts,
)

from products.signals.eval.framework import EvalCase, EvalMetric, run_eval

JUDGE_MODEL = "gpt-5.2-2025-12-11"

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def load_linear_cases(expected_labels: dict[str, str]) -> list[EvalCase]:
    with open(FIXTURES_DIR / "linear_issues.json") as f:
        issues = json.load(f)

    cases = []
    for issue in issues:
        output = linear_issue_emitter(team_id=0, record=issue)
        if output is None:
            continue
        expected = expected_labels.get(issue["id"])
        if expected is None:
            continue
        cases.append(
            EvalCase(
                name=f"issue_{issue['identifier']}",
                input={
                    "description": output.description,
                    "prompt": LINEAR_ACTIONABILITY_PROMPT.format(description=output.description),
                },
                expected=expected,
            )
        )
    return cases


class TestLinearActionability:
    NOT_ACTIONABLE_ISSUES: set[str] = {
        "b8aca684-3670-4f39-93f2-e7b6e4791d87",
        "30b6c390-3102-42ae-826c-08e0a6106b18",
        "a1c2d3e4-f5a6-4b7c-8d9e-0f1a2b3c4d5e",
        "b2d3e4f5-a6b7-4c8d-9e0f-1a2b3c4d5e6f",
        "d4f5a6b7-c8d9-4e0f-1a2b-3c4d5e6f7a8b",
        "e5a6b7c8-d9e0-4f1a-2b3c-4d5e6f7a8b9c",
        "f6b7c8d9-e0f1-4a2b-3c4d-5e6f7a8b9c0d",
    }

    JUDGE_PROMPT = """You are an eval judge for a Linear issue actionability classifier.

<rubric>
ACTIONABLE (classifier should output ACTIONABLE):
- A bug report: describes something broken, an error, or unexpected behavior
- A feature request or suggestion for improvement
- A usability issue or confusion about the product
- A performance problem or regression
- A question about how to use the product
- A documentation gap or error that caused confusion
- Internal engineering issues that describe a real technical problem or improvement

Example: "Insight loading spinner never disappears when query times out — the frontend never shows an error state after the backend 504s."

NOT_ACTIONABLE (classifier should output NOT_ACTIONABLE):
- A meta/tracking issue with no substantive feedback (release checklists, sprint trackers, one-liner reminders with just a link)
- A duplicate that only says "same as X" with no new information
- An internal housekeeping task (dependency bumps, CI config, infra maintenance)
- Spam, abuse, or profanity with no real feedback

Example: "Q1 release checklist" with a body that is just a task list of release steps

Linear issues are filed intentionally, so when in doubt the classifier should lean ACTIONABLE.
</rubric>

<classifier_output>
{output}
</classifier_output>

<expected>
{expected}
</expected>

{thoughts_section}

<issue>
{description}
</issue>

<instructions>
First analyze the issue content against the rubric. If the classifier's reasoning is provided, consider whether its logic is sound. Then determine whether the classifier's output matches the expected classification.

Respond with JSON: {{"reasoning": "...", "correct": true/false}}
</instructions>"""

    @pytest.fixture(autouse=True)
    def _setup(self, posthog_client, openai_client, case_ids):
        self.posthog_client = posthog_client
        self.openai_client = openai_client
        self.case_ids = case_ids

    @staticmethod
    async def task_fn(client: AsyncOpenAI, case: EvalCase) -> dict[str, Any]:
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
        all_issues = json.loads((FIXTURES_DIR / "linear_issues.json").read_text())
        all_ids = {i["id"] for i in all_issues if linear_issue_emitter(team_id=0, record=i) is not None}
        if self.case_ids is not None:
            all_ids = all_ids & self.case_ids
        expected_labels = {
            iid: ("NOT_ACTIONABLE" if iid in self.NOT_ACTIONABLE_ISSUES else "ACTIONABLE") for iid in all_ids
        }
        cases = load_linear_cases(expected_labels)
        assert len(cases) > 0, "No Linear issue fixtures found"

        results = await run_eval(
            client=self.posthog_client,
            openai_client=self.openai_client,
            experiment_name="linear-actionability-check",
            cases=cases,
            task_fn=self.task_fn,
            judge_fn=self.judge_fn,
        )
        assert len(results) == len(cases)
