// Runtime-agnostic OAuth/region constants shared between the Cloudflare Workers
// and Hono entry points. No imports from `cloudflare:workers` or Node-only modules
// so this file is safe to import from either runtime.

import type { CloudRegion } from '@/tools/types'

import packageJson from '../../package.json'

export const USER_AGENT = `posthog/mcp-server; version: ${packageJson.version}`

export interface GetUserAgentOptions {
    clientUserAgent?: string | undefined
    /** `x-posthog-mcp-consumer` — self-identifier of the wrapping app (e.g. `posthog-code`, `slack`). */
    mcpConsumer?: string | undefined
    /** MCP `clientInfo.name` — the wrapped client (e.g. `claude-code`). */
    mcpClientName?: string | undefined
}

export function getUserAgent(opts: GetUserAgentOptions = {}): string {
    const { clientUserAgent, mcpConsumer, mcpClientName } = opts
    const parts: string[] = []

    // When the caller self-identifies as a wrapping consumer app, emit
    // `<consumer>/<wrapped-client>` as the leading UA token so downstream
    // services can attribute traffic without parsing custom headers.
    if (mcpConsumer) {
        const wrappedClient = (mcpClientName || 'unknown').replace(/\s+/g, '-')
        parts.push(`${mcpConsumer}/${wrappedClient}`)
    }

    parts.push(USER_AGENT)

    if (clientUserAgent) {
        const match = clientUserAgent.match(/posthog\/([\w.-]+)/)
        if (match) {
            parts[parts.length - 1] = `${USER_AGENT}; for ${match[0]}`
        }
    }

    return parts.join(' ')
}

export const POSTHOG_US_BASE_URL = 'https://us.posthog.com'
export const POSTHOG_EU_BASE_URL = 'https://eu.posthog.com'

export const toCloudRegion = (value: string | undefined | null): CloudRegion => {
    const normalized = value?.toLowerCase()
    if (normalized === 'eu') {
        return 'eu'
    }
    return 'us'
}

export const getBaseUrlForRegion = (region: CloudRegion): string => {
    return region === 'eu' ? POSTHOG_EU_BASE_URL : POSTHOG_US_BASE_URL
}

export const MCP_DOCS_URL = 'https://posthog.com/docs/model-context-protocol'

export const OAUTH_PROXY_URL = 'https://oauth.posthog.com'

// Resolve the OAuth authorization server URL given an optional self-hosted override.
// Each runtime fetches the override from its own env source (CF binding vs process.env)
// and passes it in.
export const resolveAuthorizationServerUrl = (customApiBaseUrl: string | undefined): string => {
    return customApiBaseUrl || OAUTH_PROXY_URL
}

// OAuth Protected Resource Metadata (RFC 9728) — scopes the resource server supports.
export const OAUTH_SCOPES_SUPPORTED = [
    'openid',
    'profile',
    'email',
    'alert:read',
    'alert:write',
    'annotation:read',
    'annotation:write',
    'action:read',
    'action:write',
    'activity_log:read',
    'approvals:read',
    'comment:read',
    'cohort:read',
    'cohort:write',
    'dashboard:read',
    'dashboard:write',
    'early_access_feature:read',
    'early_access_feature:write',
    'endpoint:read',
    'endpoint:write',
    'error_tracking:read',
    'error_tracking:write',
    'event_definition:read',
    'event_definition:write',
    'evaluation:read',
    'external_data_source:read',
    'external_data_source:write',
    'evaluation:write',
    'experiment:read',
    'experiment:write',
    'feature_flag:read',
    'feature_flag:write',
    'group:read',
    'hog_flow:read',
    'hog_function:read',
    'hog_function:write',
    'insight:read',
    'insight:write',
    'insight_variable:read',
    'insight_variable:write',
    'integration:read',
    'integration:write',
    'llm_analytics:read',
    'llm_analytics:write',
    'llm_prompt:read',
    'llm_prompt:write',
    'llm_skill:read',
    'llm_skill:write',
    'logs:read',
    'logs:write',
    'notebook:read',
    'notebook:write',
    'organization:read',
    'organization:write',
    'organization_member:read',
    'person:read',
    'person:write',
    'project:read',
    'project:write',
    'property_definition:read',
    'query:read',
    'session_recording:read',
    'session_recording:write',
    'session_recording_playlist:read',
    'session_recording_playlist:write',
    'subscription:read',
    'subscription:write',
    'survey:read',
    'survey:write',
    'task:read',
    'ticket:read',
    'ticket:write',
    'usage_metric:read',
    'usage_metric:write',
    'user:read',
    'user:write',
    'warehouse_table:read',
    'warehouse_view:read',
    'warehouse_view:write',
    'web_analytics:read',
] as const
