"""
Event summarization function.

Generates AI-powered summaries of individual events (generations, spans, embeddings).
"""

from typing import Any

from ..llm.call import call_summarization_llm
from ..utils import load_summarization_template


async def summarize_event(event: dict[str, Any], text_repr: str, mode: str = "detailed") -> str:
    """
    Generate a summary of an event using LLM.

    Args:
        event: Event dictionary with properties
        text_repr: Full line-numbered text representation of the event
        mode: Summary detail level ('minimal' or 'detailed')

    Returns:
        Summary text with line references
    """
    # Determine event type for context
    event_type = event.get("event", "unknown")
    event_name = event.get("properties", {}).get("$ai_span_name", event_type)

    # Choose template based on mode
    template_prefix = "minimal" if mode == "minimal" else "detailed"

    # Load prompt templates
    system_prompt = load_summarization_template(
        f"event/templates/{template_prefix}-system-prompt.djt",
        {},
    )

    user_prompt = load_summarization_template(
        "event/templates/user-prompt.djt",
        {
            "event_type": event_type,
            "event_name": event_name,
            "text_repr": text_repr,
        },
    )

    # Call LLM for summary
    summary = await call_summarization_llm(system_prompt, user_prompt)

    return summary
