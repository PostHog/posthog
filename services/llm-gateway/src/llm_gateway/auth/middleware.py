import re

import asyncpg
from fastapi import Request

from llm_gateway.auth.models import AuthenticatedUser
from llm_gateway.auth.oauth import validate_oauth_token
from llm_gateway.auth.personal_api_key import validate_personal_api_key

BEARER_PATTERN = re.compile(r"^Bearer\s+(\S+)$", re.IGNORECASE)


def extract_token(request: Request) -> str | None:
    # Check x-api-key header (Anthropic SDK format)
    api_key = request.headers.get("x-api-key")
    if api_key:
        return api_key.strip()

    # Check Authorization: Bearer header (OpenAI SDK format)
    auth_header = request.headers.get("authorization")
    if not auth_header:
        return None
    match = BEARER_PATTERN.match(auth_header)
    return match.group(1).strip() if match else None


async def authenticate_request(request: Request, pool: asyncpg.Pool) -> AuthenticatedUser | None:
    token = extract_token(request)
    if not token:
        return None

    if token.startswith("pha_"):
        return await validate_oauth_token(token, pool)

    return await validate_personal_api_key(token, pool)
