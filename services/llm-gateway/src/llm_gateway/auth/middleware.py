import re

import asyncpg
from fastapi import Request

from llm_gateway.auth.models import AuthenticatedUser
from llm_gateway.auth.oauth import validate_oauth_token
from llm_gateway.auth.personal_api_key import validate_personal_api_key
from llm_gateway.config import get_settings

BEARER_PATTERN = re.compile(r"^Bearer\s+(\S+)$", re.IGNORECASE)


def extract_token(request: Request) -> str | None:
    # Check x-api-key header (Anthropic SDK format)
    api_key = request.headers.get("x-api-key")
    if api_key:
        print(f"[AUTH DEBUG] Found x-api-key header: {api_key[:20]}...")
        return api_key.strip()

    # Check Authorization: Bearer header (OpenAI SDK format)
    auth_header = request.headers.get("authorization")
    if not auth_header:
        print(f"[AUTH DEBUG] No authorization header found. Headers: {list(request.headers.keys())}")
        return None
    match = BEARER_PATTERN.match(auth_header)
    if match:
        token = match.group(1).strip()
        print(f"[AUTH DEBUG] Found Bearer token: {token[:20]}...")
        return token
    print(f"[AUTH DEBUG] Authorization header didn't match Bearer pattern: {auth_header[:50]}...")
    return None


async def authenticate_request(request: Request, pool: asyncpg.Pool) -> AuthenticatedUser | None:
    settings = get_settings()

    # In auth bypass mode (local dev), accept any token
    if settings.auth_bypass:
        token = extract_token(request)
        if token:
            print("[AUTH DEBUG] Auth bypass enabled, accepting token")
            return AuthenticatedUser(
                user_id=1,
                team_id=1,
                auth_method="bypass",
                scopes=["llm_gateway:read", "llm_gateway:write"],
            )
        return None

    token = extract_token(request)
    if not token:
        return None

    if token.startswith("pha_"):
        return await validate_oauth_token(token, pool)

    return await validate_personal_api_key(token, pool)
