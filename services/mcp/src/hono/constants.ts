import type { CloudRegion } from '@/tools/types'

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

export const getAuthorizationServerUrl = (regionParam: string | null): string => {
    const custom = getCustomApiBaseUrl()
    if (custom) {
        return custom
    }
    return getBaseUrlForRegion(toCloudRegion(regionParam))
}

export const MCP_DOCS_URL = 'https://posthog.com/docs/model-context-protocol'

export const OAUTH_SCOPES_SUPPORTED = [
    'openid',
    'profile',
    'email',
    'introspection',
    'action:read',
    'action:write',
    'dashboard:read',
    'dashboard:write',
    'error_tracking:read',
    'error_tracking:write',
    'event_definition:read',
    'event_definition:write',
    'experiment:read',
    'experiment:write',
    'feature_flag:read',
    'feature_flag:write',
    'insight:read',
    'insight:write',
    'logs:read',
    'organization:read',
    'project:read',
    'property_definition:read',
    'query:read',
    'survey:read',
    'survey:write',
    'user:read',
    'warehouse_table:read',
    'warehouse_view:read',
] as const

export function getEnv(): import('@/tools/types').Env {
    return {
        INKEEP_API_KEY: process.env.INKEEP_API_KEY || undefined,
        POSTHOG_API_BASE_URL: process.env.POSTHOG_API_BASE_URL || undefined,
        POSTHOG_MCP_APPS_ANALYTICS_BASE_URL: process.env.POSTHOG_MCP_APPS_ANALYTICS_BASE_URL || undefined,
        POSTHOG_UI_APPS_TOKEN: process.env.POSTHOG_UI_APPS_TOKEN || undefined,
    }
}
