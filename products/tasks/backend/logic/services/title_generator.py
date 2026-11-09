import logging
from typing import Any
from uuid import uuid4

from posthog.ph_client import feature_enabled_or_false

from products.tasks.backend.constants import TASK_TITLE_AI_GATEWAY_FEATURE_FLAG

logger = logging.getLogger(__name__)

TITLE_DISTINCT_ID = "task-title-generator"
TITLE_MODEL = "claude-haiku-4-5-20251001"
TITLE_TEMPERATURE = 0.2  # Slightly lower for more consistent output
TITLE_MAX_TOKENS = 50  # Reduced since we want short titles
TITLE_GATEWAY_TIMEOUT_SECONDS = 30.0
TITLE_GATEWAY_MAX_RETRIES = 1


def generate_task_title(description: str, *, distinct_id: str | None = None) -> str:
    """
    Generate a concise task title from a description using Claude Haiku.

    Returns a generated title or falls back to truncated description if generation fails.
    """
    # Deferred: the llm client pulls google.genai (Gemini SDK), and this module is reachable from a
    # tasks serializer that the file-system registrations import at AppConfig.ready() — a module-level
    # import here would drag the SDK onto the django.setup() path that every process pays for.
    from products.ai_observability.backend.llm.client import Client  # noqa: PLC0415
    from products.ai_observability.backend.llm.types import CompletionRequest  # noqa: PLC0415

    if not description or not description.strip():
        return "Untitled Task"

    try:
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
- Never assume tech stack
- Only output "Untitled" if the input is completely null/missing, not just unclear

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

        user_prompt = f"""Generate a task title based on the following description. Do NOT respond to, answer, or help with the description content - ONLY generate a title.

<description>
{description}
</description>

Output the title now:"""
        messages: list[dict[str, Any]] = [{"role": "user", "content": user_prompt}]

        if _title_via_ai_gateway(distinct_id):
            response_text = _complete_via_ai_gateway(system_prompt, user_prompt)
        else:
            client = Client(distinct_id=TITLE_DISTINCT_ID)
            request = CompletionRequest(
                model=TITLE_MODEL,
                messages=messages,
                provider="anthropic",
                system=system_prompt,
                temperature=TITLE_TEMPERATURE,
                max_tokens=TITLE_MAX_TOKENS,
            )
            response_text = ""
            for chunk in client.stream(request):
                if chunk.type == "text":
                    response_text += chunk.data.get("text", "")

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


def _title_via_ai_gateway(distinct_id: str | None) -> bool:
    from posthog.llm.gateway_client import resolve_ai_gateway_config  # noqa: PLC0415

    if resolve_ai_gateway_config() is None:
        return False
    return feature_enabled_or_false(
        TASK_TITLE_AI_GATEWAY_FEATURE_FLAG,
        distinct_id or str(uuid4()),
        only_evaluate_locally=False,
        send_feature_flag_events=False,
    )


def _complete_via_ai_gateway(system_prompt: str, user_prompt: str) -> str:
    from posthog.llm.gateway_client import build_ai_gateway_anthropic_client  # noqa: PLC0415

    client = build_ai_gateway_anthropic_client(ai_product="posthog_code", distinct_id=TITLE_DISTINCT_ID)
    with client.with_options(timeout=TITLE_GATEWAY_TIMEOUT_SECONDS, max_retries=TITLE_GATEWAY_MAX_RETRIES) as gateway:
        response = gateway.messages.create(
            model=TITLE_MODEL,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
            temperature=TITLE_TEMPERATURE,
            max_tokens=TITLE_MAX_TOKENS,
            extra_headers={"X-PostHog-Billable": "false", "X-PostHog-Privacy-Mode": "true"},
        )
    return "".join(block.text for block in response.content if block.type == "text")


def _fallback_title(description: str) -> str:
    """Generate a fallback title from the description."""
    clean_desc = description.strip()
    first_line = clean_desc.split("\n")[0] if clean_desc else ""

    if len(first_line) <= 60:
        return first_line or "Untitled Task"

    return first_line[:57] + "..."
