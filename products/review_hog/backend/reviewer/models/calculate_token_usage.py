"""Pydantic models for token usage calculation."""

from typing import Any

from pydantic import BaseModel, Field


class BaseUsage(BaseModel):
    """Base token usage model with core token fields."""

    input_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0
    reasoning_output_tokens: int = 0
    output_tokens: int = 0


class UsageDetails(BaseUsage):
    """Token usage details with additional service information."""

    server_tool_use: dict[str, Any] = Field(default_factory=lambda: {"web_search_requests": 0})
    service_tier: str = "standard"


class MetricsData(BaseModel):
    """Metrics data for a single operation."""

    cost_usd: float = 0.0
    duration_ms: int = 0
    num_turns: int = 0
    session_id: str = ""
    usage: UsageDetails = Field(default_factory=UsageDetails)


class ChunkMetrics(BaseModel):
    """Metrics for a single chunk."""

    name: str
    usage: MetricsData


class PassChunks(BaseModel):
    """Chunks within a pass for issue search."""

    name: str
    chunks: list[ChunkMetrics]


class ValidationIssue(BaseModel):
    """Validation metrics for a single issue."""

    issue_id: str
    chunk_id: str
    usage: MetricsData


class PassValidation(BaseModel):
    """Validation metrics for a single pass."""

    name: str
    issues: list[ValidationIssue]


class AggregatedMetrics(BaseModel):
    """Aggregated metrics for a step or total."""

    cost_usd: float = 0.0
    duration_ms: int = 0
    num_turns: int = 0
    usage: BaseUsage = Field(default_factory=BaseUsage)


class StepTotals(BaseModel):
    """Totals for each processing step."""

    chunking: AggregatedMetrics
    analysis: AggregatedMetrics
    issues_search: AggregatedMetrics
    deduplication: AggregatedMetrics
    validation: AggregatedMetrics


class TokenUsageReport(BaseModel):
    """Complete token usage report structure."""

    name: str
    chunking: MetricsData
    analysis: dict[str, list[ChunkMetrics]] = Field(default_factory=dict)
    issues_search: list[PassChunks] = Field(default_factory=list)
    deduplication: MetricsData = Field(default_factory=MetricsData)
    validation: list[PassValidation] = Field(default_factory=list)
    step_totals: StepTotals | None = None
    total: AggregatedMetrics | None = None
