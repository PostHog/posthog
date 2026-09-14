import json
import hashlib
import secrets
from dataclasses import asdict, field
from typing import Any

from django.core.cache import cache

from posthog.dataclasses import frozen

CONNECTOR_APPROVAL_TTL_SECONDS = 15 * 60


@frozen
class ConnectorApprovalBinding:
    team_id: int
    user_id: int
    installation_id: str
    server_url: str
    tool_name: str
    arguments: dict[str, Any] = field(repr=False)
    scope: str

    def fingerprint(self) -> str:
        payload = json.dumps(asdict(self), sort_keys=True, separators=(",", ":"), allow_nan=False)
        return hashlib.sha256(payload.encode()).hexdigest()

    def cache_key(self, token: str) -> str:
        return f"mcp:connector-approval:{self.team_id}:{hashlib.sha256(token.encode()).hexdigest()}"


def issue_connector_approval(binding: ConnectorApprovalBinding) -> str:
    token = secrets.token_urlsafe(32)
    cache.set(binding.cache_key(token), binding.fingerprint(), timeout=CONNECTOR_APPROVAL_TTL_SECONDS)
    return token


def consume_connector_approval(token: str, binding: ConnectorApprovalBinding) -> bool:
    key = binding.cache_key(token)
    fingerprint = cache.get(key)
    if not isinstance(fingerprint, str) or not secrets.compare_digest(fingerprint, binding.fingerprint()):
        return False
    return bool(cache.delete(key))
