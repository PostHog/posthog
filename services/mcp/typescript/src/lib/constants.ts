import { env } from 'cloudflare:workers'

import type { CloudRegion } from '@/tools/types'

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

export const CUSTOM_BASE_URL = env.POSTHOG_BASE_URL

// OAuth Authorization Server URL (where clients get tokens)
// Defaults to CUSTOM_BASE_URL if not explicitly set
export const OAUTH_AUTHORIZATION_SERVER_URL =
    (env as unknown as Record<string, string | undefined>).OAUTH_AUTHORIZATION_SERVER_URL || CUSTOM_BASE_URL

export const MCP_DOCS_URL = 'https://posthog.com/docs/model-context-protocol'

// OAuth Protected Resource Metadata (RFC 9728)
// Scopes that this resource server supports
export const OAUTH_SCOPES_SUPPORTED = [
    'openid',
    'profile',
    'email',
    'introspection',
    'user:read',
    'organization:read',
    'project:read',
    'feature_flag:read',
    'feature_flag:write',
    'experiment:read',
    'experiment:write',
    'insight:read',
    'insight:write',
    'dashboard:read',
    'dashboard:write',
    'query:read',
    'survey:read',
    'survey:write',
    'error_tracking:read',
    'logs:read',
] as const
