import httpx
import structlog

from llm_gateway.config import Settings

logger = structlog.get_logger(__name__)

OPENAI_DEFAULT_BASE_URL = "https://api.openai.com/v1"
_CHECK_TIMEOUT_SECONDS = 10.0


class OpenAICredentialError(RuntimeError):
    pass


async def verify_openai_credentials(settings: Settings) -> None:
    """Reject a startup where OpenAI does not accept the configured credentials.

    The key and the organization are configured separately, so a key that does not
    belong to the exported organization passes every local check and then fails
    every completion with a 401. This turns that into a failed rollout.
    """
    if not settings.openai_credential_check_enabled or not settings.openai_api_key:
        return

    base_url = (settings.openai_api_base_url or OPENAI_DEFAULT_BASE_URL).rstrip("/")
    headers = {"Authorization": f"Bearer {settings.openai_api_key}"}
    if settings.openai_organization:
        headers["OpenAI-Organization"] = settings.openai_organization

    try:
        async with httpx.AsyncClient(timeout=_CHECK_TIMEOUT_SECONDS) as client:
            response = await client.get(f"{base_url}/models", headers=headers)
    except httpx.HTTPError as error:
        # An unreachable provider must not block a rollout. A credential problem
        # answers with a status code.
        logger.warning("openai_credential_check_unreachable", error=str(error))
        return

    if response.status_code in (401, 403):
        raise OpenAICredentialError(
            f"OpenAI rejected the configured credentials with {response.status_code} "
            f"({_error_code(response) or 'no error code'}). "
            "Check that the OpenAI API key belongs to the configured organization."
        )

    if response.status_code >= 400:
        logger.warning("openai_credential_check_inconclusive", status_code=response.status_code)
        return

    logger.info("openai_credential_check_passed", organization_configured=bool(settings.openai_organization))


def _error_code(response: httpx.Response) -> str | None:
    try:
        payload = response.json()
    except ValueError:
        return None
    error = payload.get("error") if isinstance(payload, dict) else None
    if not isinstance(error, dict):
        return None
    code = error.get("code") or error.get("type")
    return str(code) if code else None
