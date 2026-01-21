import litellm
from litellm.integrations.custom_logger import CustomLogger

from llm_gateway.callbacks.posthog import PostHogCallback
from llm_gateway.callbacks.prometheus import PrometheusCallback
from llm_gateway.callbacks.rate_limiting import RateLimitCallback
from llm_gateway.config import get_settings


def init_callbacks() -> None:
    settings = get_settings()
    callbacks: list[CustomLogger] = []

    if settings.posthog_project_token:
        callbacks.append(
            PostHogCallback(
                api_key=settings.posthog_project_token,
                host=settings.posthog_host,
            )
        )

    callbacks.append(RateLimitCallback())
    callbacks.append(PrometheusCallback())

    litellm.callbacks = callbacks
