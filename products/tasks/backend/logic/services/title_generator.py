import logging

logger = logging.getLogger(__name__)

TITLE_DISTINCT_ID = "task-title-generator"
TITLE_AI_PRODUCT = "tasks_title"
TITLE_MODEL = "claude-haiku-4-5-20251001"
TITLE_TEMPERATURE = 0.2  # Slightly lower for more consistent output
TITLE_MAX_TOKENS = 50  # Reduced since we want short titles
TITLE_GATEWAY_TIMEOUT_SECONDS = 30.0
TITLE_GATEWAY_MAX_RETRIES = 1


def generate_task_title(description: str) -> str:
    """
    Generate a concise task title from a description using Claude Haiku.

    Returns a generated title or falls back to truncated description if generation fails.
    """
    # Deferred: the llm client pulls google.genai (Gemini SDK), and this module is reachable from a
    # tasks serializer that the file-system registrations import at AppConfig.ready() — a module-level
    # import here would drag the SDK onto the django.setup() path that every process pays for.
    from posthog.llm.gateway_client import build_ai_gateway_anthropic_client  # noqa: PLC0415

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
        client = build_ai_gateway_anthropic_client(ai_product=TITLE_AI_PRODUCT, distinct_id=TITLE_DISTINCT_ID)
        with client.with_options(
            timeout=TITLE_GATEWAY_TIMEOUT_SECONDS, max_retries=TITLE_GATEWAY_MAX_RETRIES
        ) as gateway:
            response = gateway.messages.create(
                model=TITLE_MODEL,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
                temperature=TITLE_TEMPERATURE,
                max_tokens=TITLE_MAX_TOKENS,
                extra_headers={"X-PostHog-Billable": "false"},
            )
        response_text = "".join(block.text for block in response.content if block.type == "text")

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
        return first_line or "Untitled Task"

    return first_line[:57] + "..."
