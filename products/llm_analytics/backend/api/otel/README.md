# OpenTelemetry AI Event Ingestion

This module handles ingestion of OpenTelemetry traces and logs for LLM/AI observability, transforming them into PostHog AI events.

## Overview

The OTEL ingestion system receives OpenTelemetry Protocol (OTLP) data via HTTP and transforms it into PostHog AI events that comply with the PostHog LLM Analytics schema. It supports two instrumentation versions (v1 and v2) with different data delivery patterns.

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
```

## v1 vs v2 Instrumentation

### v1 (Single Span - Deprecated)

**Data Pattern**: Everything in span attributes

- Prompts: `gen_ai.prompt.0.role`, `gen_ai.prompt.0.content`
- Completions: `gen_ai.completion.0.role`, `gen_ai.completion.0.content`
- Metadata: `gen_ai.request.model`, `gen_ai.usage.input_tokens`, etc.

**Ingestion Flow**:

1. Span arrives with all data
2. Transformer detects v1 (presence of `prompt` or `completion` in extracted attributes)
3. Skip event merger - send immediately
4. Result: Single complete event

**Package**: `opentelemetry-instrumentation-openai` (v1)

### v2 (Traces + Logs - Current)

**Data Pattern**: Separated metadata and content

- Traces: Model, tokens, timing, structure
- Logs: Message content (user prompts, assistant responses)

**Ingestion Flow**:

1. Trace arrives first (usually) - cached in Redis
2. Logs arrive (multiple per span) - accumulated atomically
3. Event merger combines trace + logs
4. Result: Single complete event with all data

**Package**: `opentelemetry-instrumentation-openai-v2`

**Critical Implementation Detail**: v2 sends multiple log events (user message, assistant message, tool calls, etc.) in a single HTTP request. The ingestion system MUST accumulate all logs for the same (trace_id, span_id) before calling the event merger to prevent race conditions.

## Components

### ingestion.py

Main entry point for OTLP HTTP requests. Handles:

- Protobuf parsing
- Routing to trace or log transformers
- **v2 Log Accumulation**: Groups logs by (trace_id, span_id) before merging

### transformer.py

Transforms OTel spans to PostHog AI events. Key features:

- Waterfall attribute extraction (PostHog native > GenAI conventions)
- **v1/v2 Detection**: Checks for `prompt`/`completion` in extracted attributes
- Event type determination ($ai_generation, $ai_embedding, $ai_trace, $ai_span)
- Timestamp and latency calculation

### logs_transformer.py

Transforms OTel log records to AI event properties. Extracts:

- Message content from log body
- Event metadata from log attributes
- Works with event_merger for v2 ingestion

### event_merger.py

Redis-based non-blocking cache for v2 trace/log merging. Features:

- **Bidirectional merge**: Either traces or logs can arrive first
- **Atomic operations**: Thread-safe using Redis transactions
- **TTL-based cleanup**: 60-second expiration prevents orphaned entries
- **First arrival caches, second arrival merges and returns complete event**

### parser.py

Decodes OTLP protobuf spans into Python dictionaries. Handles:

- Trace/span ID conversion (bytes to hex)
- Attribute type mapping
- Timestamp conversion

### logs_parser.py

Decodes OTLP protobuf log records. Similar to parser.py but for logs.

### conventions/

Attribute extraction modules following semantic conventions:

#### posthog_native.py

Extracts PostHog-native attributes (highest priority):

- `posthog.ai.model`, `posthog.ai.provider`
- `posthog.ai.input_tokens`, `posthog.ai.output_tokens`
- `posthog.ai.input`, `posthog.ai.output`
- Cost attributes, session IDs, etc.

#### genai.py

Extracts GenAI semantic convention attributes (fallback):

- `gen_ai.request.model`, `gen_ai.system`
- `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`
- **Indexed messages**: `gen_ai.prompt.0.role`, `gen_ai.prompt.0.content`

## PostHog AI Event Schema

All transformed events comply with the PostHog LLM Analytics schema:

**Required Properties**:

- `$ai_input`: Array of message objects with `role` and `content`
- `$ai_output_choices`: Array of choice objects with `role` and `content`
- `$ai_model`: Model identifier (e.g., "gpt-4o-mini")
- `$ai_provider`: Provider name (e.g., "openai")
- `$ai_input_tokens`: Integer token count
- `$ai_output_tokens`: Integer token count

**Optional Properties**:

- `$ai_trace_id`, `$ai_span_id`, `$ai_parent_id`
- `$ai_session_id`, `$ai_generation_id`
- `$ai_latency`: Duration in seconds
- `$ai_total_cost_usd`, `$ai_input_cost_usd`, `$ai_output_cost_usd`
- `$ai_temperature`, `$ai_max_tokens`, `$ai_stream`
- `$ai_tools`: Array of tool definitions
- Error tracking: `$ai_is_error`, `$ai_error`

## Event Types

The transformer determines event types based on span characteristics:

- **$ai_generation**: LLM chat/completion requests (has model + tokens + input)
- **$ai_embedding**: Embedding generation requests (operation_name = "embedding")
- **$ai_trace**: Root spans (no parent_span_id)
- **$ai_span**: Generic spans (default)

## Testing

### Unit Tests

```bash
pytest products/llm_analytics/backend/api/otel/test/
```

### Integration Tests

Test scripts available in `/tmp/`:

- `test_posthog_sdk.py`: PostHog Python SDK with AI wrapper
- `test_otel_v1.py`: v1 instrumentation test
- `test_otel_v2.py`: v2 instrumentation test
- `compare_events.py`: Database comparison of all three methods

Run with llm-analytics-apps venv:

```bash
source /Users/andrewmaguire/Documents/GitHub/llm-analytics-apps/.env
source /Users/andrewmaguire/Documents/GitHub/llm-analytics-apps/python/venv/bin/activate
python /tmp/test_otel_v2.py
```

Check results:

```bash
python /tmp/compare_events.py
```

## Troubleshooting

### v1 Events Not Appearing

**Symptom**: v1 spans cached in Redis but never sent

**Cause**: Detection logic not identifying spans as v1

**Debug**:

```python
import redis
r = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)
keys = r.keys('otel_merge:*')
# Check cached data for prompt/completion attributes
```

**Fix**: Ensure transformer checks for extracted `prompt`/`completion` attributes, not raw `gen_ai.prompt`

### v2 Missing Output

**Symptom**: Events have `$ai_input` but no `$ai_output_choices`

**Cause**: Multiple logs processed sequentially, race condition

**Solution**: Already fixed - logs are accumulated by (trace_id, span_id) before merging

### Events Stuck in Redis

**Symptom**: Redis cache grows over time

**Cause**: Traces waiting for logs that never arrive (or vice versa)

**Debug**:

```python
# Check cache contents
for key in r.keys('otel_merge:*'):
    ttl = r.ttl(key)
    print(f"{key}: TTL={ttl}s")
```

**Fix**: TTL is 60 seconds - entries auto-expire. If persistent, check instrumentation configuration.

### Schema Violations

**Symptom**: Events have unexpected property names

**Cause**: Attribute extraction waterfall not working correctly

**Debug**: Check conventions/ extractors and transformer.py property mapping

## Redis Cache Management

The event merger uses Redis keys with pattern: `otel_merge:{type}:{trace_id}:{span_id}`

**Key Types**:

- `otel_merge:trace:{trace_id}:{span_id}`: Cached trace waiting for logs
- `otel_merge:logs:{trace_id}:{span_id}`: Cached logs waiting for trace

**TTL**: 60 seconds (auto-cleanup)

**Manual Cleanup**:

```python
import redis
r = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)
r.delete(*r.keys('otel_merge:*'))
```

## API Endpoints

**Traces**: `POST /api/projects/{project_id}/ai/otel/v1/traces`

- Accepts: `application/x-protobuf`
- Authorization: `Bearer {project_api_key}`

**Logs**: `POST /api/projects/{project_id}/ai/otel/v1/logs`

- Accepts: `application/x-protobuf`
- Authorization: `Bearer {project_api_key}`

## Performance Considerations

- **Redis Operations**: Atomic using transactions (WATCH/MULTI/EXEC)
- **Non-blocking**: Returns None on first arrival (caches), complete event on second
- **TTL Cleanup**: Automatic expiration prevents memory growth
- **Log Accumulation**: All logs for same span processed atomically (prevents N+1 Redis calls)

## Recent Bug Fixes

### v2 Log Accumulation (2025-11-21)

**Problem**: Race condition when multiple logs arrive in same HTTP request

**Solution**: Group and accumulate all logs by (trace_id, span_id) before calling event merger

**Commit**: `cd4d4e500c`

### v1 Detection (2025-11-21)

**Problem**: v1 spans incorrectly treated as v2, cached waiting for logs

**Solution**: Check for extracted `prompt`/`completion` instead of raw `gen_ai.prompt`/`gen_ai.completion`

**Commits**: `618b4f06ab`, `2e088f790e`

## Contributing

When modifying this system:

1. **Preserve v1/v2 compatibility**: Both versions must work correctly
2. **Test both paths**: Run integration tests for v1 and v2
3. **Check Redis cache**: Ensure no orphaned entries after changes
4. **Validate schema**: Events must comply with PostHog AI schema
5. **Document changes**: Update this README for significant changes

## References

- [OpenTelemetry GenAI Semantic Conventions](https://opentelemetry.io/docs/specs/semconv/gen-ai/)
- [PostHog LLM Analytics Documentation](https://posthog.com/docs/ai-engineering)
- [OTLP Specification](https://opentelemetry.io/docs/specs/otlp/)
