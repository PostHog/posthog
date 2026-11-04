"""A local capture endpoint for the eval AI gateway's `$ai_generation` events.

Without a capture URL the gateway only logs a summary of each generation, which leaves out the
served service tier, cache and reasoning tokens, and per-part costs. Pointing it here keeps the
full property set for each eval run in one JSONL file. Prompt and completion bodies are dropped:
the agent log already holds the conversation.
"""

from __future__ import annotations

import json
import logging
import threading
from email.parser import BytesParser
from email.policy import HTTP
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

CAPTURE_AI_PATH = "/i/v0/ai"

_DROPPED_PROPERTIES = frozenset({"$ai_input", "$ai_output", "$ai_output_choices", "$ai_tools"})


def parse_generation(content_type: str, body: bytes) -> dict[str, Any] | None:
    """Read the gateway's multipart `event` and `event.properties` parts into one record."""
    message = BytesParser(policy=HTTP).parsebytes(f"Content-Type: {content_type}\r\n\r\n".encode() + body)
    if not message.is_multipart():
        return None
    parts: dict[str, Any] = {}
    for part in message.iter_parts():
        name = part.get_param("name", header="content-disposition")
        payload = part.get_payload(decode=True)
        if isinstance(name, str) and isinstance(payload, bytes):
            parts[name] = json.loads(payload)
    event = parts.get("event")
    properties = parts.get("event.properties")
    if not isinstance(event, dict) or not isinstance(properties, dict):
        return None
    return {
        **event,
        "properties": {key: value for key, value in properties.items() if key not in _DROPPED_PROPERTIES},
    }


class GenerationCapture:
    """Accepts capture POSTs on localhost and appends each generation to `path`."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()
        capture = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                record = None
                if self.path.split("?", 1)[0] == CAPTURE_AI_PATH:
                    try:
                        record = parse_generation(self.headers.get("Content-Type", ""), body)
                    except (ValueError, UnicodeDecodeError):
                        logger.warning("Could not parse a gateway generation event", exc_info=True)
                if record is not None:
                    capture.append(record)
                self.send_response(200 if record is not None else 400)
                self.end_headers()

            def log_message(self, format: str, *args: Any) -> None:
                return

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, name="ai-gateway-capture", daemon=True)

    @property
    def url(self) -> str:
        host, port = self._server.server_address[:2]
        return f"http://{host!s}:{port}"

    def append(self, record: dict[str, Any]) -> None:
        line = json.dumps(record, separators=(",", ":"), default=str)
        with self._lock, self.path.open("a", encoding="utf-8") as file:
            file.write(line + "\n")

    def start(self) -> GenerationCapture:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch()
        self._thread.start()
        return self

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()
