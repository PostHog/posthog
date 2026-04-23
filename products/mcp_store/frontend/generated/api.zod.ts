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

export const mcpServerInstallationsCreateBodyDisplayNameMax = 200

export const mcpServerInstallationsCreateBodyUrlMax = 2048

export const McpServerInstallationsCreateBody = /* @__PURE__ */ zod.object({
    display_name: zod.string().max(mcpServerInstallationsCreateBodyDisplayNameMax).optional(),
    url: zod.url().max(mcpServerInstallationsCreateBodyUrlMax).optional(),
    description: zod.string().optional(),
    auth_type: zod.enum(['api_key', 'oauth']).optional().describe('* `api_key` - API Key\n* `oauth` - OAuth'),
    is_enabled: zod.boolean().optional(),
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

export const McpServerInstallationsPartialUpdateBody = /* @__PURE__ */ zod.object({
    display_name: zod.string().optional(),
    description: zod.string().optional(),
    is_enabled: zod.boolean().optional(),
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

export const McpServerInstallationsToolsPartialUpdateBody = /* @__PURE__ */ zod.object({
    approval_state: zod
        .enum(['approved', 'needs_approval', 'do_not_use'])
        .optional()
        .describe('* `approved` - approved\n* `needs_approval` - needs_approval\n* `do_not_use` - do_not_use'),
})

export const mcpServerInstallationsToolsRefreshCreateBodyDisplayNameMax = 200

export const mcpServerInstallationsToolsRefreshCreateBodyUrlMax = 2048

export const McpServerInstallationsToolsRefreshCreateBody = /* @__PURE__ */ zod.object({
    display_name: zod.string().max(mcpServerInstallationsToolsRefreshCreateBodyDisplayNameMax).optional(),
    url: zod.url().max(mcpServerInstallationsToolsRefreshCreateBodyUrlMax).optional(),
    description: zod.string().optional(),
    auth_type: zod.enum(['api_key', 'oauth']).optional().describe('* `api_key` - API Key\n* `oauth` - OAuth'),
    is_enabled: zod.boolean().optional(),
})

export const mcpServerInstallationsInstallCustomCreateBodyNameMax = 200

export const mcpServerInstallationsInstallCustomCreateBodyUrlMax = 2048

export const mcpServerInstallationsInstallCustomCreateBodyApiKeyDefault = ``
export const mcpServerInstallationsInstallCustomCreateBodyDescriptionDefault = ``
export const mcpServerInstallationsInstallCustomCreateBodyClientIdDefault = ``
export const mcpServerInstallationsInstallCustomCreateBodyClientSecretDefault = ``
export const mcpServerInstallationsInstallCustomCreateBodyInstallSourceDefault = `posthog`
export const mcpServerInstallationsInstallCustomCreateBodyPosthogCodeCallbackUrlDefault = ``

export const McpServerInstallationsInstallCustomCreateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(mcpServerInstallationsInstallCustomCreateBodyNameMax),
    url: zod.url().max(mcpServerInstallationsInstallCustomCreateBodyUrlMax),
    auth_type: zod.enum(['api_key', 'oauth']).describe('* `api_key` - api_key\n* `oauth` - oauth'),
    api_key: zod.string().default(mcpServerInstallationsInstallCustomCreateBodyApiKeyDefault),
    description: zod.string().default(mcpServerInstallationsInstallCustomCreateBodyDescriptionDefault),
    client_id: zod.string().default(mcpServerInstallationsInstallCustomCreateBodyClientIdDefault),
    client_secret: zod.string().default(mcpServerInstallationsInstallCustomCreateBodyClientSecretDefault),
    install_source: zod
        .enum(['posthog', 'posthog-code'])
        .describe('* `posthog` - posthog\n* `posthog-code` - posthog-code')
        .default(mcpServerInstallationsInstallCustomCreateBodyInstallSourceDefault),
    posthog_code_callback_url: zod
        .string()
        .default(mcpServerInstallationsInstallCustomCreateBodyPosthogCodeCallbackUrlDefault),
})

export const mcpServerInstallationsInstallTemplateCreateBodyApiKeyDefault = ``
export const mcpServerInstallationsInstallTemplateCreateBodyInstallSourceDefault = `posthog`
export const mcpServerInstallationsInstallTemplateCreateBodyPosthogCodeCallbackUrlDefault = ``

export const McpServerInstallationsInstallTemplateCreateBody = /* @__PURE__ */ zod.object({
    template_id: zod.uuid(),
    api_key: zod.string().default(mcpServerInstallationsInstallTemplateCreateBodyApiKeyDefault),
    install_source: zod
        .enum(['posthog', 'posthog-code'])
        .describe('* `posthog` - posthog\n* `posthog-code` - posthog-code')
        .default(mcpServerInstallationsInstallTemplateCreateBodyInstallSourceDefault),
    posthog_code_callback_url: zod
        .string()
        .default(mcpServerInstallationsInstallTemplateCreateBodyPosthogCodeCallbackUrlDefault),
})
