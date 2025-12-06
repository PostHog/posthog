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

**Pattern Detection**: Uses `OtelInstrumentationPattern` enum to determine routing:

1. Provider declares pattern via `get_instrumentation_pattern()` (most reliable)
2. Span has `prompt` or `completion` attributes (indicates V1 data present)
3. Span is an embedding operation (embeddings don't have associated logs)
4. Default to V2 (safer - waits for logs rather than sending incomplete)

V1 spans bypass the event merger and are sent immediately.

**Event Type Logic**: For V1 frameworks, root spans are marked as `$ai_span` (not `$ai_trace`) to ensure they appear in the tree hierarchy. This is necessary because `TraceQueryRunner` filters out `$ai_trace` events from the events array.

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

**Return Format**: Both parsers return a list of items where each item contains its own resource and scope context:

- `parse_otlp_request()`: Returns `[{"span": {...}, "resource": {...}, "scope": {...}}, ...]`
- `parse_otlp_logs_request()`: Returns `[{"log": {...}, "resource": {...}, "scope": {...}}, ...]`

This per-item format ensures correct resource/scope attribution when a single OTLP request contains multiple `resource_spans`/`resource_logs` (e.g., from different services or scopes).

### conventions/

Attribute extraction modules implementing semantic conventions:

**posthog_native.py**: Extracts PostHog-specific attributes prefixed with `posthog.ai.*`. These take precedence in the waterfall.

**genai.py**: Extracts OpenTelemetry GenAI semantic convention attributes (`gen_ai.*`). Handles indexed message fields by collecting attributes like `gen_ai.prompt.0.role` into structured message arrays. Provides `detect_provider()` function for centralized provider detection. Supports provider-specific transformations for frameworks that use custom OTEL formats.

**providers/**: Framework-specific transformers for handling custom OTEL formats:

- **base.py**: Abstract base class defining the provider transformer interface:
  - `can_handle()`: Detect if transformer handles this span
  - `transform_prompt()`: Transform provider-specific prompt format
  - `transform_completion()`: Transform provider-specific completion format
  - `get_instrumentation_pattern()`: Declare V1 or V2 pattern (returns `OtelInstrumentationPattern` enum)
- **mastra.py**: Transforms Mastra's wrapped message format (e.g., `{"messages": [...]}` for input, `{"text": "...", "files": [], ...}` for output) into standard PostHog format. Detected by instrumentation scope name `@mastra/otel`. Declares `V1_ATTRIBUTES` pattern.

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

**Traces**: `POST /api/projects/{project_id}/ai/otel/traces`

- Content-Type: `application/x-protobuf`
- Authorization: `Bearer {project_api_key}`
- Accepts OTLP trace payloads

**Logs**: `POST /api/projects/{project_id}/ai/otel/logs`

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
    endpoint=f"{posthog_host}/api/projects/{project_id}/ai/otel/traces",
    headers={"Authorization": f"Bearer {api_key}"}
)

log_exporter = OTLPLogExporter(
    endpoint=f"{posthog_host}/api/projects/{project_id}/ai/otel/logs",
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

### Pattern Detection via Provider Transformers

Rather than hardcoding framework names, the transformer uses a layered detection approach:

1. **Provider declaration** (most reliable): Providers implement `get_instrumentation_pattern()` returning `OtelInstrumentationPattern.V1_ATTRIBUTES` or `V2_TRACES_AND_LOGS`
2. **Content detection** (fallback): Span has `prompt` or `completion` attributes after extraction
3. **Safe default**: Unknown providers default to V2 (waits for logs rather than sending incomplete events)

This allows both patterns to coexist without configuration, and new providers only need to declare their pattern in one place.

### Provider Transformers

Some frameworks (like Mastra) wrap OTEL data in custom structures that don't match standard GenAI conventions. Provider transformers detect these frameworks (via instrumentation scope or attribute prefixes) and unwrap their data into standard format. This keeps framework-specific logic isolated while maintaining compatibility with the core transformer pipeline.

**Example**: Mastra wraps prompts as `{"messages": [{"role": "user", "content": [...]}]}` where content is an array of `{"type": "text", "text": "..."}` objects. The Mastra transformer unwraps this into standard `[{"role": "user", "content": "..."}]` format.

### Event Type Determination for V1 Frameworks

V1 frameworks create root spans that should appear in the tree hierarchy alongside their children. The `determine_event_type()` function checks `provider.get_instrumentation_pattern()` and marks V1 root spans as `$ai_span` (not `$ai_trace`) because `TraceQueryRunner` filters out `$ai_trace` events from the events array. This ensures V1 framework traces display correctly with proper parent-child relationships in the UI.

### TTL-Based Cleanup

The event merger uses 60-second TTL on cache entries. This automatically cleans up orphaned data from incomplete traces (e.g., lost log packets) without requiring background jobs or manual cleanup.

## Extending the System

### Adding New Provider Transformers

Create a new transformer in `conventions/providers/`:

```python
from .base import OtelInstrumentationPattern, ProviderTransformer
from typing import Any
import json

class CustomFrameworkTransformer(ProviderTransformer):
    """Transform CustomFramework's OTEL format."""

    def can_handle(self, span: dict[str, Any], scope: dict[str, Any]) -> bool:
        """Detect CustomFramework by scope name or attributes."""
        scope_name = scope.get("name", "")
        return scope_name == "custom-framework-scope"

    def get_instrumentation_pattern(self) -> OtelInstrumentationPattern:
        """Declare V1 or V2 pattern - determines event routing."""
        # V1: All data in span attributes, send immediately
        # V2: Metadata in spans, content in logs, requires merge
        return OtelInstrumentationPattern.V1_ATTRIBUTES

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

## Provider Reference

Different LLM frameworks implement OTEL instrumentation with their own nuances. This section documents known provider behaviors to help understand what to expect from each.

### Mastra (`@mastra/otel`)

**Detection**: Instrumentation scope name `@mastra/otel` or `mastra.*` attribute prefix

**OTEL Pattern**: `V1_ATTRIBUTES` (all data in span attributes)

**Key Behaviors**:

- **No conversation history accumulation**: Each `agent.generate()` call creates a separate, independent trace. The `gen_ai.prompt` only contains that specific call's input (typically system message + current user message), not the accumulated conversation history from previous turns.
- **Wrapped message format**: Prompts are JSON-wrapped as `{"messages": [{"role": "user", "content": [{"type": "text", "text": "..."}]}]}` where content is an array of typed objects.
- **Wrapped completion format**: Completions are JSON-wrapped as `{"text": "...", "files": [], "warnings": [], ...}`.
- **Multi-turn traces**: In a multi-turn conversation, you'll see multiple separate traces (one per `agent.generate()` call), each showing only that turn's input/output.

**Implications for PostHog**:

- Each turn appears as a separate trace in LLM Analytics
- To see full conversation context, users need to look at the sequence of traces
- The Mastra transformer unwraps the custom JSON format into standard PostHog message arrays

**Example**: A 4-turn conversation produces 4 traces, where turn 4's input only shows "Thanks, bye!" (not the previous greeting, weather query, and joke request).

### OpenTelemetry Instrumentation OpenAI v1 (`opentelemetry-instrumentation-openai`)

**Detection**: Span attributes with indexed prompt/completion fields (no custom provider transformer needed - uses standard GenAI conventions)

**OTEL Pattern**: `V1_ATTRIBUTES` (all data in span attributes)

**Key Behaviors**:

- **Full conversation in each call**: The `gen_ai.prompt.*` attributes contain all messages passed to the API call
- **Indexed attributes**: Messages use `gen_ai.prompt.0.role`, `gen_ai.prompt.0.content`, etc.
- **Direct attribute format**: No JSON wrapping, values are stored directly as span attributes

**Implications for PostHog**:

- If the application maintains conversation state, later turns show full history
- Each trace is self-contained with complete context

### OpenTelemetry Instrumentation OpenAI v2 (`opentelemetry-instrumentation-openai-v2`)

**Detection**: Spans without prompt/completion attributes, accompanied by OTEL log events (no custom provider transformer needed - detected by absence of V1 content)

**OTEL Pattern**: `V2_TRACES_AND_LOGS` (traces + logs separated)

**Key Behaviors**:

- **Split data model**: Traces contain metadata (model, tokens, timing), logs contain message content
- **Log events**: Uses `gen_ai.user.message`, `gen_ai.assistant.message`, `gen_ai.tool.message`, etc.
- **Full conversation in each call**: Like v1, if the app maintains state, messages accumulate
- **Requires merge**: PostHog's event merger combines traces and logs into complete events

**Implications for PostHog**:

- Slightly higher latency due to merge process
- Supports streaming better than v1
- Both traces and logs endpoints must be configured

## References

- [OpenTelemetry GenAI Semantic Conventions](https://opentelemetry.io/docs/specs/semconv/gen-ai/)
- [OTLP Specification](https://opentelemetry.io/docs/specs/otlp/)
- [PostHog AI Engineering Documentation](https://posthog.com/docs/ai-engineering)
