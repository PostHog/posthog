import httpx
import structlog

from llm_gateway.config import Settings
from llm_gateway.provider_errors import error_code_from_payload

logger = structlog.get_logger(__name__)

OPENAI_DEFAULT_BASE_URL = "https://api.openai.com/v1"
_CHECK_TIMEOUT = httpx.Timeout(3.0, connect=2.0)


class OpenAICredentialError(RuntimeError):
    pass


async def verify_openai_credentials(settings: Settings) -> None:
    """Reject a startup where OpenAI does not accept the configured credentials.

    The key and the organization are configured separately, so a pair that does
    not match passes every local check and then fails every completion with a
    401. This turns that into a failed rollout. It runs once at startup rather
    than on every readiness probe, unlike the database grant check, because each
    run costs a request to OpenAI.
    """
    if not settings.openai_credential_check_enabled or not settings.openai_api_key:
        return

    base_url = (settings.openai_api_base_url or OPENAI_DEFAULT_BASE_URL).rstrip("/")
    headers = {"Authorization": f"Bearer {settings.openai_api_key}"}
    if settings.openai_organization:
        headers["OpenAI-Organization"] = settings.openai_organization

    try:
        async with httpx.AsyncClient(timeout=_CHECK_TIMEOUT) as client:
            response = await client.get(f"{base_url}/models", headers=headers)
    except httpx.HTTPError as error:
        # An unreachable provider must not block a rollout. A rejected
        # credential answers quickly, and with a status code.
        logger.warning("openai_credential_check_unreachable", error=str(error))
        return

    if response.status_code == 401:
        raise OpenAICredentialError(
            f"OpenAI rejected the configured credentials ({_error_code(response) or 'no error code'}). "
            "Check that the OpenAI API key belongs to the configured organization."
        )

    if response.status_code >= 400:
        # Only a 401 names the gateway's own credentials. An edge or a proxy in
        # front of OpenAI answers 403, and that must not hold every pod out of
        # service.
        logger.warning("openai_credential_check_inconclusive", status_code=response.status_code)
        return

    logger.info("openai_credential_check_passed", organization_configured=bool(settings.openai_organization))


def _error_code(response: httpx.Response) -> str | None:
    try:
        payload = response.json()
    except ValueError:
        return None
    return error_code_from_payload(payload)
