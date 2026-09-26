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


def resolve_openai_api_key(settings: Settings) -> str | None:
    return settings.openai_api_key or os.environ.get("OPENAI_API_KEY")


def resolve_openai_organization(settings: Settings) -> str | None:
    return settings.openai_organization or os.environ.get("OPENAI_ORGANIZATION") or os.environ.get("OPENAI_ORG_ID")


def resolve_openai_base_url(settings: Settings) -> str | None:
    return settings.openai_api_base_url or os.environ.get("OPENAI_BASE_URL") or os.environ.get("OPENAI_API_BASE")


def uses_openai_credentials(model: str) -> bool:
    try:
        return litellm.get_llm_provider(model=model)[1] == "openai"
    except litellm.BadRequestError:
        return False


def make_openai_responses_call(settings: Settings) -> Callable[..., Awaitable[Any]]:
    api_key = resolve_openai_api_key(settings)
    organization = resolve_openai_organization(settings)
    base_url = resolve_openai_base_url(settings)

    async def llm_call(**kwargs: Any) -> Any:
        kwargs.pop("headers", None)
        kwargs.pop("extra_headers", None)
        model = kwargs.get("model")
        if isinstance(model, str) and uses_openai_credentials(model):
            if api_key:
                kwargs["api_key"] = api_key
            if base_url:
                kwargs["api_base"] = base_url
            if organization:
                kwargs["extra_headers"] = {"OpenAI-Organization": organization}
        return await litellm.aresponses(**kwargs)

    return llm_call


async def check_openai_availability(settings: Settings) -> bool:
    """Report whether OpenAI accepts the effective SDK credentials.

    The key and the organization are configured separately, so a pair that does
    not match passes every local check and then fails every completion with a
    401. The gateway uses this result to reject OpenAI requests without blocking
    other providers. It runs once at startup rather than on every readiness
    probe, unlike the database grant check, because each run costs a request to
    OpenAI.
    """
    if not settings.openai_credential_check_enabled:
        return True

    api_key = resolve_openai_api_key(settings)
    if not api_key:
        return True

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
        logger.error("openai_credential_check_failed", error_code=provider_error_code(error))
        return False
    except openai.APIConnectionError as error:
        logger.warning("openai_credential_check_unreachable", error=str(error))
        return True
    except openai.APIStatusError as error:
        logger.warning("openai_credential_check_inconclusive", status_code=error.status_code)
        return True
    except openai.APIError as error:
        logger.warning("openai_credential_check_inconclusive", error=str(error))
        return True
    except Exception as error:
        # The SDK parses a 2xx body without a guard, so a success response the gateway cannot read
        # raises a plain JSONDecodeError or AttributeError instead of an openai error. A rejected
        # credential always arrives as AuthenticationError above, so nothing that reaches here is
        # a reason to stop the boot.
        logger.warning("openai_credential_check_inconclusive", error=str(error), error_type=type(error).__name__)
        return True

    logger.info("openai_credential_check_passed", organization_configured=bool(organization))
    return True
