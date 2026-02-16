from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from django.core.signing import TimestampSigner

from posthog.hogql.query import execute_hogql_query

from posthog.models import Team

logger = logging.getLogger(__name__)

BRIDGE_TOKEN_SALT = "streamlit-bridge"
BRIDGE_TOKEN_MAX_AGE_SECONDS = 60 * 60  # 1 hour

PROXY_TOKEN_SALT = "streamlit-proxy"
PROXY_TOKEN_MAX_AGE_SECONDS = 5 * 60  # 5 minutes


@dataclass(frozen=True)
class BridgeTokenClaims:
    team_id: int
    app_id: str


@dataclass(frozen=True)
class ProxyTokenClaims:
    user_id: int
    team_id: int
    app_short_id: str


def generate_bridge_token(team_id: int, app_id: str) -> str:
    signer = TimestampSigner(salt=BRIDGE_TOKEN_SALT)
    payload = json.dumps({"team_id": team_id, "app_id": app_id}, separators=(",", ":"))
    return signer.sign(payload)


def validate_bridge_token(token: str, max_age: int = BRIDGE_TOKEN_MAX_AGE_SECONDS) -> BridgeTokenClaims:
    signer = TimestampSigner(salt=BRIDGE_TOKEN_SALT)
    payload_str = signer.unsign(token, max_age=max_age)
    payload = json.loads(payload_str)
    return BridgeTokenClaims(team_id=payload["team_id"], app_id=payload["app_id"])


def generate_proxy_token(user_id: int, team_id: int, app_short_id: str) -> str:
    signer = TimestampSigner(salt=PROXY_TOKEN_SALT)
    payload = json.dumps(
        {"user_id": user_id, "team_id": team_id, "app_short_id": app_short_id},
        separators=(",", ":"),
    )
    return signer.sign(payload)


def validate_proxy_token(token: str, max_age: int = PROXY_TOKEN_MAX_AGE_SECONDS) -> ProxyTokenClaims:
    signer = TimestampSigner(salt=PROXY_TOKEN_SALT)
    payload_str = signer.unsign(token, max_age=max_age)
    payload = json.loads(payload_str)
    return ProxyTokenClaims(
        user_id=payload["user_id"],
        team_id=payload["team_id"],
        app_short_id=payload["app_short_id"],
    )


def execute_bridge_query(query: str, team_id: int) -> dict:
    team = Team.objects.get(id=team_id)
    response = execute_hogql_query(query=query, team=team)

    if hasattr(response, "model_dump"):
        payload = response.model_dump(exclude_none=True)
    else:
        payload = response.dict(exclude_none=True)

    for key in ("clickhouse", "hogql", "timings", "modifiers"):
        payload.pop(key, None)

    return payload
