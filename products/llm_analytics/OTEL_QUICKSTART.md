# OpenTelemetry Ingestion for PostHog LLM Analytics - Quickstart

This guide shows how to configure OpenTelemetry SDKs to send LLM traces and logs to PostHog.

## Overview

PostHog LLM Analytics supports OpenTelemetry Protocol (OTLP) ingestion for:

- **Traces**: Spans from LLM operations (chat, completions, embeddings)
- **Logs**: Log records containing message content (prompts/completions)

## Endpoints

### Base URL Pattern

```text
{posthog_host}/api/projects/{project_id}/ai/otel/v1/
```

### Specific Endpoints

- **Traces**: `POST /api/projects/{project_id}/ai/otel/v1/traces`
- **Logs**: `POST /api/projects/{project_id}/ai/otel/v1/logs`

### Authentication

Use Personal API Key as Bearer token:

```text
Authorization: Bearer {personal_api_key}
```

## Quick Start

### 1. Get Credentials

1. Find your Project ID in PostHog UI (Settings → Project)
2. Create a Personal API Key (Settings → Personal API Keys)

### 2. Configure Environment

```bash
export POSTHOG_PROJECT_ID=123
export POSTHOG_PERSONAL_API_KEY=phc_...
export POSTHOG_HOST=https://app.posthog.com  # or http://localhost:8000 for local
```

### 3. Configure OpenTelemetry SDK

#### Python (OpenTelemetry SDK)

```python
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

# Create resource
resource = Resource.create({
    "service.name": "my-llm-app",
    "service.version": "1.0.0",
})

# Create tracer provider
tracer_provider = TracerProvider(resource=resource)

# Configure OTLP exporter
traces_endpoint = f"{posthog_host}/api/projects/{project_id}/ai/otel/v1/traces"
trace_exporter = OTLPSpanExporter(
    endpoint=traces_endpoint,
    headers={"Authorization": f"Bearer {personal_api_key}"},
)

# Add batch processor
tracer_provider.add_span_processor(BatchSpanProcessor(trace_exporter))

# Set as global tracer
trace.set_tracer_provider(tracer_provider)
```

#### JavaScript/TypeScript (OpenTelemetry SDK)

```typescript
import { OTLPTraceExporter } from '@opentelemetry/exporter-trace-otlp-http';
import { Resource } from '@opentelemetry/resources';
import { BatchSpanProcessor } from '@opentelemetry/sdk-trace-base';
import { NodeTracerProvider } from '@opentelemetry/sdk-trace-node';

const provider = new NodeTracerProvider({
  resource: new Resource({
    'service.name': 'my-llm-app',
    'service.version': '1.0.0',
  }),
});

const exporter = new OTLPTraceExporter({
  url: `${posthogHost}/api/projects/${projectId}/ai/otel/v1/traces`,
  headers: {
    'Authorization': `Bearer ${personalApiKey}`,
  },
});

provider.addSpanProcessor(new BatchSpanProcessor(exporter));
provider.register();
```

### 4. Instrument Your LLM SDK

#### OpenAI Python

```python
from opentelemetry.instrumentation.openai import OpenAIInstrumentor

# Instrument OpenAI SDK
OpenAIInstrumentor().instrument()

# Now use OpenAI as normal
import openai
response = openai.chat.completions.create(
    model="gpt-4o-mini",
    messages=[{"role": "user", "content": "Hello!"}]
)
```

#### Anthropic (with LangChain)

```python
from opentelemetry.instrumentation.langchain import LangChainInstrumentor

# Instrument LangChain
LangChainInstrumentor().instrument()

# Now use LangChain/Anthropic as normal
from langchain_anthropic import ChatAnthropic
llm = ChatAnthropic(model="claude-3-5-sonnet-20241022")
response = llm.invoke("Hello!")
```

## Supported Conventions

### PostHog Native Attributes (Highest Priority)

Use these for direct control over AI event properties:

```python
span.set_attribute("posthog.ai.model", "gpt-4o-mini")
span.set_attribute("posthog.ai.provider", "openai")
span.set_attribute("posthog.ai.input_tokens", 100)
span.set_attribute("posthog.ai.output_tokens", 50)
span.set_attribute("posthog.ai.total_cost_usd", 0.0042)
span.set_attribute("posthog.ai.input", "What is 2+2?")
span.set_attribute("posthog.ai.output", "4")
```

### GenAI Semantic Conventions (Fallback)

Standard OpenTelemetry GenAI conventions:

```python
span.set_attribute("gen_ai.system", "openai")
span.set_attribute("gen_ai.request.model", "gpt-4o-mini")
span.set_attribute("gen_ai.operation.name", "chat")
span.set_attribute("gen_ai.usage.input_tokens", 100)
span.set_attribute("gen_ai.usage.output_tokens", 50)
span.set_attribute("gen_ai.prompt", "What is 2+2?")
span.set_attribute("gen_ai.completion", "4")
```

## Generated AI Events

PostHog automatically creates these event types:

- `$ai_generation`: Chat/completion operations
- `$ai_embedding`: Embedding operations
- `$ai_span`: Generic LLM spans
- `$ai_trace`: Root spans (traces)

### Event Properties

Events include these properties (when available):

```python
{
    # Core IDs
    "$ai_trace_id": "hex-string",
    "$ai_span_id": "hex-string",
    "$ai_parent_id": "hex-string",
    "$ai_session_id": "session-123",

    # Model info
    "$ai_model": "gpt-4o-mini",
    "$ai_provider": "openai",

    # Tokens & Cost
    "$ai_input_tokens": 100,
    "$ai_output_tokens": 50,
    "$ai_total_cost_usd": 0.0042,

    # Timing & Error
    "$ai_latency": 1.234,
    "$ai_is_error": false,

    # Content
    "$ai_input": "...",
    "$ai_output_choices": "...",

    # Metadata
    "$ai_service_name": "my-app",
    "$ai_otel_transformer_version": "1.0.0"
}
```

## Framework Examples

### Pydantic AI

```python
from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIModel

# Setup OpenTelemetry (see above)

# Instrument OpenAI
from opentelemetry.instrumentation.openai import OpenAIInstrumentor
OpenAIInstrumentor().instrument()

# Use Pydantic AI as normal
agent = Agent(OpenAIModel("gpt-4o-mini"))
result = await agent.run("Hello!")
```

### LangChain

```python
from langchain_openai import ChatOpenAI

# Setup OpenTelemetry (see above)

# Instrument LangChain
from opentelemetry.instrumentation.langchain import LangChainInstrumentor
LangChainInstrumentor().instrument()

# Use LangChain as normal
llm = ChatOpenAI(model="gpt-4o-mini")
response = llm.invoke("Hello!")
```

### LlamaIndex

```python
from llama_index.core import VectorStoreIndex, SimpleDirectoryReader

# Setup OpenTelemetry (see above)

# Instrument OpenAI (used by LlamaIndex)
from opentelemetry.instrumentation.openai import OpenAIInstrumentor
OpenAIInstrumentor().instrument()

# Use LlamaIndex as normal
documents = SimpleDirectoryReader("data").load_data()
index = VectorStoreIndex.from_documents(documents)
response = index.as_query_engine().query("What is...?")
```

## Validation Limits

The ingestion endpoint enforces these limits:

- **Traces:**
  - Max 1000 spans per request
  - Max 128 attributes per span
  - Max 128 events per span
  - Max 128 links per span
  - Max 100KB per attribute value
  - Max 1024 characters for span names

- **Logs:**
  - Max 1000 log records per request
  - Max 128 attributes per log
  - Max 100KB for log body
  - Max 100KB per attribute value

Configure your SDK's batch settings if you hit these limits:

```python
# Python
processor = BatchSpanProcessor(
    exporter,
    max_export_batch_size=500,  # Lower than 1000
)
```

## Troubleshooting

### No events appearing in PostHog

1. **Check authentication:**
   - Verify Personal API Key is valid
   - Check for 401/403 responses in network logs

2. **Check endpoint URL:**
   - Ensure project ID is correct
   - Verify host URL (no trailing slash)

3. **Check OTLP exporter:**
   - Verify protobuf content type is being sent
   - Check for connection errors in SDK logs

### Events missing properties

1. **Check instrumentation:**
   - Ensure SDK instrumentation is installed
   - Verify instrumentation is called before SDK usage

2. **Check conventions:**
   - Use PostHog native (`posthog.ai.*`) or GenAI (`gen_ai.*`) attributes
   - Verify attribute names are correct

### High latency or timeouts

1. **Check batch settings:**
   - Reduce batch size if hitting limits
   - Increase batch timeout for better throughput

2. **Check network:**
   - Verify PostHog host is reachable
   - Check for proxy/firewall issues

## Development & Testing

### Local Development

1. Start PostHog locally:

   ```bash
   cd /path/to/posthog
   ./bin/start
   ```

2. Use local endpoint:

   ```text
   http://localhost:8000/api/projects/{project_id}/ai/otel/v1/
   ```

### Testing with Console Exporter

Add console exporter for debugging:

```python
from opentelemetry.sdk.trace.export import ConsoleSpanExporter

# Add console exporter alongside PostHog exporter
console_exporter = ConsoleSpanExporter()
tracer_provider.add_span_processor(BatchSpanProcessor(console_exporter))
```

This will print spans to stdout for verification.

## Next Steps

1. **Verify ingestion:** Check PostHog LLM Analytics UI for events
2. **Add session tracking:** Set `$ai_session_id` for grouping traces
3. **Add custom attributes:** Enrich spans with app-specific data
4. **Monitor costs:** Track `$ai_total_cost_usd` per model/provider
5. **Set up alerts:** Create insights for errors, latency, costs

## References

- [OpenTelemetry Python SDK](https://opentelemetry.io/docs/instrumentation/python/)
- [OpenTelemetry JavaScript SDK](https://opentelemetry.io/docs/instrumentation/js/)
- [GenAI Semantic Conventions](https://opentelemetry.io/docs/specs/semconv/gen-ai/)
- [OTLP Specification](https://opentelemetry.io/docs/specs/otlp/)
