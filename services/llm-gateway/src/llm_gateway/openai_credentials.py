import os
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
import litellm
import openai
import structlog

from llm_gateway.config import Settings
from llm_gateway.provider_errors import provider_error_code

logger = structlog.get_logger(__name__)

_CHECK_TIMEOUT = httpx.Timeout(3.0, connect=2.0)


class OpenAICredentialError(RuntimeError):
    pass


def resolve_openai_api_key(settings: Settings) -> str | None:
    return settings.openai_api_key or os.environ.get("OPENAI_API_KEY")


def resolve_openai_organization(settings: Settings) -> str | None:
    return settings.openai_organization or os.environ.get("OPENAI_ORGANIZATION") or os.environ.get("OPENAI_ORG_ID")


def resolve_openai_base_url(settings: Settings) -> str | None:
    return settings.openai_api_base_url or os.environ.get("OPENAI_BASE_URL") or os.environ.get("OPENAI_API_BASE")


def make_openai_responses_call(settings: Settings) -> Callable[..., Awaitable[Any]]:
    api_key = resolve_openai_api_key(settings)
    organization = resolve_openai_organization(settings)
    base_url = resolve_openai_base_url(settings)

    async def llm_call(**kwargs: Any) -> Any:
        kwargs.pop("headers", None)
        kwargs.pop("extra_headers", None)
        if api_key:
            kwargs["api_key"] = api_key
        if base_url:
            kwargs["api_base"] = base_url
        if organization:
            kwargs["extra_headers"] = {"OpenAI-Organization": organization}
        return await litellm.aresponses(**kwargs)

    return llm_call


async def verify_openai_credentials(settings: Settings) -> None:
    """Reject startup when OpenAI returns 401 for the effective SDK credentials.

    The key and the organization are configured separately, so a pair that does
    not match passes every local check and then fails every completion with a
    401. This turns that into a failed rollout. It runs once at startup rather
    than on every readiness probe, unlike the database grant check, because each
    run costs a request to OpenAI.
    """
    if not settings.openai_credential_check_enabled:
        return

    api_key = resolve_openai_api_key(settings)
    if not api_key:
        return

    organization = resolve_openai_organization(settings)
    base_url = resolve_openai_base_url(settings)

    try:
        async with openai.AsyncOpenAI(
            api_key=api_key,
            organization=organization,
            base_url=base_url,
            timeout=_CHECK_TIMEOUT,
            max_retries=0,
        ) as client:
            await client.models.list()
    except openai.AuthenticationError as error:
        raise OpenAICredentialError(
            f"OpenAI rejected the configured credentials ({provider_error_code(error) or 'no error code'}). "
            "Check that the OpenAI API key belongs to the configured organization."
        ) from error
    except openai.APIConnectionError as error:
        logger.warning("openai_credential_check_unreachable", error=str(error))
        return
    except openai.APIStatusError as error:
        logger.warning("openai_credential_check_inconclusive", status_code=error.status_code)
        return
    except openai.APIError as error:
        logger.warning("openai_credential_check_inconclusive", error=str(error))
        return
    except Exception as error:
        # The SDK parses a 2xx body without a guard, so a success response the gateway cannot read
        # raises a plain JSONDecodeError or AttributeError instead of an openai error. A rejected
        # credential always arrives as AuthenticationError above, so nothing that reaches here is
        # a reason to stop the boot.
        logger.warning("openai_credential_check_inconclusive", error=str(error), error_type=type(error).__name__)
        return

    logger.info("openai_credential_check_passed", organization_configured=bool(organization))
