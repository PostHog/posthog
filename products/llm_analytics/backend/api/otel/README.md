# OpenTelemetry AI Event Ingestion

This module transforms OpenTelemetry traces and logs into PostHog AI events for LLM observability.

## Overview

The OTEL ingestion pipeline accepts OpenTelemetry Protocol (OTLP) data via HTTP endpoints and converts it into PostHog AI events that comply with the PostHog LLM Analytics schema. The system supports two instrumentation patterns (v1 and v2) that differ in how they deliver trace and log data.

## Architecture

```text
OTLP HTTP Request
       |
       v
   ingestion.py (parse protobuf)
       |
       +---> parser.py (decode spans)
       |       |
       |       v
       |   transformer.py (detect v1/v2, transform spans)
       |       |
       |       +---> conventions/ (extract attributes)
       |       |       |
       |       |       +---> posthog_native.py
       |       |       +---> genai.py
       |       |       |       |
       |       |       |       +---> providers/ (framework-specific transformations)
       |       |       |               |
       |       |       |               +---> mastra.py
       |       |       |               +---> base.py
       |       |
       |       +---> event_merger.py (Redis cache for v2)
       |
       +---> logs_parser.py (decode logs)
               |
               v
           logs_transformer.py (transform logs)
               |
               v
           event_merger.py (merge with traces for v2)
               |
               v
       PostHog AI Events ($ai_generation, $ai_span, etc.)
               |
               v
       capture_batch_internal (PostHog capture API)
               |
               v
           Kafka (events_plugin_ingestion topic)
               |
               v
       Plugin-server (ingestion-consumer)
               |
               +---> process-ai-event.ts (cost calculation, normalization)
               |
               v
           ClickHouse (sharded_events table)
```

**Post-transformation flow**:

1. **capture_batch_internal**: OTEL-transformed events enter PostHog's standard event ingestion pipeline
2. **Kafka**: Events are published to the `events_plugin_ingestion` topic for async processing
3. **Plugin-server**: The ingestion consumer processes events through `process-ai-event.ts`:
   - Calculates costs based on token counts and model pricing (`$ai_input_cost_usd`, `$ai_output_cost_usd`, `$ai_total_cost_usd`)
   - Normalizes trace IDs to strings
   - Extracts model parameters (temperature, max_tokens, stream) from `$ai_model_parameters`
4. **ClickHouse**: Events are written to the sharded_events table for querying in PostHog UI

## Instrumentation Patterns

### v1 Instrumentation

**Data Model**: All data in span attributes

v1 instrumentation sends complete LLM call data within span attributes using indexed fields:

- Prompts: `gen_ai.prompt.0.role`, `gen_ai.prompt.0.content`
- Completions: `gen_ai.completion.0.role`, `gen_ai.completion.0.content`
- Metadata: `gen_ai.request.model`, `gen_ai.usage.input_tokens`, etc.

**Processing**: The transformer recognizes v1 in two ways:

1. Span contains `prompt` or `completion` attributes (after extraction)
2. Framework detection via instrumentation scope name (e.g., `@mastra/otel` for Mastra)

When detected, events are sent immediately without caching since v1 spans are self-contained.

**Packages**: `opentelemetry-instrumentation-openai`, Mastra framework (`@mastra/otel-exporter`)

### v2 Instrumentation

**Data Model**: Separated metadata and content

v2 instrumentation splits LLM call data across two channels:

- Traces: Model name, token counts, timing, span structure
- Logs: Message content (user prompts, assistant completions, tool calls)

**Processing**: The event merger provides bidirectional merging - either traces or logs can arrive first. The first arrival caches data in Redis, the second arrival merges and returns a complete event. Multiple log events for the same span are accumulated atomically before merging to ensure completeness.

**Package**: `opentelemetry-instrumentation-openai-v2`

**Design Rationale**: Separating traces and logs allows v2 to stream content while maintaining trace context, but requires a merge layer to recombine data into complete events.

## Components

### ingestion.py

Main entry point for OTLP HTTP requests. Parses protobuf payloads and routes to appropriate transformers. For v2 logs, groups all log records by (trace_id, span_id) before processing to ensure atomic accumulation of multi-log spans.

### transformer.py

Converts OTel spans to PostHog AI events using a waterfall attribute extraction pattern:

1. Extract PostHog-native attributes (highest priority)
2. Extract GenAI semantic convention attributes (fallback, with provider transformers)
3. Merge with PostHog attributes taking precedence

Determines event type based on span characteristics:

- `$ai_generation`: LLM completion requests (has model, tokens, and input)
- `$ai_embedding`: Embedding requests (operation_name matches embedding patterns)
- `$ai_trace`: Root spans (no parent) for v2 frameworks
- `$ai_span`: All other spans, including root spans from v1 frameworks

**v1 Detection**: Checks for `prompt` or `completion` attributes OR framework scope name (e.g., `@mastra/otel`). v1 spans bypass the event merger.

**Event Type Logic**: For v1 frameworks like Mastra, root spans are marked as `$ai_span` (not `$ai_trace`) to ensure they appear in the tree hierarchy. This is necessary because `TraceQueryRunner` filters out `$ai_trace` events from the events array.

### logs_transformer.py

Converts OTel log records to AI event properties. Extracts message content from log body and metadata from log attributes. Designed to work with event_merger for v2 ingestion.

### event_merger.py

Redis-based non-blocking cache for v2 trace/log coordination. Uses simple Redis operations (get/setex/delete) for fast caching and retrieval. Keys expire after 60 seconds to prevent orphaned entries.

**Merge Logic**:

- First arrival: Cache data, return None (event not ready)
- Second arrival: Retrieve cached data, merge properties, delete cache, return complete event

**Key Pattern**: `otel_merge:{type}:{trace_id}:{span_id}`

### parser.py / logs_parser.py

Decode OTLP protobuf messages into Python dictionaries. Handle type conversions (bytes to hex for IDs, nanoseconds to seconds for timestamps) and attribute flattening.

### conventions/

Attribute extraction modules implementing semantic conventions:

**posthog_native.py**: Extracts PostHog-specific attributes prefixed with `posthog.ai.*`. These take precedence in the waterfall.

**genai.py**: Extracts OpenTelemetry GenAI semantic convention attributes (`gen_ai.*`). Handles indexed message fields by collecting attributes like `gen_ai.prompt.0.role` into structured message arrays. Supports provider-specific transformations for frameworks that use custom OTEL formats.

**providers/**: Framework-specific transformers for handling custom OTEL formats:

- **base.py**: Abstract base class defining the provider transformer interface (`can_handle()`, `transform_prompt()`, `transform_completion()`)
- **mastra.py**: Transforms Mastra's wrapped message format (e.g., `{"messages": [...]}` for input, `{"text": "...", "files": [], ...}` for output) into standard PostHog format. Detected by instrumentation scope name `@mastra/otel`.

## Event Schema

All events conform to the PostHog LLM Analytics schema:

**Core Properties**:

- `$ai_input`: Array of message objects `[{role: str, content: str}]`
- `$ai_output_choices`: Array of completion objects `[{role: str, content: str}]`
- `$ai_model`: Model identifier (e.g., "gpt-4o-mini")
- `$ai_provider`: Provider name (e.g., "openai")
- `$ai_input_tokens`: Input token count
- `$ai_output_tokens`: Output token count

**Trace Context**:

- `$ai_trace_id`, `$ai_span_id`, `$ai_parent_id`
- `$ai_session_id`, `$ai_generation_id`

**Metrics**:

- `$ai_latency`: Duration in seconds
- `$ai_total_cost_usd`, `$ai_input_cost_usd`, `$ai_output_cost_usd`

**Configuration**:

- `$ai_temperature`, `$ai_max_tokens`, `$ai_stream`
- `$ai_tools`: Array of tool definitions

**Error Tracking**:

- `$ai_is_error`: Boolean
- `$ai_error`: Error message string

## API Endpoints

**Traces**: `POST /api/projects/{project_id}/ai/otel/v1/traces`

- Content-Type: `application/x-protobuf`
- Authorization: `Bearer {project_api_key}`
- Accepts OTLP trace payloads

**Logs**: `POST /api/projects/{project_id}/ai/otel/v1/logs`

- Content-Type: `application/x-protobuf`
- Authorization: `Bearer {project_api_key}`
- Accepts OTLP log payloads

## Testing

Run unit tests:

```bash
pytest products/llm_analytics/backend/api/otel/
```

Integration testing requires:

1. Running PostHog instance with OTEL endpoints enabled
2. OpenTelemetry SDK configured to send to local endpoints
3. Redis instance for event merger cache

Example v2 test configuration:

```python
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter

trace_exporter = OTLPSpanExporter(
    endpoint=f"{posthog_host}/api/projects/{project_id}/ai/otel/v1/traces",
    headers={"Authorization": f"Bearer {api_key}"}
)

log_exporter = OTLPLogExporter(
    endpoint=f"{posthog_host}/api/projects/{project_id}/ai/otel/v1/logs",
    headers={"Authorization": f"Bearer {api_key}"}
)
```

## Design Decisions

### Waterfall Attribute Extraction

PostHog-native attributes take precedence over GenAI conventions, allowing instrumentation to override standard attributes when needed. This provides flexibility for custom instrumentation while maintaining compatibility with standard OTEL instrumentation.

### Non-Blocking Event Merger

The merger returns None on first arrival rather than blocking. This prevents the ingestion pipeline from waiting on Redis and keeps request processing fast. The tradeoff is that v2 requires two round-trips (trace + logs) before emitting events.

### Atomic Log Accumulation

v2 can send multiple log events in a single HTTP request. The ingestion layer groups these by (trace_id, span_id) and accumulates their properties before calling the merger. This prevents race conditions where partial log data gets merged before all logs arrive.

### v1/v2 Detection

Rather than requiring explicit configuration, the transformer auto-detects instrumentation version by:

1. Checking for `prompt` or `completion` attributes (after extraction)
2. Detecting framework via instrumentation scope name (e.g., `@mastra/otel`)

This allows both patterns to coexist without configuration, and supports frameworks that don't follow standard attribute conventions.

### Provider Transformers

Some frameworks (like Mastra) wrap OTEL data in custom structures that don't match standard GenAI conventions. Provider transformers detect these frameworks (via instrumentation scope or attribute prefixes) and unwrap their data into standard format. This keeps framework-specific logic isolated while maintaining compatibility with the core transformer pipeline.

**Example**: Mastra wraps prompts as `{"messages": [{"role": "user", "content": [...]}]}` where content is an array of `{"type": "text", "text": "..."}` objects. The Mastra transformer unwraps this into standard `[{"role": "user", "content": "..."}]` format.

### Event Type Determination for v1 Frameworks

v1 frameworks create root spans that should appear in the tree hierarchy alongside their children. These root spans are marked as `$ai_span` (not `$ai_trace`) because `TraceQueryRunner` filters out `$ai_trace` events from the events array. This ensures v1 framework traces display correctly with proper parent-child relationships in the UI.

### TTL-Based Cleanup

The event merger uses 60-second TTL on cache entries. This automatically cleans up orphaned data from incomplete traces (e.g., lost log packets) without requiring background jobs or manual cleanup.

## Extending the System

### Adding New Provider Transformers

Create a new transformer in `conventions/providers/`:

```python
from .base import ProviderTransformer
from typing import Any

class CustomFrameworkTransformer(ProviderTransformer):
    """Transform CustomFramework's OTEL format."""

    def can_handle(self, span: dict[str, Any], scope: dict[str, Any]) -> bool:
        """Detect CustomFramework by scope name or attributes."""
        scope_name = scope.get("name", "")
        return scope_name == "custom-framework-scope"

    def transform_prompt(self, prompt: Any) -> Any:
        """Transform wrapped prompt format to standard."""
        if not isinstance(prompt, str):
            return None

        try:
            parsed = json.loads(prompt)
            # Transform custom format to standard
            return [{"role": "user", "content": parsed["text"]}]
        except (json.JSONDecodeError, KeyError):
            return None

    def transform_completion(self, completion: Any) -> Any:
        """Transform wrapped completion format to standard."""
        # Similar transformation logic
        pass
```

Register in `conventions/providers/__init__.py`:

```python
from .custom_framework import CustomFrameworkTransformer

PROVIDER_TRANSFORMERS = [
    CustomFrameworkTransformer,
    MastraTransformer,
]
```

### Adding New Semantic Conventions

Create a new extractor in `conventions/`:

```python
def extract_custom_attributes(span: dict[str, Any]) -> dict[str, Any]:
    attributes = span.get("attributes", {})
    result = {}

    # Extract custom attributes
    if custom_attr := attributes.get("custom.attribute"):
        result["custom_field"] = custom_attr

    return result
```

Add to waterfall in `transformer.py`:

```python
custom_attrs = extract_custom_attributes(span)
merged_attrs = {**genai_attrs, **posthog_attrs, **custom_attrs}
```

### Supporting New Event Types

Add logic to `determine_event_type()` in `transformer.py`:

```python
def determine_event_type(span: dict[str, Any], attrs: dict[str, Any]) -> str:
    op_name = attrs.get("operation_name", "").lower()

    if op_name == "new_operation":
        return "$ai_new_event_type"
    # ... existing logic
```

### Custom Property Mapping

Extend `build_event_properties()` in `transformer.py` to map additional attributes to event properties.

## Performance Characteristics

- **Throughput**: Limited by Redis round-trip time for v2 merging
- **Latency**: v1 has single-pass latency, v2 has cache lookup latency
- **Memory**: Redis cache bounded by TTL (60s max retention)
- **Concurrency**: Simple Redis operations enable fast merging with minimal race condition risk

## References

- [OpenTelemetry GenAI Semantic Conventions](https://opentelemetry.io/docs/specs/semconv/gen-ai/)
- [OTLP Specification](https://opentelemetry.io/docs/specs/otlp/)
- [PostHog AI Engineering Documentation](https://posthog.com/docs/ai-engineering)
