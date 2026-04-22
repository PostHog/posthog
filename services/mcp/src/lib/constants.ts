import { env } from 'cloudflare:workers'

import type { CloudRegion } from '@/tools/types'

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

// Region-specific PostHog API base URLs
export const POSTHOG_US_BASE_URL = 'https://us.posthog.com'
export const POSTHOG_EU_BASE_URL = 'https://eu.posthog.com'

// Normalize a string to a valid CloudRegion, defaulting to 'us'
export const toCloudRegion = (value: string | undefined | null): CloudRegion => {
    const normalized = value?.toLowerCase()
    if (normalized === 'eu') {
        return 'eu'
    }
    return 'us'
}

// Get the PostHog base URL for a region
export const getBaseUrlForRegion = (region: CloudRegion): string => {
    return region === 'eu' ? POSTHOG_EU_BASE_URL : POSTHOG_US_BASE_URL
}

/**
 * Custom API base URL for self-hosted PostHog instances.
 *
 * WARNING: In PostHog Production, this should NOT be set.
 * The code automatically handles US/EU region routing via getAuthorizationServerUrl().
 * Only set this for self-hosted PostHog deployments.
 */
export const CUSTOM_API_BASE_URL = env.POSTHOG_API_BASE_URL

const OAUTH_PROXY_URL = 'https://oauth.posthog.com'

// Get the authorization server URL for OAuth
// Uses the cross-region OAuth proxy for cloud, or CUSTOM_API_BASE_URL for self-hosted
export const getAuthorizationServerUrl = (): string => {
    if (CUSTOM_API_BASE_URL) {
        return CUSTOM_API_BASE_URL
    }

    return OAUTH_PROXY_URL
}

// OAuth Authorization Server URL (where clients get tokens)
// Defaults to CUSTOM_API_BASE_URL if not explicitly set
export const OAUTH_AUTHORIZATION_SERVER_URL =
    (env as unknown as Record<string, string | undefined>).OAUTH_AUTHORIZATION_SERVER_URL || CUSTOM_API_BASE_URL

export const MCP_DOCS_URL = 'https://posthog.com/docs/model-context-protocol'

// OAuth Protected Resource Metadata (RFC 9728)
// Scopes that this resource server supports
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
    'ticket:read',
    'ticket:write',
    'user:read',
    'user:write',
    'warehouse_table:read',
    'warehouse_view:read',
    'warehouse_view:write',
    'web_analytics:read',
] as const
