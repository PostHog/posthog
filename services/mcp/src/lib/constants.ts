import { env } from '@/lib/env'

export {
    USER_AGENT,
    type GetUserAgentOptions,
    getUserAgent,
    POSTHOG_US_BASE_URL,
    POSTHOG_EU_BASE_URL,
    toCloudRegion,
    getBaseUrlForRegion,
    MCP_DOCS_URL,
    OAUTH_PROXY_URL,
    OAUTH_SCOPES_SUPPORTED,
} from './oauth-constants'

import { resolveAuthorizationServerUrl } from './oauth-constants'

/**
 * Custom API base URL for self-hosted PostHog instances.
 *
 * WARNING: In PostHog Production, this should NOT be set.
 * The code automatically handles US/EU region routing via getAuthorizationServerUrl().
 * Only set this for self-hosted PostHog deployments.
 */
export const getCustomApiBaseUrl = (): string | undefined => env.POSTHOG_API_BASE_URL

export const getAuthorizationServerUrl = (): string => resolveAuthorizationServerUrl(getCustomApiBaseUrl())
