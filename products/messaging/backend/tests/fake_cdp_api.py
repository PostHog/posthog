import re
import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import requests

from posthog.dataclasses import frozen

# A copy of the request schemas in nodejs/src/cdp/services/hogflows/transactional-email.ts. Like the zod
# schemas there, the code-send `send` object and every object in it refuse a key they don't name.
RECIPIENT_ADDRESS_PATTERN = re.compile(
    r"^[a-zA-Z0-9!#$%&'*+/=?^_`{|}~-]+(?:\.[a-zA-Z0-9!#$%&'*+/=?^_`{|}~-]+)*"
    r"@[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)+$"
)

Issues = list[dict[str, Any]]
Check = Callable[[Any, list[Any]], Issues]


def _issue(code: str, path: list[Any], **extra: Any) -> dict[str, Any]:
    return {"code": code, "path": path, "message": code, **extra}


def _string(min_length: int = 0, max_length: int | None = None) -> Check:
    def check(value: Any, path: list[Any]) -> Issues:
        if not isinstance(value, str):
            return [_issue("invalid_type", path)]
        if len(value) < min_length:
            return [_issue("too_small", path)]
        if max_length is not None and len(value) > max_length:
            return [_issue("too_big", path)]
        return []

    return check


def _email(value: Any, path: list[Any]) -> Issues:
    if not isinstance(value, str):
        return [_issue("invalid_type", path)]
    return [] if RECIPIENT_ADDRESS_PATTERN.match(value) else [_issue("invalid_format", path)]


def _boolean(value: Any, path: list[Any]) -> Issues:
    return [] if isinstance(value, bool) else [_issue("invalid_type", path)]


def _integer(value: Any, path: list[Any]) -> Issues:
    return [] if isinstance(value, int) and not isinstance(value, bool) else [_issue("invalid_type", path)]


def _literal(expected: Any) -> Check:
    def check(value: Any, path: list[Any]) -> Issues:
        return [] if value is expected else [_issue("invalid_value", path)]

    return check


def _record(value: Any, path: list[Any]) -> Issues:
    return [] if isinstance(value, dict) else [_issue("invalid_type", path)]


def _array(item: Check, max_items: int | None = None) -> Check:
    def check(value: Any, path: list[Any]) -> Issues:
        if not isinstance(value, list):
            return [_issue("invalid_type", path)]
        if max_items is not None and len(value) > max_items:
            return [_issue("too_big", path)]
        return [issue for index, entry in enumerate(value) for issue in item(entry, [*path, index])]

    return check


@dataclass(frozen=True)
class _Key:
    check: Check
    optional: bool = False


def _object(
    keys: dict[str, _Key], *, strict: bool, refine: Callable[[dict[str, Any], list[Any]], Issues] | None = None
) -> Check:
    def check(value: Any, path: list[Any]) -> Issues:
        if not isinstance(value, dict):
            return [_issue("invalid_type", path)]
        issues: Issues = []
        for name, key in keys.items():
            if name in value:
                issues += key.check(value[name], [*path, name])
            elif not key.optional:
                issues.append(_issue("invalid_type", [*path, name]))
        unknown = [name for name in value if name not in keys]
        if strict and unknown:
            issues.append(_issue("unrecognized_keys", path, keys=unknown))
        if not issues and refine is not None:
            issues += refine(value, path)
        return issues

    return check


def _content_needs_a_body(content: dict[str, Any], path: list[Any]) -> Issues:
    return [] if content.get("html") or content.get("text") else [_issue("custom", path)]


def _clicks_need_opens(tracking: dict[str, Any], path: list[Any]) -> Issues:
    return [_issue("custom", path)] if tracking.get("opens") is False and tracking.get("clicks") is True else []


def _accepted_send(tracking: Check) -> Check:
    copies = _Key(_array(_email, max_items=10), optional=True)
    return _object(
        {
            "content": _Key(
                _object(
                    {
                        "subject": _Key(_string(min_length=1)),
                        "html": _Key(_string(), optional=True),
                        "text": _Key(_string(), optional=True),
                    },
                    strict=True,
                    refine=_content_needs_a_body,
                ),
                optional=True,
            ),
            "from": _Key(
                _object(
                    {
                        "integrationId": _Key(_integer),
                        "email": _Key(_string(), optional=True),
                        "name": _Key(_string(), optional=True),
                    },
                    strict=True,
                ),
                optional=True,
            ),
            "replyTo": _Key(_array(_string()), optional=True),
            "cc": copies,
            "bcc": copies,
            "tracking": _Key(tracking),
        },
        strict=True,
    )


# The pipeline before the code-send tracking contract: it takes only `captureEngagement`.
TRACKING_BEFORE_THE_CONTRACT = _object({"captureEngagement": _Key(_boolean)}, strict=True)
TRACKING = _object(
    {
        "captureEngagement": _Key(_boolean),
        "opens": _Key(_literal(False), optional=True),
        "clicks": _Key(_literal(True), optional=True),
    },
    strict=True,
    refine=_clicks_need_opens,
)

_TEMPLATE_REQUEST_KEYS = {
    "to": _Key(_email),
    "distinct_id": _Key(_string(min_length=1)),
    "variables": _Key(_record, optional=True),
    "idempotency_key": _Key(_string(min_length=1, max_length=255), optional=True),
}


def _is_recipient_format_issue(issue: dict[str, Any]) -> bool:
    path = issue["path"]
    return issue["code"] == "invalid_format" and (
        path[:1] == ["to"] or (path[:1] == ["send"] and path[1:2] in (["cc"], ["bcc"]))
    )


@frozen
class FakeCdpApi:
    """Stands in for cdp-api's transactional email routes: it validates a request as those routes do and
    queues what it accepts."""

    tracking: Check = TRACKING
    queued: list[dict[str, Any]] = field(default_factory=list)

    @property
    def queued_sends(self) -> list[dict[str, Any]]:
        return [request["send"] for request in self.queued if "send" in request]

    def post(self, url: str, *, data: Any = None, json: Any = None, **_kwargs: Any) -> requests.Response:
        request = json if json is not None else _json_loads(data)
        is_code_send = url.endswith("/transactional_email/send")
        keys = {**_TEMPLATE_REQUEST_KEYS, **({"send": _Key(_accepted_send(self.tracking))} if is_code_send else {})}
        issues = _object(keys, strict=False)(request, [])
        if issues and all(_is_recipient_format_issue(issue) for issue in issues):
            return _response(422, {"error": "recipient_unreachable"})
        if issues:
            return _response(400, {"error": _json_dumps(issues)})
        self.queued.append({name: value for name, value in request.items() if name in keys})
        return _response(202, {"invocation_id": str(uuid.uuid4())})


@frozen
class FakeAnalytics:
    """Stands in for `posthoganalytics.capture` and keeps the events it was given."""

    events: list[dict[str, Any]] = field(default_factory=list)

    def capture(self, **event: Any) -> str:
        self.events.append(event)
        return str(uuid.uuid4())

    def properties_of(self, name: str) -> list[dict[str, Any]]:
        return [event["properties"] for event in self.events if event.get("event") == name]


def _json_loads(data: bytes | str) -> Any:
    return json.loads(data)


def _json_dumps(value: Any) -> str:
    return json.dumps(value)


def _response(status_code: int, body: dict[str, Any]) -> requests.Response:
    response = requests.Response()
    response.status_code = status_code
    response._content = _json_dumps(body).encode()
    response.headers["Content-Type"] = "application/json"
    return response
