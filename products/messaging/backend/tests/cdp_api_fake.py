import re
import json
from typing import Any
from uuid import UUID

import requests

from posthog.dataclasses import frozen
from posthog.uuidt import UUIDT

from products.messaging.backend.models.message_preferences import MessageRecipientPreference
from products.workflows.backend.facade.models import HogFlow

# The schemas the CDP API parses a send with, in nodejs/src/cdp/services/hogflows/transactional-email.ts.
# A field that Django sends and the CDP does not know is refused here, as the CDP's strict schema refuses it.
_CATEGORY = {"id": None, "type": None}
_SEND = {
    "content": {"subject": None, "html": None, "text": None},
    "from": {"integrationId": None, "email": None, "name": None},
    "replyTo": None,
    "cc": None,
    "bcc": None,
    "tracking": {"captureEngagement": None},
    "messageCategory": _CATEGORY,
}
_TEMPLATE_SEND = {
    "to": None,
    "distinct_id": None,
    "variables": None,
    "idempotency_key": None,
    "message_category": _CATEGORY,
}
_CODE_SEND = {**_TEMPLATE_SEND, "send": _SEND}

_ROUTE = re.compile(
    r"/api/projects/(?P<team_id>\d+)/hog_flows/(?P<hog_flow_id>[^/]+)/transactional_email(?P<code>/send)?$"
)
_GUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
# JavaScript's \s, which the CDP's patterns use. Python's \s also matches characters such as U+0085.
_JS_SPACE = "[\t\n\v\f\r    -     　﻿]"
_CODE_SEND_UNSUBSCRIBE_PLACEHOLDER = re.compile(rf"\{{\{{{_JS_SPACE}*unsubscribe_url{_JS_SPACE}*\}}\}}")
_LIQUID_UNSUBSCRIBE_LINK = re.compile(
    rf"\{{\{{-?{_JS_SPACE}*unsubscribe_url(_one_click)?{_JS_SPACE}*-?\}}\}}|\{{%-?{_JS_SPACE}*unsubscribe_url{_JS_SPACE}*-?%\}}"
)


@frozen
class QueuedSend:
    hog_flow_id: UUID
    to: str
    category: dict[str, str] | None
    marketing: bool
    content: dict[str, str] | None


class CdpApi:
    def __init__(self) -> None:
        self.queued: list[QueuedSend] = []

    def post(self, url: str, **request: Any) -> requests.Response:
        route = _ROUTE.search(url)
        if route is None:
            return _reply(404, {"error": "Not found"})
        body = request["json"] if "json" in request else json.loads(request["data"])
        issues = _issues(body, _CODE_SEND if route["code"] else _TEMPLATE_SEND, [])
        if issues:
            return _reply(400, {"error": json.dumps(issues)})

        hog_flow = HogFlow.objects.filter(team_id=int(route["team_id"]), id=route["hog_flow_id"]).first()
        if hog_flow is None:
            return _reply(404, {"error": "Workflow not found"})
        send = body.get("send")
        category = (send or {}).get("messageCategory") or body.get("message_category")
        if (hog_flow.trigger or {}).get("type") != "api":
            return _reply(400, {"error": "not_sendable"})

        marketing_step = _marketing_email_step(hog_flow.actions, category)
        recipients = [body["to"], *((send or {}).get("cc") or []), *((send or {}).get("bcc") or [])]
        refusal = (marketing_step and _marketing_send_refusal(marketing_step, send)) or _refusal(
            hog_flow, recipients, marketing_step
        )
        if refusal:
            status_code = 400 if refusal in ("unsubscribe_link_required", "copies_not_allowed", "not_sendable") else 422
            return _reply(status_code, {"error": refusal})

        invocation_id = str(UUIDT())
        self.queued.append(
            QueuedSend(
                hog_flow_id=hog_flow.id,
                to=body["to"],
                category=category,
                marketing=marketing_step is not None,
                content=(send or {}).get("content"),
            )
        )
        return _reply(202, {"status": "queued", "invocation_id": invocation_id, "replayed": False})


def _issues(value: Any, fields: dict[str, Any], path: list[str]) -> list[dict[str, Any]]:
    if not isinstance(value, dict):
        return [{"code": "invalid_type", "expected": "object", "path": path}]
    unknown = [key for key in value if key not in fields]
    issues: list[dict[str, Any]] = [{"code": "unrecognized_keys", "keys": unknown, "path": path}] if unknown else []
    for key, nested in fields.items():
        if nested is not None and value.get(key) is not None:
            issues += _issues(value[key], nested, [*path, key])
    if fields is _CATEGORY:
        if not _GUID.match(str(value.get("id", ""))):
            issues.append({"code": "invalid_format", "format": "guid", "path": [*path, "id"]})
        if value.get("type") not in ("marketing", "transactional"):
            issues.append({"code": "invalid_value", "path": [*path, "type"]})
    if fields is _SEND and not isinstance(value.get("tracking"), dict):
        issues.append({"code": "invalid_type", "expected": "object", "path": [*path, "tracking"]})
    if fields in (_TEMPLATE_SEND, _CODE_SEND):
        for required in ("to", "distinct_id"):
            if not value.get(required):
                issues.append({"code": "invalid_type", "expected": "string", "path": [required]})
    return issues


def _marketing_email_step(actions: Any, category: dict[str, str] | None) -> dict[str, Any] | None:
    for action in actions if isinstance(actions, list) else []:
        if action.get("type") != "function_email":
            continue
        config = dict(action.get("config") or {})
        if category:
            config.update(message_category_type=category["type"], message_category_id=category["id"])
        if config.get("message_category_type") != "transactional":
            return config
    return None


def _marketing_send_refusal(step: dict[str, Any], send: dict[str, Any] | None) -> str | None:
    email = ((step.get("inputs") or {}).get("email") or {}).get("value") or {}
    content = (send or {}).get("content")
    if content:
        has_link = bool(_CODE_SEND_UNSUBSCRIBE_PLACEHOLDER.search(content.get("html") or content.get("text") or ""))
    else:
        has_link = bool(_LIQUID_UNSUBSCRIBE_LINK.search(email.get("html") or email.get("text") or ""))
    if not has_link:
        return "unsubscribe_link_required"
    copies = [(send or {}).get("cc", email.get("cc")), (send or {}).get("bcc", email.get("bcc"))]
    if any(copy if isinstance(copy, list) else isinstance(copy, str) and copy.strip() for copy in copies):
        return "copies_not_allowed"
    return None


def _refusal(hog_flow: HogFlow, recipients: list[str], marketing_step: dict[str, Any] | None) -> str | None:
    if hog_flow.status != "active":
        return "not_sendable"
    if hog_flow.email_sending_paused_at:
        return "sending_paused"
    if marketing_step is not None:
        category_id = marketing_step.get("message_category_id") or "$all"
        if any(_opted_out(hog_flow.team_id, recipient, category_id) for recipient in recipients):
            return "recipient_opted_out"
    return None


def _opted_out(team_id: int, identifier: str, category_id: str) -> bool:
    recipient = MessageRecipientPreference.objects.filter(team_id=team_id, identifier=identifier).first()
    if recipient is None:
        return False
    preferences = recipient.preferences or {}
    return "OPTED_OUT" in (preferences.get(category_id), preferences.get("$all"))


def _reply(status_code: int, body: dict[str, Any]) -> requests.Response:
    response = requests.Response()
    response.status_code = status_code
    response._content = json.dumps(body).encode()
    return response
