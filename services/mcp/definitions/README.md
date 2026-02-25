# MCP YAML tool definitions

YAML-driven tool generation for PostHog's MCP server. Each YAML file declares which API
endpoints are exposed as MCP tools, with product teams owning the configuration for their
endpoints.

## How it works

The pipeline turns YAML configs + the Django OpenAPI schema into ready-to-use TypeScript
tool handlers and Zod validation schemas. Operations are discovered by matching URL paths
against product names (e.g., `error_tracking` matches all paths containing `/error_tracking/`),
same approach as the frontend type generator.

```text
OpenAPI schema (Django)
        │
        ▼
  scaffold-yaml          ← discovers operations by URL path, writes YAML stubs
        │
        ▼
  YAML definitions       ← product teams enable tools, add scopes/annotations/descriptions
        │
        ├──► generate-orval-schemas   → Zod schemas from OpenAPI (src/generated/{product}/api.ts)
        │
        └──► generate-tools           → TypeScript handlers (src/tools/generated/{product}.ts)
                                        JSON definitions  (schema/generated-tool-definitions.json)
```

Run the full pipeline: `hogli build:openapi`

## Adding tools for a new product

1. **Scaffold** — generate a starter YAML with all operations disabled:

   ```sh
   pnpm --filter=@posthog/mcp run scaffold-yaml -- --product your_product
   # or for a product folder:
   pnpm --filter=@posthog/mcp run scaffold-yaml -- --product your_product \
       --output ../../products/your_product/mcp/tools.yaml
   ```

2. **Configure** — edit the YAML to enable the tools you want. Each enabled tool needs
   `scopes`, `annotations`, and ideally a `description`:

   ```yaml
   your-tool-name:
     operation: your_product_endpoint_list # operationId from OpenAPI
     enabled: true
     scopes:
       - your_product:read
     annotations:
       readOnly: true
       destructive: false
       idempotent: true
     title: List things
     description: >
       Human-friendly description for the LLM.
   ```

3. **Generate** — run the pipeline to produce handlers and schemas:

   ```sh
   hogli build:openapi
   ```

## Keeping definitions in sync

When backend API endpoints are added or removed, YAML definitions need updating.
The scaffold script handles this automatically:

```sh
pnpm --filter=@posthog/mcp run scaffold-yaml -- --sync-all
```

This is idempotent and non-destructive — it only adds newly discovered operations
(with `enabled: false`) and removes stale ones. All hand-authored configuration
(descriptions, scopes, annotations, etc.) is preserved. CI runs this as a drift check.

## YAML schema reference

Each YAML file has a top-level structure validated by Zod (`scripts/yaml-config-schema.ts`):

```yaml
category: Human readable name # shown in tool registry
feature: snake_case_name # product identifier
url_prefix: /path # base URL for enrich_url links
tools:
  tool-name:
    operation: operation_id # must match an OpenAPI operationId
    enabled: false # set to true to expose as MCP tool
    # --- required when enabled: ---
    scopes: [product:read]
    annotations:
      readOnly: true
      destructive: false
      idempotent: true
    # --- optional: ---
    title: Short title
    description: Detailed description for the LLM
    list: true # marks as a list endpoint
    enrich_url: '{id}' # appended to url_prefix for result URLs
    exclude_params: [field] # hide params from tool input
    include_params: [field] # whitelist params (excludes all others)
    param_overrides: # override Orval-generated param descriptions
      name:
        description: Custom description
```

Unknown keys are rejected at build time (Zod `.strict()`) to catch typos early.
