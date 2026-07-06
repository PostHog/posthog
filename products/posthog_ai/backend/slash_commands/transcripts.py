import json
from typing import TYPE_CHECKING, Any

from posthog.storage import object_storage

from products.posthog_ai.backend.slash_commands.base import TranscriptMessage

if TYPE_CHECKING:
    from products.tasks.backend.models import TaskRun

_CONTEXT_OPEN_TAG = "<posthog_context>"
_CONTEXT_CLOSE_TAG = "</posthog_context>"


def _strip_context_wrapper(content: str) -> str:
    """Mirror of the frontend `unwrapUserMessageContent`: drop the `<posthog_context>…</posthog_context>`
    block the backend prepends when attachments are present, leaving the raw text the user typed."""
    if content.startswith(_CONTEXT_OPEN_TAG):
        close_idx = content.find(_CONTEXT_CLOSE_TAG)
        if close_idx != -1:
            return content[close_idx + len(_CONTEXT_CLOSE_TAG) :].lstrip("\n")
    return content


def _extract_text(content: Any) -> str:
    """Pull rendered text out of a wire `content` field — a plain string, or ACP content blocks
    (`[{ type: 'text', text }]`)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict):
                text = block.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "".join(parts)
    return ""


class RunLogTranscriptSource:
    """Reconstructs the neutral conversation transcript from a Run's persisted ACP log, walking the
    whole resume chain so a summarizer sees the full history across resumed runs.

    Reads raw notification bodies rather than requiring the stream envelope, so both agent-server
    frames (`type: notification`) and directly-seeded `{notification}` entries are handled.
    """

    def __init__(self, run: "TaskRun") -> None:
        self._run = run

    async def fetch(self) -> list[TranscriptMessage]:
        messages: list[TranscriptMessage] = []
        for chain_run in self._run.get_resume_chain():
            log_content = object_storage.read(chain_run.log_url, missing_ok=True) or ""
            for raw_line in log_content.splitlines():
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(data, dict):
                    continue
                notification = data.get("notification")
                if not isinstance(notification, dict):
                    continue
                method = notification.get("method")
                params = notification.get("params")
                params = params if isinstance(params, dict) else {}

                if method == "_posthog/user_message":
                    text = _strip_context_wrapper(_extract_text(params.get("content")))
                    if text:
                        messages.append(TranscriptMessage(role="user", content=text))
                    continue

                if method == "session/update":
                    update = params.get("update")
                    update = update if isinstance(update, dict) else {}
                    # The persisted log keeps only finalized `agent_message` updates — chunks are
                    # dropped on write (`TaskRun._is_agent_message_chunk`).
                    if update.get("sessionUpdate") == "agent_message":
                        content = update.get("content")
                        text = content.get("text") if isinstance(content, dict) else update.get("text")
                        if isinstance(text, str) and text:
                            messages.append(TranscriptMessage(role="assistant", content=text))
        return messages
