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
         * When true, the tool issues PATCH { deleted: true } instead of DELETE.
         * Use for endpoints backed by ForbidDestroyModel where soft-delete is the
         * correct operation.
         */
        soft_delete: z.boolean().optional(),
        /**
         * When true, the tool is only available when the organization has approved
         * AI data processing (`is_ai_data_processing_approved`). Tools that invoke
         * LLMs internally should set this to true.
         */
        requires_ai_consent: z.boolean().optional(),
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
 * Enforced by lint-tool-names.ts rather than here so pre-existing tools
 * that already exceed the limit don't break schema validation.
 */
export const MAX_TOOL_NAME_LENGTH = 52

export const CategoryConfigSchema = z
    .object({
        category: z.string(),
        feature: z.string(),
        url_prefix: z.string(),
        tools: z.record(z.string(), ToolConfigSchema),
    })
    .strict()

export type CategoryConfig = z.infer<typeof CategoryConfigSchema>
