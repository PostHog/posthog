import litellm
from litellm.integrations.custom_logger import CustomLogger

from llm_gateway.callbacks.posthog import PostHogCallback
from llm_gateway.callbacks.prometheus import PrometheusCallback
from llm_gateway.callbacks.rate_limiting import RateLimitCallback
from llm_gateway.config import REGION_TO_URL, get_settings


def init_callbacks() -> None:
    settings = get_settings()
    callbacks: list[CustomLogger] = []

    if settings.posthog_project_token:
        callbacks.append(
            PostHogCallback(
                api_key=settings.posthog_project_token,
                host=settings.posthog_host,
                region=settings.posthog_region,
                region_url=REGION_TO_URL.get(settings.posthog_region),
                mirror_api_key=settings.posthog_mirror_project_token,
                mirror_host=settings.posthog_mirror_host,
            )
        )

    callbacks.append(RateLimitCallback())
    callbacks.append(PrometheusCallback())

    litellm.callbacks = callbacks
