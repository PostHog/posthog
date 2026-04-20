import type { CloudRegion, Env } from '@/tools/types'

import packageJson from '../../package.json'

export const USER_AGENT = `posthog/mcp-server; version: ${packageJson.version}`

export function getUserAgent(clientUserAgent?: string): string {
    if (clientUserAgent) {
        const match = clientUserAgent.match(/posthog\/([\w.-]+)/)
        if (match) {
            return `${USER_AGENT}; for ${match[0]}`
        }
    }
    return USER_AGENT
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

export const getCustomApiBaseUrl = (): string | undefined => {
    return process.env.POSTHOG_API_BASE_URL || undefined
}

const OAUTH_PROXY_URL = 'https://oauth.posthog.com'

export const getAuthorizationServerUrl = (): string => {
    const custom = getCustomApiBaseUrl()
    if (custom) {
        return custom
    }
    return OAUTH_PROXY_URL
}

export const MCP_DOCS_URL = 'https://posthog.com/docs/model-context-protocol'

export const OAUTH_SCOPES_SUPPORTED = [
    'openid',
    'profile',
    'email',
    'introspection',
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
    'evaluation:read',
    'evaluation:write',
    'event_definition:read',
    'event_definition:write',
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
    'integration:read',
    'integration:write',
    'llm_analytics:read',
    'llm_analytics:write',
    'llm_prompt:read',
    'llm_prompt:write',
    'logs:read',
    'notebook:read',
    'notebook:write',
    'organization:read',
    'organization:write',
    'organization_member:read',
    'person:read',
    'person:write',
    'project:read',
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
    'ticket:read',
    'ticket:write',
    'user:read',
    'warehouse_table:read',
    'warehouse_view:read',
    'warehouse_view:write',
] as const

export function getEnv(): Env {
    return {
        INKEEP_API_KEY: process.env.INKEEP_API_KEY || undefined,
        POSTHOG_API_BASE_URL: process.env.POSTHOG_API_BASE_URL || undefined,
        MCP_APPS_BASE_URL: process.env.MCP_APPS_BASE_URL || undefined,
        POSTHOG_MCP_APPS_ANALYTICS_BASE_URL: process.env.POSTHOG_MCP_APPS_ANALYTICS_BASE_URL || undefined,
        POSTHOG_UI_APPS_TOKEN: process.env.POSTHOG_UI_APPS_TOKEN || undefined,
        POSTHOG_ANALYTICS_API_KEY: process.env.POSTHOG_ANALYTICS_API_KEY || undefined,
        POSTHOG_ANALYTICS_HOST: process.env.POSTHOG_ANALYTICS_HOST || undefined,
    }
}
