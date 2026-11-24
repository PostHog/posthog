import json
import hashlib
from collections.abc import Mapping
from typing import Any

from products.messaging.backend.models.message_template import MessageTemplate


def _text(value: Any) -> str:
    return "" if value is None else str(value)


def push_digest(template: MessageTemplate) -> str:
    """Hash of everything a person confirms about a push template. The MCP server computes the same one from the
    template it shows, in services/mcp/src/lib/push-digest.ts, so both must change together."""
    push = (template.content or {}).get("push")
    push = push if isinstance(push, Mapping) else {}
    data = push.get("data")
    entries = [[str(key), None if value is None else str(value)] for key, value in (data or {}).items()]
    confirmed = [
        "push-1",
        str(template.id),
        _text(template.name),
        _text(template.type),
        bool(template.sensitive),
        _text(push.get("title")),
        _text(push.get("body")),
        _text(push.get("link")),
        _text(push.get("image")),
        # By bytes, because the two languages order other strings differently.
        sorted(entries, key=lambda entry: entry[0].encode(errors="surrogatepass")),
        [str(channel) for channel in push.get("channels") or []],
        _text(template.transactional_hog_flow_id),
    ]
    encoded = json.dumps(confirmed, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(encoded.encode(errors="backslashreplace")).hexdigest()
