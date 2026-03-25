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
        enrich_url: z.string().optional(),
        list: z.boolean().optional(),
        title: z.string().optional(),
        description: z.string().optional(),
        /** Path to a file containing the tool description (resolved relative to the YAML file). Mutually exclusive with `description`. */
        description_file: z.string().optional(),
        exclude_params: z.array(z.string()).optional(),
        include_params: z.array(z.string()).optional(),
        param_overrides: z
            .record(
                z.string(),
                z
                    .object({
                        description: z.string().optional(),
                        input_schema: z.string().optional(),
                    })
                    .strict()
            )
            .optional(),
        mcp_version: z.number().int().positive().optional(),
        ui_resource_uri: z.string().optional(),
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
    })
    .strict()

export type CategoryConfig = z.infer<typeof CategoryConfigSchema>

// ------------------------------------------------------------------
// Query wrapper config — tools generated from frontend/src/queries/schema.json
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
        ui_resource_uri: z.string().optional(),
        /** Properties to exclude from the generated Zod schema */
        exclude_properties: z.array(z.string()).optional(),
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
