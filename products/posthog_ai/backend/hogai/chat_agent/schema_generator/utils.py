from typing import Generic, TypeVar

from pydantic import BaseModel

from posthog.schema import (
    AssistantFunnelsQuery,
    AssistantHogQLQuery,
    AssistantRetentionQuery,
    AssistantTrendsQuery,
    DataVisualizationNode,
)

Q = TypeVar(
    "Q",
    AssistantHogQLQuery,
    AssistantTrendsQuery,
    AssistantFunnelsQuery,
    AssistantRetentionQuery,
    DataVisualizationNode,
)


class SchemaGeneratorOutput(BaseModel, Generic[Q]):
    query: Q
