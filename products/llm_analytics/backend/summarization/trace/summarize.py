"""
Trace summarization function.

Generates AI-powered summaries of full LLM traces using text representation.
"""

from typing import Any

from ..llm.call import call_summarization_llm
from ..utils import load_summarization_template


async def summarize_trace(
    trace: dict[str, Any], hierarchy: list[dict[str, Any]], text_repr: str, mode: str = "minimal"
) -> str:
    """
    Generate a summary of a trace using LLM.

    Args:
        trace: Trace metadata dictionary
        hierarchy: Hierarchical event structure
        text_repr: Full line-numbered text representation of the trace
        mode: Summary detail level ('minimal' or 'detailed')

    Returns:
        Summary text with line references
    """
    # Load prompt templates with mode variable
    system_prompt = load_summarization_template(
        "prompts/trace/system-prompt-base.djt",
        {"mode": mode},
    )

    user_prompt = load_summarization_template(
        "prompts/trace/user-prompt.djt",
        {
            "trace_name": trace.get("properties", {}).get("$ai_span_name", "Trace"),
            "text_repr": text_repr,
        },
    )

    # Call LLM for summary
    summary = await call_summarization_llm(system_prompt, user_prompt)

    return summary
