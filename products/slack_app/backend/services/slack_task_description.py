"""The shape of a Slack task's description, shared by the code that writes it and the code that reads it.

``task_creation._build_posthog_code_task_description`` writes the surrounding thread as a delimited
context block, then the requester's own message after the closing tag. Messages inside the block can
come from anyone in the thread, so a reader that wants only the requester's words takes what follows
that tag, never what is inside it.
"""

THREAD_CONTEXT_TAG = "slack_thread_context"
FALLBACK_TASK_PROMPT = "Task from Slack"

_CONTEXT_BLOCK_END = f"</{THREAD_CONTEXT_TAG}>\n\n"


def request_from_task_description(description: str) -> str | None:
    """The requester's own message in a Slack task description, or None when it cannot be isolated.

    A thread message has the context tags stripped before it goes into the block, so the last closing
    tag is the builder's own and everything after it is the requester's prompt. When the mention carried
    no text, the prompt is a placeholder and the request is inside the block, so this returns None.
    """
    _, _, prompt = description.rpartition(_CONTEXT_BLOCK_END)
    prompt = prompt.strip()
    if not prompt or prompt == FALLBACK_TASK_PROMPT:
        return None
    return prompt
