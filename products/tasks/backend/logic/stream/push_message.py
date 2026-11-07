import re
import json
from typing import Self

from posthog.dataclasses import frozen

MAX_PUSH_MESSAGE_BYTES = 1000


def truncate_push_message(text: str) -> str:
    text = re.sub(r"[\ud800-\udfff]", "�", text)
    encoded = text.encode("utf-8")
    if len(encoded) <= MAX_PUSH_MESSAGE_BYTES:
        return text
    return encoded[: MAX_PUSH_MESSAGE_BYTES - 3].decode("utf-8", errors="ignore") + "…"


@frozen
class PushMessage:
    text: str = ""
    message_id: str | None = None
    finished: bool = False

    @classmethod
    def from_json(cls, value: str | bytes | None) -> Self:
        if value is None:
            return cls()
        data = json.loads(value)
        return cls(text=data["text"], message_id=data["message_id"], finished=data["finished"])

    def to_json(self) -> str:
        return json.dumps({"text": self.text, "message_id": self.message_id, "finished": self.finished})

    def update(self, event: dict[str, object]) -> Self | None:
        notification = event.get("notification")
        notification = notification if isinstance(notification, dict) else {}
        params = notification.get("params")
        params = params if isinstance(params, dict) else {}
        update = params.get("update")
        update = update if isinstance(update, dict) else {}
        kind = update.get("sessionUpdate")
        if event.get("type") == "pi_event":
            pi_event = event.get("event")
            update = pi_event if isinstance(pi_event, dict) else {}
            kind = update.get("type")

        meta = update.get("_meta")
        meta = meta if isinstance(meta, dict) else {}
        for metadata_key in ("posthog", "claudeCode"):
            agent_meta = meta.get(metadata_key)
            parent = agent_meta.get("parentToolCallId") if isinstance(agent_meta, dict) else None
            if isinstance(parent, str) and parent:
                return None

        kind = kind if isinstance(kind, str) else None
        result = notification.get("result")
        result = result if isinstance(result, dict) else {}
        if (
            kind == "turn_completed"
            or notification.get("method") == "_posthog/turn_complete"
            or result.get("stopReason") == "end_turn"
        ):
            return type(self)(text=self.text, message_id=self.message_id, finished=True)
        if notification.get("method") == "_posthog/user_message" or kind in {
            "user_message",
            "user_message_chunk",
            "tool_call",
            "tool_call_started",
        }:
            return type(self)()
        if kind not in {"agent_message", "agent_message_chunk", "assistant_message_chunk"}:
            return None

        content = update.get("content")
        if not isinstance(content, dict) or content.get("type") != "text" or not isinstance(content.get("text"), str):
            return None
        message_id = update.get("messageId")
        message_id = message_id if isinstance(message_id, str) else None
        replace = kind == "agent_message" or self.finished or (message_id is not None and message_id != self.message_id)
        text = ("" if replace else self.text) + content["text"]
        return type(self)(text=truncate_push_message(text), message_id=message_id)
