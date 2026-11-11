"""One-shot eval of how AI subscription summaries are styled once Slack renders them.

Arms, scored side by side on the same invented cases:

- structured: the production prompt and schema, rendered the way production renders it for Slack.
- markdown: the same input data, but the model writes plain Markdown bullets without a schema.

`structured__findings_tagged` tracks how often the model returns a finding as one untagged text
item, which renders with no styling at all.
Stub mode returns canned replies, so the suite runs without model credentials. Set
SUMMARY_STYLING_EVAL_LIVE=1 to call OpenAI directly with OPENAI_API_KEY, using the production prompt, model and parameters.

Results stay local: the suite compares design options for one decision, so it is not enrolled in
PostHog offline reporting.

To run:
    LLM_GATEWAY_ANTHROPIC_API_KEY=unused hogli evals eval_summary_styling
    SUMMARY_STYLING_EVAL_LIVE=1 hogli evals eval_summary_styling --trials 3
"""

from __future__ import annotations

import io
import os
import asyncio
from functools import cache

from openai import OpenAI

from products.posthog_ai.eval_harness.config import BaseEvalCase
from products.posthog_ai.eval_harness.harness.context import EvalContext
from products.posthog_ai.eval_harness.harness.requirements import SuiteKind
from products.posthog_ai.eval_harness.one_shot import OneShotEval
from products.subscriptions.backend.logic.report_text import ReportSummary
from products.subscriptions.backend.temporal.llm_change_summary import (
    SUMMARY_OUTPUT_INSTRUCTIONS,
    _attach_images_to_user_message,
    build_summary_messages,
    generate_report_summary,
    request_summary_completion,
    summary_user_tag,
)
from products.subscriptions.evals.cases import CASES, CASES_BY_NAME, SummaryCase
from products.subscriptions.evals.styling import (
    all_scorers,
    extract_input_values,
    render_arms,
    single_text_finding_rate,
)

SUITE_KIND = SuiteKind.ONE_SHOT

LIVE_EVAL_ENV_VAR = "SUMMARY_STYLING_EVAL_LIVE"

STRUCTURED_TAGGING_LINE = "Tag every name, measured value, change and date with its kind; the renderer styles them."
MARKDOWN_STYLING_LINE = (
    "Bold every event name, metric name, measured value and change. Italicize every date and time window."
)
MARKDOWN_OUTPUT_INSTRUCTIONS = """Return only the findings as a Markdown bullet list, one finding per "- " bullet, with no heading or other text.
- Use **double asterisks** for bold and _underscores_ for italic. Keep each styled span to the name, value, or time expression.
- Use [short label](url) for a page or referrer with a supplied URL, and keep the complete original URL.
- Keep inline code literal; do not style its contents.
Include the time window when describing a trend."""


def live_eval_enabled() -> bool:
    return os.environ.get(LIVE_EVAL_ENV_VAR, "").strip().lower() in {"1", "true", "yes"}


@cache
def _chart_images(case_name: str) -> dict[int, bytes]:
    import matplotlib  # noqa: PLC0415 - only live runs draw charts

    matplotlib.use("Agg")
    from matplotlib import pyplot  # noqa: PLC0415

    images: dict[int, bytes] = {}
    for insight_id, series_list in CASES_BY_NAME[case_name].chart_series.items():
        figure, axis = pyplot.subplots(figsize=(6, 3), dpi=80)
        for series in series_list:
            axis.plot(series["days"], series["data"], label=series["label"])
        axis.set_yscale("log")
        axis.set_xticks(axis.get_xticks()[::7])
        buffer = io.BytesIO()
        figure.savefig(buffer, format="png")
        pyplot.close(figure)
        images[insight_id] = buffer.getvalue()
    return images


def _markdown_messages(case: SummaryCase) -> list[dict]:
    messages = build_summary_messages(case.previous_states, case.current_states, case.subscription_title, team=None)
    system = messages[0]["content"]
    # Fail loudly when the production prompt changes, so the markdown arm never runs with a
    # half-replaced structured instruction.
    for production_text in (SUMMARY_OUTPUT_INSTRUCTIONS, STRUCTURED_TAGGING_LINE):
        if production_text not in system:
            raise ValueError(f"Production summary prompt no longer contains: {production_text[:60]}")
    system = system.replace(SUMMARY_OUTPUT_INSTRUCTIONS, MARKDOWN_OUTPUT_INSTRUCTIONS)
    messages[0]["content"] = system.replace(STRUCTURED_TAGGING_LINE, MARKDOWN_STYLING_LINE)
    _attach_images_to_user_message(messages, case.current_states, _chart_images(case.name) or None)
    return messages


def _direct_openai_client() -> OpenAI:
    # The gateway only proxies the request, so calling OpenAI directly returns the same model
    # output without a local gateway. OpenAI() reads OPENAI_API_KEY and OPENAI_BASE_URL itself.
    return OpenAI(max_retries=1)


def _live_structured(case: SummaryCase) -> str:
    summary = generate_report_summary(
        case.previous_states,
        case.current_states,
        case.subscription_title,
        team=None,
        insight_images=_chart_images(case.name) or None,
        client=_direct_openai_client(),
    )
    return summary.model_dump_json() if summary else ""


def _live_markdown(case: SummaryCase) -> str:
    return request_summary_completion(
        _markdown_messages(case),
        team=None,
        delivery_id=None,
        user_tag=summary_user_tag(0, None),
        response_format=None,
        client=_direct_openai_client(),
    )


async def run_case(case: SummaryCase, *, live: bool) -> dict:
    if live:
        structured_json, markdown = await asyncio.gather(
            asyncio.to_thread(_live_structured, case), asyncio.to_thread(_live_markdown, case)
        )
    else:
        structured_json, markdown = case.stub_structured_json(), case.stub_markdown

    summary = ReportSummary.model_validate_json(structured_json) if structured_json else None
    arms = render_arms(summary, markdown or None)
    return {
        "mode": "live" if live else "stub",
        "structured_json": structured_json,
        "markdown": markdown,
        "single_text_finding_rate": single_text_finding_rate(summary) if summary else None,
        "arms": arms,
        "input_values": extract_input_values(case.results_summaries),
        "input_names": case.names,
        "input_text": case.input_text,
        "last_message": "\n\n".join(f"[{arm}]\n{rendered}" for arm, rendered in arms.items()),
    }


async def eval_summary_styling(ctx: EvalContext) -> None:
    live = live_eval_enabled()

    async def task(case: BaseEvalCase, task_ctx: EvalContext) -> dict:
        return await run_case(CASES_BY_NAME[case.name], live=live)

    await OneShotEval(
        experiment_name="subscription-summary-styling",
        cases=[
            BaseEvalCase(
                name=case.name,
                prompt=case.description,
                metadata={"mode": "live" if live else "stub", "live_env_var": LIVE_EVAL_ENV_VAR},
            )
            for case in CASES
        ],
        scorers=all_scorers(),
        task=task,
        ctx=ctx,
        send_to_posthog=False,
    )
