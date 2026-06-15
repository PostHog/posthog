# MCP YAML tool definitions

YAML-driven tool generation for PostHog's MCP server. Each YAML file declares which API
endpoints are exposed as MCP tools, with product teams owning the configuration for their
endpoints.

## How it works

tool handlers and Zod validation schemas. Operations are discovered by their `x-product`
attribution in the OpenAPI spec — auto-derived from the ViewSet module path
(`products/<name>/backend/` → `<name>`) or declared explicitly via
`@extend_schema(extensions={"x-product": "<name>"})`.

```text
OpenAPI schema (Django)
        │
        ▼
  scaffold-yaml          ← discovers operations by x-product, writes YAML stubs
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

   `--product` matches endpoints by their **`x-product`** attribution
   (hyphens are normalized to underscores before matching).
   ViewSets in `products/<name>/backend/` are attributed automatically;
   ViewSets elsewhere need `@extend_schema(extensions={"x-product": "<name>"})`.
   URL paths are never used for discovery.

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
(descriptions, scopes, annotations, etc.) is preserved.

CI runs this as a drift check.

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
    input_schema: ActionCreateSchema # named export from src/schema/tool-inputs.ts
    response_type: Schemas.Action[] # optional TypeScript return type override for generated handlers
    list: true # marks as a list endpoint
    enrich_url: '{id}' # appended to url_prefix for result URLs
    exclude_params: [field] # hide params from tool input
    include_params: [field] # whitelist params (excludes all others)
    response: # filter response fields (applied per-item on list endpoints)
      include: [id, key, name] # keep only these fields (dot-path wildcards supported)
      exclude: [filters.groups.*.properties] # remove these fields
      # include and exclude are mutually exclusive
    requires_ai_consent: true # gate behind org AI data processing consent
    param_overrides: # override individual param descriptions or schemas
      name:
        description: Custom description
        input_schema: NameSchema # replace this param's type with a schema from tool-inputs
    confirmed_action: # typed-confirm two-tool paradigm for destructive actions
      message: "About to {action}. Reply 'confirm' to proceed." # prompt shown to user, supports {param} placeholders
      action_label: Short action label # optional, defaults to tool title
```

Unknown keys are rejected at build time (Zod `.strict()`) to catch typos early.

## Custom input schemas

By default, tool input schemas are derived from the OpenAPI spec via Orval-generated Zod schemas.
When the auto-derived schema isn't ideal for an LLM tool interface (descriptions lacking, field
structure doesn't match, etc.), you can override it with a hand-crafted schema.

Set `input_schema` to the name of an exported Zod schema from `src/schema/tool-inputs.ts`:

```yaml
tools:
  actions-create:
    operation: actions_create
    enabled: true
    input_schema: ActionCreateSchema
    scopes: [action:write]
    annotations:
      readOnly: false
      destructive: false
      idempotent: false
    title: Create an action
    description: Create a new action with custom steps and filters
```

When `input_schema` is set:

- The generated tool imports the named schema from `@/schema/tool-inputs` instead of composing Orval imports
- The `operation` is still used to determine the HTTP method and URL path
- Path parameters are extracted from the URL pattern and interpolated from the input
- Remaining parameters are forwarded as body (POST/PATCH/PUT) or query (GET/DELETE)
- `enrich_url` and `list` enrichment still apply as normal
- You can optionally set `response_type` to override the generated TypeScript return type when MCP intentionally differs from the raw OpenAPI response shape

### Per-param schema overrides

You can also override individual parameter schemas without replacing the entire input schema.
Use `input_schema` inside `param_overrides` to replace a single field's type:

```yaml
tools:
  actions-create:
    operation: actions_create
    enabled: true
    scopes: [action:write]
    annotations:
      readOnly: false
      destructive: false
      idempotent: false
    param_overrides:
      steps:
        input_schema: ActionStepsSchema
        description: The action steps configuration
```

This keeps the Orval-derived schema for all other fields but replaces `steps` with `ActionStepsSchema`
from `src/schema/tool-inputs.ts` via `.extend()`.

## Typed-confirm for destructive tools

Tools that perform destructive or security-sensitive actions can declare `confirmed_action`
to require explicit user confirmation. When this field is present, codegen emits two tools
instead of one:

- `<name>-prepare` — validates args, returns a signed confirmation hash and a message to surface to the user
- `<name>-execute` — verifies the hash plus the literal "confirm" string from the user, then executes the action

The model calls them in sequence: prepare → surface message → wait for user to type "confirm" → execute.

```yaml
tools:
  project-delete:
    operation: projects_delete
    enabled: true
    scopes: [project:delete]
    annotations:
      readOnly: false
      destructive: true
      idempotent: false
    confirmed_action:
      message: "About to delete project {id}. This cannot be undone. Reply 'confirm' to proceed."
      action_label: Delete project
```

`confirmed_action` fields:

| Field          | Required | Description                                                                                              |
| -------------- | -------- | -------------------------------------------------------------------------------------------------------- |
| `message`      | Yes      | Prompt shown to the user. Supports `{paramName}` placeholders interpolated from the validated tool args. |
| `action_label` | No       | Short label for the action (e.g. "delete project"). Defaults to the tool's title.                        |

Requirements:

- The `MCP_SIGNED_STATE_KEY` environment variable (≥32 bytes) must be set on the MCP Hono server
- Cannot be combined with `ui_app` (codegen limitation)
