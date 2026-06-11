export {
    USER_AGENT,
    type GetUserAgentOptions,
    getUserAgent,
    POSTHOG_US_BASE_URL,
    POSTHOG_EU_BASE_URL,
    toCloudRegion,
    getBaseUrlForRegion,
    getCustomApiBaseUrl,
    getPublicBaseUrl,
    isCloudApi,
    isLocalApi,
    MCP_DOCS_URL,
    OAUTH_SCOPES_SUPPORTED,
} from './oauth-constants'

import { resolveAuthorizationServerUrl } from './oauth-constants'

export const getAuthorizationServerUrl = (): string => resolveAuthorizationServerUrl()

export const MCP_SERVER_NAME = 'PostHog'
export const MCP_SERVER_VERSION = '1.0.0'
export const MCP_ANALYTICS_SOURCE = 'posthog_mcp_analytics'
