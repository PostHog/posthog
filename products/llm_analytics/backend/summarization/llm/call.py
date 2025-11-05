"""
LLM calling function for summarization.

Reuses PostHog's existing LLM infrastructure from session_summaries.
"""

from ee.hogai.session_summaries.llm.call import get_async_openai_client

from ..constants import SUMMARIZATION_MODEL, SUMMARIZATION_TEMPERATURE, SUMMARIZATION_TIMEOUT


async def call_summarization_llm(system_prompt: str, user_prompt: str) -> str:
    """
    Call LLM for summarization with configured parameters.

    Args:
        system_prompt: System instructions for the LLM
        user_prompt: User prompt with content to summarize

    Returns:
        Summary text from the LLM
    """
    client = get_async_openai_client()

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    # Non-streaming call for simplicity
    response = await client.chat.completions.create(
        model=SUMMARIZATION_MODEL,
        messages=messages,
        temperature=SUMMARIZATION_TEMPERATURE,
        timeout=SUMMARIZATION_TIMEOUT,
    )

    return response.choices[0].message.content or ""
