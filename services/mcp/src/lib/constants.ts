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
    OAUTH_SCOPES_HIDDEN,
    OAUTH_SCOPES_SUPPORTED,
} from './oauth-constants'

import { resolveAuthorizationServerUrl } from './oauth-constants'

export const getAuthorizationServerUrl = (): string => resolveAuthorizationServerUrl()

export const MCP_SERVER_NAME = 'PostHog'
export const MCP_SERVER_VERSION = '1.0.0'
export const MCP_ANALYTICS_SOURCE = 'posthog_mcp_analytics'

// Claude Code truncates a server's `instructions` payload at this many characters — silently,
// mid-token, with nothing the model can act on. The compact single-exec payload is sized to
// fit, and the tool-domain index absorbs whatever budget the fixed sections leave.
export const MCP_INSTRUCTIONS_CHAR_BUDGET = 2048

// claude.ai's registry silently drops a tool whose serialized `inputSchema` crosses ~16,384
// chars. The exec command reference lands in that schema's `command.description`; this budget
// caps the reference itself, leaving room for the schema's fixed structure, the exec tool
// description, and the injected `context` property. The tool-domain index absorbs the
// overflow by collapsing sub-families, so adding a tool cannot push the schema past the cap.
export const CLAUDE_EXEC_COMMAND_REFERENCE_CHAR_BUDGET = 15_200

// Gates the semantic layer (governed-metrics catalog) — no tool declares it, so it must be
// joined into the evaluated flag set explicitly; instructions content branches on it.
export const PRODUCT_DATA_CATALOG_FLAG = 'product-data-catalog'

// Gates reaching third-party MCP servers connected through the MCP gateway. Same flag as
// the gateway's own UI in the main app, so a team gets the tools when it gets the gateway.
export const MCP_GATEWAY_FLAG = 'mcp-gateway'
