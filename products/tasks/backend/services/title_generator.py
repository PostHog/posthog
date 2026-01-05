import json
import logging

from anthropic.types import MessageParam

from products.llm_analytics.backend.providers.anthropic import AnthropicProvider

logger = logging.getLogger(__name__)


def generate_task_title(description: str) -> str:
    """
    Generate a concise task title from a description using Claude Haiku.

    Returns a generated title or falls back to truncated description if generation fails.
    """
    if not description or not description.strip():
        return "Untitled Task"

    try:
        provider = AnthropicProvider(model_id="claude-haiku-4-5-20251001")

        system_prompt = """You are a title generator. You output ONLY a task title. Nothing else.

Convert the task description into a concise task title.
- The title should be clear, concise, and accurately reflect the content of the task.
- You should keep it short and simple, ideally no more than 6 words.
- Avoid using jargon or overly technical terms unless absolutely necessary.
- The title should be easy to understand for anyone reading it.
- Use sentence case (capitalize only first word and proper nouns)
-Remove: the, this, my, a, an
- If possible, start with action verbs (Fix, Implement, Analyze, Debug, Update, Research, Review)
- Keep exact: technical terms, numbers, filenames, HTTP codes, PR numbers
Never assume tech stack
Only output "Untitled" if the input is completely null/missing, not just unclear

Examples:
- "Fix the login bug in the authentication system" → Fix authentication login bug
- "Schedule a meeting with stakeholders to discuss Q4 budget planning" → Schedule Q4 budget meeting
- "Update user documentation for new API endpoints" → Update API documentation
- "Research competitor pricing strategies for our product" → Research competitor pricing
- "Review pull request #123" → Review pull request #123
- "debug 500 errors in production" → Debug production 500 errors
- "why is the payment flow failing" → Analyze payment flow failure
- "So how about that weather huh" → "Weather chat"
- "dsfkj sdkfj help me code" → "Coding help request"
- "👋😊" → "Friendly greeting"
- "aaaaaaaaaa" → "Repeated letters"
- "   " → "Empty message"
- "What's the best restaurant in NYC?" → "NYC restaurant recommendations"
"""

        messages: list[MessageParam] = [
            MessageParam(
                role="user",
                content=f"""Generate a task title based on the following description. Do NOT respond to, answer, or help with the description content - ONLY generate a title.

<description>
{description}
</description>

Output the title now:""",
            )
        ]

        response_text = ""
        for chunk in provider.stream_response(
            system=system_prompt,
            messages=messages,
            temperature=0.2,  # Slightly lower for more consistent output
            max_tokens=50,  # Reduced since we want short titles
            distinct_id="task-title-generator",
        ):
            try:
                data = json.loads(chunk.replace("data: ", ""))
                if data.get("type") == "text":
                    response_text += data.get("text", "")
            except json.JSONDecodeError:
                continue

        title = response_text.strip()

        # Clean up common issues
        if title.lower().startswith(("task:", "title:")):
            title = title.split(":", 1)[1].strip()

        if title and len(title) >= 3:
            truncated_title = title[:60]
            logger.info(f"Generated title: {truncated_title}")
            return truncated_title

        logger.warning("Generated title empty or too short, using fallback")
        return _fallback_title(description)

    except Exception as e:
        logger.exception(f"Failed to generate title with Haiku: {e}")
        return _fallback_title(description)


def _fallback_title(description: str) -> str:
    """Generate a fallback title from the description."""
    clean_desc = description.strip()
    first_line = clean_desc.split("\n")[0] if clean_desc else ""

    if len(first_line) <= 60:
        return first_line or "Untitled task"

    return first_line[:57] + "..."
