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
    'annotation:read',
    'annotation:write',
    'action:read',
    'action:write',
    'cohort:read',
    'cohort:write',
    'dashboard:read',
    'dashboard:write',
    'error_tracking:read',
    'error_tracking:write',
    'event_definition:read',
    'event_definition:write',
    'evaluation:read',
    'evaluation:write',
    'experiment:read',
    'experiment:write',
    'feature_flag:read',
    'feature_flag:write',
    'hog_flow:read',
    'hog_function:read',
    'hog_function:write',
    'insight:read',
    'insight:write',
    'llm_prompt:read',
    'llm_prompt:write',
    'logs:read',
    'organization:read',
    'organization:write',
    'project:read',
    'property_definition:read',
    'query:read',
    'survey:read',
    'survey:write',
    'user:read',
    'warehouse_table:read',
    'warehouse_view:read',
] as const
