/**
 * Zod schemas for MCP YAML tool definitions.
 *
 * Shared between generate-tools.ts and scaffold-yaml.ts to validate
 * that product-authored YAML configs are well-formed. Uses .strict()
 * on all objects to reject unknown keys (catches typos).
 */
import { z } from 'zod'

export const ToolConfigSchema = z
    .object({
        operation: z.string(),
        enabled: z.boolean(),
        scopes: z.array(z.string()).optional(),
        annotations: z
            .object({
                readOnly: z.boolean(),
                destructive: z.boolean(),
                idempotent: z.boolean(),
            })
            .strict()
            .optional(),
        input_schema: z.string().optional(),
        /** Optional TypeScript type expression used for the generated handler return type and request generic. */
        response_type: z.string().optional(),
        enrich_url: z.string().optional(),
        list: z.boolean().optional(),
        title: z.string().optional(),
        description: z.string().optional(),
        /** Path to a file containing the tool description (resolved relative to the YAML file). Mutually exclusive with `description`. */
        description_file: z.string().optional(),
        /**
         * One-line selection hint injected into the system prompt catalog.
         * Describes *when to pick this tool*, not what it does. Currently only
         * surfaced for `query-*` tools in the query tool catalog.
         * Example: "Time series, aggregations, formulas, comparisons"
         */
        system_prompt_hint: z.string().optional(),
        exclude_params: z.array(z.string()).optional(),
        include_params: z.array(z.string()).optional(),
        param_overrides: z
            .record(
                z.string(),
                z
                    .object({
                        description: z.string().optional(),
                        /** Override the default value for this parameter. The field becomes optional with `.default(value)`. */
                        default: z.unknown().optional(),
                        input_schema: z.string().optional(),
                        /** Reference to a schema.json definition. Generates a Zod schema from JSON Schema at build time. */
                        schema_ref: z.string().optional(),
                        /** Properties to exclude when generating from schema_ref. */
                        exclude_properties: z.array(z.string()).optional(),
                        /**
                         * When true, the param becomes optional in the tool schema.
                         * Must be paired with `fallback` to specify the state key used
                         * to resolve the value when the caller omits it.
                         */
                        optional: z.boolean().optional(),
                        /**
                         * State manager key to resolve the param from when omitted.
                         * Supported keys: 'orgId' (→ getOrgID()), 'projectId' (→ getProjectId()).
                         */
                        fallback: z.enum(['orgId', 'projectId']).optional(),
                    })
                    .strict()
                    .refine((data) => !(data.input_schema && data.schema_ref), {
                        message: 'input_schema and schema_ref are mutually exclusive',
                    })
                    .refine((data) => !(data.optional && !data.fallback), {
                        message: 'optional requires a fallback key to resolve the value from state',
                    })
            )
            .optional(),
        mcp_version: z.number().int().positive().optional(),
        /** References a key in ui_apps. */
        ui_app: z.string().optional(),
        /**
         * When true or a string, the tool issues PATCH instead of DELETE.
         * `true` sends `{ deleted: true }` (for ForbidDestroyModel endpoints).
         * A string value specifies a custom field name, e.g. `"archived"` sends
         * `{ archived: true }` (for models that use a different soft-delete field).
         */
        soft_delete: z.union([z.boolean(), z.string()]).optional(),
        /**
         * When true, the tool is only available when the organization has approved
         * AI data processing (`is_ai_data_processing_approved`). Tools that invoke
         * LLMs internally should set this to true.
         */
        requires_ai_consent: z.boolean().optional(),
        /**
         * Maps original OpenAPI field names to MCP-safe aliases. The generated tool
         * schema uses the alias (which must match ^[a-zA-Z0-9_.-]{1,64}$), while
         * the request body still sends the original field name.
         */
        rename_params: z.record(z.string(), z.string()).optional(),
        /**
         * PostHog feature flag key that controls whether this tool is exposed.
         * When set, the tool is only included (or excluded) based on the flag's
         * evaluation for the current user.
         *
         * By default (`feature_flag_behavior: 'enable'`), the tool is only shown
         * when the flag is **on**. Set `feature_flag_behavior: 'disable'` to hide
         * the tool when the flag is on (useful for sunsetting old tools).
         */
        feature_flag: z.string().optional(),
        /**
         * Controls how `feature_flag` gates the tool:
         * - `'enable'` (default): tool is shown only when the flag is on.
         * - `'disable'`: tool is hidden when the flag is on.
         */
        feature_flag_behavior: z.enum(['enable', 'disable']).optional(),
        /**
         * Response field filtering. Supports dot-path patterns with wildcards (e.g. 'filters.groups.*.key').
         * For list endpoints, applied to each item in `results`. `include` and `exclude` are mutually exclusive.
         */
        /**
         * Override the category-level URL prefix for `_posthogUrl` enrichment.
         * Useful when a single category YAML covers tools that link to different frontend pages.
         */
        url_prefix: z.string().optional(),
        response: z
            .object({
                /** Dot-path patterns of response fields to keep. Only matched fields are preserved. */
                include: z.array(z.string()).optional(),
                /** Dot-path patterns of response fields to remove. */
                exclude: z.array(z.string()).optional(),
            })
            .strict()
            .refine((data) => !(data.include?.length && data.exclude?.length), {
                message: 'response.include and response.exclude are mutually exclusive',
            })
            .optional(),
    })
    .strict()
    .refine(
        (data) =>
            !data.input_schema ||
            (!data.include_params?.length && !data.exclude_params?.length && !data.param_overrides),
        {
            message:
                'input_schema replaces the entire schema, so include_params, exclude_params, and param_overrides have no effect and should be removed',
        }
    )
    .refine((data) => !(data.description && data.description_file), {
        message: 'description and description_file are mutually exclusive',
    })

export type ToolConfig = z.infer<typeof ToolConfigSchema>

/** Narrowed type for enabled tools — scopes and annotations are guaranteed present. */
export type EnabledToolConfig = Omit<ToolConfig, 'scopes' | 'annotations'> & {
    scopes: string[]
    annotations: { readOnly: boolean; destructive: boolean; idempotent: boolean }
}

// --- UI App schemas ---
//
// Each entry under ui_apps in a tools.yaml file defines a UI app.
// The discriminator is `type`: 'detail', 'list', or 'custom'.
//
// Most fields are optional — the generator (generate-ui-apps.ts) derives
// them from the app key + the product directory the YAML lives in.
// See resolveDetailApp() and resolveListApp() in generate-ui-apps.ts
// for the full derivation logic.
//
// To add a new field:
// 1. Add it to the appropriate schema below (with .optional() if it has a default)
// 2. Add it to the matching Resolved* interface
// 3. Add the default derivation in the resolve*App() function in generate-ui-apps.ts
// 4. Use the resolved value in generateDetailApp() or generateListApp()

/**
 * Detail UI app — renders a single entity.
 *
 * Generated entry point wraps the view component in AppWrapper and mounts it.
 * The only required field is `view_prop` — everything else is derived by convention.
 */
const DetailUiAppSchema = z
    .object({
        /** Discriminator. Must be 'detail'. */
        type: z.literal('detail'),
        /** The prop name passed to the view component. Required — cannot be derived. */
        view_prop: z.string(),
        /** Display name shown in the MCP client. Default: "PostHog " + title-case of key. */
        app_name: z.string().optional(),
        /** Short description for the MCP resource. Default: title-case of key + " detail view". */
        description: z.string().optional(),
        /** Import path for the view component. Default: derived from product dir (products/{product}/mcp/apps). */
        component_import: z.string().optional(),
        /** TypeScript type for the tool result data. Default: PascalCase(key) + "Data". */
        data_type: z.string().optional(),
        /** React component name that renders the detail view. Default: PascalCase(key) + "View". */
        view_component: z.string().optional(),
    })
    .strict()

/**
 * List UI app — renders a list with drill-down into detail via a tool call.
 *
 * Generated entry point includes the list component, a fallback-to-chat function,
 * and a click handler that calls `detail_tool` via app.callServerTool().
 * The only required field is `detail_tool` — everything else has a default.
 */
const ListUiAppSchema = z
    .object({
        /** Discriminator. Must be 'list'. */
        type: z.literal('list'),
        /** Tool name to call when a list item is clicked (e.g. 'action-get'). Required. */
        detail_tool: z.string(),
        /** JS expression for arguments passed to the detail tool. Default: '{ id: item.id }'. */
        detail_args: z.string().optional(),
        /** Field on the item object used for display in loading/fallback states. Default: 'name'. */
        item_name_field: z.string().optional(),
        /** Prop name for the click handler on the list component. Default: 'on' + PascalCase(singularKey) + 'Click'. */
        click_prop: z.string().optional(),
        /** Human-readable entity label for the fallback chat message. Default: kebab-to-space of singular key. */
        entity_label: z.string().optional(),
        /** Display name shown in the MCP client. Default: "PostHog " + title-case of key. */
        app_name: z.string().optional(),
        /** Short description for the MCP resource. Default: title-case of key + " view". */
        description: z.string().optional(),
        /** Import path for the view component. Default: derived from product dir (products/{product}/mcp/apps). */
        component_import: z.string().optional(),
        /** TypeScript type for the full list response. Default: PascalCase(singularKey) + "ListData". */
        list_data_type: z.string().optional(),
        /** TypeScript type for a single item. Default: PascalCase(singularKey) + "Data". */
        item_data_type: z.string().optional(),
        /** React component name that renders the list view. Default: PascalCase(key) + "View". */
        view_component: z.string().optional(),
    })
    .strict()

/**
 * Custom UI app — handwritten entry point, only gets a registry entry.
 *
 * Use for apps that need fully custom logic (e.g. debug.tsx, query-results.tsx).
 * The generator does NOT create an entry point file — you maintain it manually at
 * services/mcp/src/ui-apps/apps/{key}.tsx.
 */
const CustomUiAppSchema = z
    .object({
        /** Discriminator. Must be 'custom'. */
        type: z.literal('custom'),
        /** Display name shown in the MCP client. Required for custom apps (no convention to derive from). */
        app_name: z.string(),
        /** Short description for the MCP resource. Required for custom apps. */
        description: z.string(),
    })
    .strict()

export const UiAppConfigSchema = z.discriminatedUnion('type', [DetailUiAppSchema, ListUiAppSchema, CustomUiAppSchema])

export type UiAppConfig = z.infer<typeof UiAppConfigSchema>

/** Detail config with all fields resolved (after convention defaults are applied). */
export interface ResolvedDetailUiApp {
    type: 'detail'
    view_prop: string
    app_name: string
    description: string
    component_import: string
    data_type: string
    view_component: string
}

/** List config with all fields resolved (after convention defaults are applied). */
export interface ResolvedListUiApp {
    type: 'list'
    detail_tool: string
    detail_args: string
    item_name_field: string
    click_prop: string
    entity_label: string
    app_name: string
    description: string
    component_import: string
    list_data_type: string
    item_data_type: string
    view_component: string
}

/**
 * Some MCP clients (notably Cursor) enforce a 60-character combined limit on
 * server_name + tool_name. With server name "posthog" (7 chars), tool names
 * must be <= 52 chars to stay under that limit.
 *
 * Length is enforced by lint-tool-names.ts rather than here so pre-existing
 * tools that already exceed the limit don't break schema validation.
 */
export const MAX_TOOL_NAME_LENGTH = 52

/** Tool names must be lowercase kebab-case: letters, digits, hyphens. No leading/trailing hyphens. */
export const TOOL_NAME_PATTERN = /^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$/

/** Feature identifiers must be lowercase snake_case: letters, digits, underscores. */
export const FEATURE_NAME_PATTERN = /^[a-z][a-z0-9_]*$/

// ------------------------------------------------------------------
// Query wrapper config — tools generated from frontend/src/queries/schema.json
// Defined before CategoryConfigSchema so it can be referenced there.
// ------------------------------------------------------------------

export const QueryWrapperToolConfigSchema = z
    .object({
        /** Name of the definition in schema.json (e.g. "AssistantTrendsQuery") */
        schema_ref: z.string(),
        enabled: z.boolean(),
        scopes: z.array(z.string()).optional(),
        annotations: z
            .object({
                readOnly: z.boolean(),
                destructive: z.boolean(),
                idempotent: z.boolean(),
            })
            .strict()
            .optional(),
        mcp_version: z.number().int().positive().optional(),
        title: z.string().optional(),
        description: z.string().optional(),
        /** Path to a file containing the tool description (resolved relative to the YAML file). Mutually exclusive with `description`. */
        description_file: z.string().optional(),
        /**
         * One-line selection hint injected into the query tool catalog in the
         * system prompt. Describes *when to pick this tool*, not what it does.
         * Example: "Time series, aggregations, formulas, comparisons"
         */
        system_prompt_hint: z.string().optional(),
        ui_resource_uri: z.string().optional(),
        /** Properties to exclude from the generated Zod schema */
        exclude_properties: z.array(z.string()).optional(),
        /**
         * Set to `true` when the wrapper's `schema_ref` has a matching formatter in
         * `ee/hogai/context/insight/format/`. Enabling this:
         *   - surfaces the formatter's LLM-friendly text output (via the backend's `formatted_results`)
         *     as the default response text;
         *   - adds an `output_format: 'optimized' | 'json'` per-call input to the generated tool schema,
         *     so the caller can opt into raw JSON when they want structured data instead of prose.
         * Omit (or set to `false`) when the query kind has no formatter; the tool then always returns
         * JSON-encoded results.
         */
        use_optimized_output: z.boolean().optional(),
        /**
         * Default values for properties that are required in the schema but should
         * be optional for the agent. The Zod schema gets `.default(value).optional()`.
         */
        property_defaults: z.record(z.string(), z.unknown()).optional(),
        /**
         * Override the URL enrichment prefix. When set, `_posthogUrl` uses
         * `{baseUrl}{url_prefix}` instead of the default `/insights/new#q=...`.
         */
        url_prefix: z.string().optional(),
        /**
         * PostHog feature flag key that controls whether this tool is exposed.
         * See ToolConfigSchema.feature_flag for full documentation.
         */
        feature_flag: z.string().optional(),
        /**
         * Controls how `feature_flag` gates the tool:
         * - `'enable'` (default): tool is shown only when the flag is on.
         * - `'disable'`: tool is hidden when the flag is on.
         */
        feature_flag_behavior: z.enum(['enable', 'disable']).optional(),
    })
    .strict()
    .refine((data) => !(data.description && data.description_file), {
        message: 'description and description_file are mutually exclusive',
    })

export type QueryWrapperToolConfig = z.infer<typeof QueryWrapperToolConfigSchema>

export type EnabledQueryWrapperToolConfig = Omit<QueryWrapperToolConfig, 'scopes' | 'annotations'> & {
    scopes: string[]
    annotations: { readOnly: boolean; destructive: boolean; idempotent: boolean }
}

export const QueryWrappersConfigSchema = z
    .object({
        category: z.string(),
        feature: z.string(),
        wrappers: z.record(z.string(), QueryWrapperToolConfigSchema),
    })
    .strict()

export type QueryWrappersConfig = z.infer<typeof QueryWrappersConfigSchema>

// ------------------------------------------------------------------
// Category config — the top-level schema for product tools.yaml files.
// Supports both REST tools (via OpenAPI) and query wrappers (via schema.json).
// ------------------------------------------------------------------

export const CategoryConfigSchema = z
    .object({
        category: z.string(),
        feature: z.string().regex(FEATURE_NAME_PATTERN, 'Feature must be lowercase snake_case: [a-z0-9_]'),
        url_prefix: z.string(),
        tools: z.record(
            z
                .string()
                .regex(
                    TOOL_NAME_PATTERN,
                    'Tool name must be lowercase kebab-case: [a-z0-9-], no leading/trailing hyphens'
                ),
            ToolConfigSchema
        ),
        ui_apps: z.record(z.string(), UiAppConfigSchema).optional(),
        /** Query wrapper tools generated from schema.json, co-located with REST tools in the same file. */
        wrappers: z.record(z.string(), QueryWrapperToolConfigSchema).optional(),
    })
    .strict()

export type CategoryConfig = z.infer<typeof CategoryConfigSchema>
