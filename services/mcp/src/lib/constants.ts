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

// Gates the semantic layer (governed-metrics catalog) — no tool declares it, so it must be
// joined into the evaluated flag set explicitly; instructions content branches on it.
export const PRODUCT_DATA_CATALOG_FLAG = 'product-data-catalog'

// Multivariate flag selecting the default text encoding for tool results: variant 'json'
// switches the default from TOON to JSON; any other value keeps TOON. Like
// PRODUCT_DATA_CATALOG_FLAG it gates serialization rather than a tool, so no tool declares
// it and it must be joined into the evaluated flag set explicitly. See
// `resolveDefaultOutputFormat` in lib/posthog/flags.
export const MCP_OUTPUT_FORMAT_FLAG = 'mcp-output-format'
