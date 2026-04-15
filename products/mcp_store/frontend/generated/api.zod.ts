/**
 * Auto-generated Zod validation schemas from the Django backend OpenAPI schema.
 * To modify these schemas, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

export const mcpServerInstallationsListResponseResultsItemDisplayNameMax = 200

export const mcpServerInstallationsListResponseResultsItemUrlMax = 2048

export const McpServerInstallationsListResponse = /* @__PURE__ */ zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(
        zod.object({
            id: zod.uuid(),
            server_id: zod.uuid().nullable(),
            name: zod.string(),
            display_name: zod.string().max(mcpServerInstallationsListResponseResultsItemDisplayNameMax).optional(),
            url: zod.url().max(mcpServerInstallationsListResponseResultsItemUrlMax).optional(),
            description: zod.string().optional(),
            auth_type: zod.enum(['api_key', 'oauth']).optional().describe('* `api_key` - API Key\n* `oauth` - OAuth'),
            is_enabled: zod.boolean().optional(),
            needs_reauth: zod.boolean(),
            pending_oauth: zod.boolean(),
            proxy_url: zod.string(),
            created_at: zod.iso.datetime({}),
            updated_at: zod.iso.datetime({}).nullable(),
        })
    ),
})

export const mcpServerInstallationsCreateBodyDisplayNameMax = 200

export const mcpServerInstallationsCreateBodyUrlMax = 2048

export const McpServerInstallationsCreateBody = /* @__PURE__ */ zod.object({
    display_name: zod.string().max(mcpServerInstallationsCreateBodyDisplayNameMax).optional(),
    url: zod.url().max(mcpServerInstallationsCreateBodyUrlMax).optional(),
    description: zod.string().optional(),
    auth_type: zod.enum(['api_key', 'oauth']).optional().describe('* `api_key` - API Key\n* `oauth` - OAuth'),
    is_enabled: zod.boolean().optional(),
})

export const mcpServerInstallationsRetrieveResponseDisplayNameMax = 200

export const mcpServerInstallationsRetrieveResponseUrlMax = 2048

export const McpServerInstallationsRetrieveResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    server_id: zod.uuid().nullable(),
    name: zod.string(),
    display_name: zod.string().max(mcpServerInstallationsRetrieveResponseDisplayNameMax).optional(),
    url: zod.url().max(mcpServerInstallationsRetrieveResponseUrlMax).optional(),
    description: zod.string().optional(),
    auth_type: zod.enum(['api_key', 'oauth']).optional().describe('* `api_key` - API Key\n* `oauth` - OAuth'),
    is_enabled: zod.boolean().optional(),
    needs_reauth: zod.boolean(),
    pending_oauth: zod.boolean(),
    proxy_url: zod.string(),
    created_at: zod.iso.datetime({}),
    updated_at: zod.iso.datetime({}).nullable(),
})

export const mcpServerInstallationsUpdateBodyDisplayNameMax = 200

export const mcpServerInstallationsUpdateBodyUrlMax = 2048

export const McpServerInstallationsUpdateBody = /* @__PURE__ */ zod.object({
    display_name: zod.string().max(mcpServerInstallationsUpdateBodyDisplayNameMax).optional(),
    url: zod.url().max(mcpServerInstallationsUpdateBodyUrlMax).optional(),
    description: zod.string().optional(),
    auth_type: zod.enum(['api_key', 'oauth']).optional().describe('* `api_key` - API Key\n* `oauth` - OAuth'),
    is_enabled: zod.boolean().optional(),
})

export const mcpServerInstallationsUpdateResponseDisplayNameMax = 200

export const mcpServerInstallationsUpdateResponseUrlMax = 2048

export const McpServerInstallationsUpdateResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    server_id: zod.uuid().nullable(),
    name: zod.string(),
    display_name: zod.string().max(mcpServerInstallationsUpdateResponseDisplayNameMax).optional(),
    url: zod.url().max(mcpServerInstallationsUpdateResponseUrlMax).optional(),
    description: zod.string().optional(),
    auth_type: zod.enum(['api_key', 'oauth']).optional().describe('* `api_key` - API Key\n* `oauth` - OAuth'),
    is_enabled: zod.boolean().optional(),
    needs_reauth: zod.boolean(),
    pending_oauth: zod.boolean(),
    proxy_url: zod.string(),
    created_at: zod.iso.datetime({}),
    updated_at: zod.iso.datetime({}).nullable(),
})

export const McpServerInstallationsPartialUpdateBody = /* @__PURE__ */ zod.object({
    display_name: zod.string().optional(),
    description: zod.string().optional(),
    is_enabled: zod.boolean().optional(),
})

export const mcpServerInstallationsPartialUpdateResponseDisplayNameMax = 200

export const mcpServerInstallationsPartialUpdateResponseUrlMax = 2048

export const McpServerInstallationsPartialUpdateResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    server_id: zod.uuid().nullable(),
    name: zod.string(),
    display_name: zod.string().max(mcpServerInstallationsPartialUpdateResponseDisplayNameMax).optional(),
    url: zod.url().max(mcpServerInstallationsPartialUpdateResponseUrlMax).optional(),
    description: zod.string().optional(),
    auth_type: zod.enum(['api_key', 'oauth']).optional().describe('* `api_key` - API Key\n* `oauth` - OAuth'),
    is_enabled: zod.boolean().optional(),
    needs_reauth: zod.boolean(),
    pending_oauth: zod.boolean(),
    proxy_url: zod.string(),
    created_at: zod.iso.datetime({}),
    updated_at: zod.iso.datetime({}).nullable(),
})

export const mcpServerInstallationsProxyCreateBodyDisplayNameMax = 200

export const mcpServerInstallationsProxyCreateBodyUrlMax = 2048

export const McpServerInstallationsProxyCreateBody = /* @__PURE__ */ zod.object({
    display_name: zod.string().max(mcpServerInstallationsProxyCreateBodyDisplayNameMax).optional(),
    url: zod.url().max(mcpServerInstallationsProxyCreateBodyUrlMax).optional(),
    description: zod.string().optional(),
    auth_type: zod.enum(['api_key', 'oauth']).optional().describe('* `api_key` - API Key\n* `oauth` - OAuth'),
    is_enabled: zod.boolean().optional(),
})

export const mcpServerInstallationsInstallCustomCreateBodyNameMax = 200

export const mcpServerInstallationsInstallCustomCreateBodyUrlMax = 2048

export const mcpServerInstallationsInstallCustomCreateBodyApiKeyDefault = ``
export const mcpServerInstallationsInstallCustomCreateBodyDescriptionDefault = ``
export const mcpServerInstallationsInstallCustomCreateBodyInstallSourceDefault = `posthog`
export const mcpServerInstallationsInstallCustomCreateBodyPosthogCodeCallbackUrlDefault = ``

export const McpServerInstallationsInstallCustomCreateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(mcpServerInstallationsInstallCustomCreateBodyNameMax),
    url: zod.url().max(mcpServerInstallationsInstallCustomCreateBodyUrlMax),
    auth_type: zod.enum(['api_key', 'oauth']).describe('* `api_key` - api_key\n* `oauth` - oauth'),
    api_key: zod.string().default(mcpServerInstallationsInstallCustomCreateBodyApiKeyDefault),
    description: zod.string().default(mcpServerInstallationsInstallCustomCreateBodyDescriptionDefault),
    install_source: zod
        .enum(['posthog', 'posthog-code'])
        .describe('* `posthog` - posthog\n* `posthog-code` - posthog-code')
        .default(mcpServerInstallationsInstallCustomCreateBodyInstallSourceDefault),
    posthog_code_callback_url: zod
        .string()
        .default(mcpServerInstallationsInstallCustomCreateBodyPosthogCodeCallbackUrlDefault),
})

export const McpServerInstallationsInstallCustomCreateResponse = /* @__PURE__ */ zod.object({
    redirect_url: zod.url(),
})

export const McpServersListResponse = /* @__PURE__ */ zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(
        zod.object({
            name: zod.string(),
            url: zod.url(),
            description: zod.string(),
            auth_type: zod
                .enum(['none', 'api_key', 'oauth'])
                .describe('* `none` - none\n* `api_key` - api_key\n* `oauth` - oauth'),
        })
    ),
})
