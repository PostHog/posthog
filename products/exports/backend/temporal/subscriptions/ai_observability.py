import uuid
from typing import Optional, Union

import posthoganalytics
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.runnables import RunnableConfig
from posthoganalytics.ai.langchain.callbacks import CallbackHandler

from posthog.models import Team

# Every generation the subscriptions pipeline makes carries this tag. LLM evaluations sample on it,
# so a stage that omits it is invisible to them; keep new stages on the shared constant.
AI_PRODUCT = "subscriptions"


def generation_properties(
    *, stage: str, subscription_id: Optional[Union[int, str]] = None
) -> dict[str, Union[str, int]]:
    """Properties for one AI subscription generation. `stage` separates the pipeline steps."""
    properties: dict[str, Union[str, int]] = {
        "ai_product": AI_PRODUCT,
        "feature": "ai_subscription",
        "stage": stage,
    }
    if subscription_id is not None:
        properties["subscription_id"] = subscription_id
    return properties


def generation_config(*, team: Team) -> RunnableConfig:
    """Config that makes a LangChain generation reach AI observability.

    langchain-openai emits no $ai_* events by itself, so without this handler the properties set on
    MaxChatOpenAI stay in run metadata and no generation is recorded.
    """
    client = posthoganalytics.default_client
    if client is None:
        return {}
    callbacks: list[BaseCallbackHandler] = [
        CallbackHandler(
            client,
            distinct_id=str(team.id),
            trace_id=f"ai-subscription-{uuid.uuid4()}",
            properties={"ai_product": AI_PRODUCT, "team_id": team.id},
        )
    ]
    return {"callbacks": callbacks}
