"""Go-to-market strategy generation endpoint.

Takes a product description and uses OpenAI to generate a GTM strategy
with a description and list of actionable steps.

Endpoint:
- POST /api/projects/:id/founder/go-to-market/
"""

import os
from typing import Any, cast

from django.conf import settings

import structlog
from asgiref.sync import async_to_sync
from drf_spectacular.utils import extend_schema
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionMessageParam
from pydantic import BaseModel, ConfigDict, Field
from rest_framework import exceptions, serializers, status, viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin

logger = structlog.get_logger(__name__)

GTM_TIMEOUT = 90


class GTMStep(BaseModel):
    """A single step in the go-to-market strategy."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(description="Short title for the step")
    description: str = Field(description="Detailed explanation of what to do in this step")
    timeline: str = Field(description="Suggested timeline for this step (e.g. 'Week 1-2', 'Month 1')")
    key_actions: list[str] = Field(description="Concrete actions to take during this step")


class GTMStrategyResponse(BaseModel):
    """Structured go-to-market strategy response."""

    model_config = ConfigDict(extra="forbid")

    strategy_description: str = Field(description="High-level overview of the go-to-market strategy (2-3 paragraphs)")
    target_audience: str = Field(description="Who the product is for and why they need it")
    value_proposition: str = Field(description="The core value proposition in one sentence")
    steps: list[GTMStep] = Field(description="Ordered list of steps to execute the GTM strategy")


class GoToMarketRequestSerializer(serializers.Serializer):
    product_description = serializers.CharField(
        min_length=10,
        max_length=5000,
        help_text="Description of the product idea (e.g. 'I want to build a coworking space app')",
    )


class GTMStepSerializer(serializers.Serializer):
    title = serializers.CharField()
    description = serializers.CharField()
    timeline = serializers.CharField()
    key_actions = serializers.ListField(child=serializers.CharField())


class GoToMarketResponseSerializer(serializers.Serializer):
    strategy_description = serializers.CharField()
    target_audience = serializers.CharField()
    value_proposition = serializers.CharField()
    steps = GTMStepSerializer(many=True)


GTM_SYSTEM_PROMPT = """You are an expert startup strategist and go-to-market advisor.
Given a product description, produce a comprehensive go-to-market strategy plan.

Your strategy should be:
- Actionable and specific to the product described
- Ordered chronologically from pre-launch to growth
- Realistic for a startup with limited resources
- Focused on early traction and finding product-market fit

Include 5-8 concrete steps covering: market research, MVP positioning, launch channels,
early user acquisition, feedback loops, and scaling triggers."""


async def generate_gtm_strategy(product_description: str, team_id: int) -> GTMStrategyResponse:
    """Call OpenAI to generate a go-to-market strategy."""
    if not os.getenv("OPENAI_API_KEY"):
        raise exceptions.APIException("OpenAI API key not configured")

    client = AsyncOpenAI(base_url=settings.OPENAI_BASE_URL, timeout=GTM_TIMEOUT)

    messages: list[ChatCompletionMessageParam] = [
        {"role": "system", "content": GTM_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": f"Generate a go-to-market strategy for the following product:\n\n{product_description}",
        },
    ]

    try:
        response = await client.chat.completions.create(
            model="gpt-4.1",
            messages=messages,
            response_format=cast(
                Any,
                {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "gtm_strategy_response",
                        "strict": True,
                        "schema": GTMStrategyResponse.model_json_schema(),
                    },
                },
            ),
        )

        content = response.choices[0].message.content
        if not content:
            raise exceptions.ValidationError("OpenAI returned empty response")
        return GTMStrategyResponse.model_validate_json(content)
    except exceptions.ValidationError:
        raise
    except Exception as e:
        logger.exception("OpenAI API call failed for GTM strategy", error=str(e), team_id=team_id)
        raise exceptions.APIException("Failed to generate go-to-market strategy")


@extend_schema(tags=["founder_mode"])
class GoToMarketViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """Generate a go-to-market strategy for a product idea using AI."""

    scope_object = "INTERNAL"
    serializer_class = GoToMarketRequestSerializer

    @extend_schema(
        request=GoToMarketRequestSerializer,
        responses={200: GoToMarketResponseSerializer},
    )
    def create(self, request: Request, **kwargs) -> Response:
        """
        Generate a go-to-market strategy.

        POST /api/projects/:id/founder/go-to-market/
        """
        serializer = GoToMarketRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        product_description = serializer.validated_data["product_description"]

        result = async_to_sync(generate_gtm_strategy)(product_description, self.team_id)
        return Response(result.model_dump(), status=status.HTTP_200_OK)
