# LLM analytics

LLM analytics started as an analytics view over generation events and
has grown into a full LLM platform: traces, evaluations, clustering,
prompt management, a model gateway, a playground, and review queues.

This README is the orientation map for the product folder. Agents
should also read [AGENTS.md](./AGENTS.md) for product-specific rules.

## Directory layout

```txt
products/llm_analytics/
  backend/                # Django app (label: llm_analytics)
    api/                  # DRF viewsets (one file per resource;
                          # api/__init__.py is the canonical inventory)
    llm/                  # Unified LLM client
      client.py           # Single entry point for provider calls
      providers/          # Per-provider adapters
      formatters/         # Provider request/response formatters
    models/               # Django models + pydantic validators
    migrations/
    queries/              # Raw .sql files used by query runners
    summarization/        # Trace and evaluation summarization
    translation/
    text_repr/            # Text-representation formatters for events
    tools/                # Shared backend tools
    test/
  frontend/               # React + kea
    components/           # Reusable UI
    <feature>/            # clusters, datasets, evaluations, playground,
                          # prompts, settings, traceReviews,
                          # scoreDefinitions, skills, ...
    generated/            # Generated types (do not edit)
  mcp/                    # MCP tool definitions
  dags/                   # Dagster jobs + metrics
  skills/                 # Agent skills scoped to the product
  docs/                   # Product-level docs (rollout plans, ADRs)
  shared/                 # Cross-frontend/backend constants, schemas
  manifest.tsx            # Scene + navigation registration
  package.json            # Turborepo package (@posthog/products-llm-analytics)
```

Query runners for the product live **outside** this folder in
`posthog/hogql_queries/ai/`. Two runners matter: `trace_query_runner.py`
(single trace) and `traces_query_runner.py` (list). See
[AGENTS.md](./AGENTS.md) for why that detail matters.

## Running tests locally

```bash
# Backend (pytest, Django)
hogli test products/llm_analytics/backend
hogli test products/llm_analytics/backend/api/test/test_trace_reviews.py

# HogQL query runners (live in posthog/, not products/)
hogli test posthog/hogql_queries/ai

# Frontend (Jest)
hogli test products/llm_analytics/frontend
hogli test products/llm_analytics/frontend/utils.test.ts --watch
```

After changing a serializer or viewset, regenerate OpenAPI and
TypeScript types:

```bash
hogli build:openapi
```

## Further reading

- [AGENTS.md](./AGENTS.md) — product-specific conventions.
- [docs/ai-events-table-rollout.md](./docs/ai-events-table-rollout.md) — ongoing `ai_events` ClickHouse table rollout.
- [products/architecture.md](../architecture.md) — target architecture for products (facades, contracts, isolation). This product has not yet been migrated.
