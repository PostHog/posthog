import json
import base64
import binascii
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import responses

EXPORT_PATH = "/v2/export/html"


def unlayer_document(body: str) -> str:
    return f"<!DOCTYPE html><html><head></head><body>{body}</body></html>"


class FakeUnlayerExportAPI:
    def __init__(self, base_url: str, api_key: str) -> None:
        self.base_url = base_url
        self.api_key = api_key

    @contextmanager
    def installed(self) -> Iterator["FakeUnlayerExportAPI"]:
        with responses.RequestsMock(assert_all_requests_are_fired=False) as http:
            http.add_callback(responses.POST, f"{self.base_url}{EXPORT_PATH}", callback=self._export)
            yield self

    def _export(self, request: Any) -> tuple[int, dict[str, str], str]:
        if _basic_credentials(request.headers.get("Authorization", "")) != (self.api_key, ""):
            return 401, {}, json.dumps({"success": False, "errors": ["Unauthorized"]})
        payload = json.loads(request.body)
        design = payload.get("design")
        if payload.get("displayMode") != "email" or not isinstance(design, dict) or "body" not in design:
            return 400, {}, json.dumps({"success": False, "errors": ["Invalid design"]})
        body = design["body"]
        rows = body.get("headers", []) + body.get("rows", []) + body.get("footers", [])
        blocks = [
            _block(content)
            for row in rows
            for column in row.get("columns", [])
            for content in column.get("contents", [])
        ]
        return 200, {}, json.dumps({"success": True, "data": {"html": unlayer_document("".join(blocks))}})


def _block(content: dict[str, Any]) -> str:
    values = content.get("values") or {}
    if content.get("type") == "text":
        return values.get("text", "")
    if content.get("type") == "html":
        return values.get("html", "")
    return "<div>Missing</div>"


def _basic_credentials(authorization: str) -> tuple[str, str] | None:
    scheme, _, token = authorization.partition(" ")
    if scheme != "Basic":
        return None
    try:
        user, _, password = base64.b64decode(token, validate=True).decode().partition(":")
    except (binascii.Error, UnicodeDecodeError):
        return None
    return user, password
