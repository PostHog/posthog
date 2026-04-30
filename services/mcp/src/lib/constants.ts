import { env } from 'cloudflare:workers'

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
export const CUSTOM_API_BASE_URL = env.POSTHOG_API_BASE_URL

<<<<<<< New base: fix conflicts
<<<<<<< New base: update stuff to remove sse
<<<<<<< New base: refactor stuff, start adding client tests
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

// OAuth Protected Resource Metadata (RFC 9728). Generated from posthog/scopes.py
// to match what the authorization server actually advertises. See
// oauth-scopes.generated.ts and bin/build-mcp-oauth-scopes.py.
export { OAUTH_SCOPES_SUPPORTED, type OAuthScope } from './oauth-scopes.generated'
||||||| Common ancestor
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
    'usage_metric:read',
    'usage_metric:write',
    'user:read',
    'user:write',
    'warehouse_table:read',
    'warehouse_view:read',
    'warehouse_view:write',
    'web_analytics:read',
] as const
=======
export const getAuthorizationServerUrl = (): string => resolveAuthorizationServerUrl(CUSTOM_API_BASE_URL)
>>>>>>> Current commit: refactor stuff, start adding client tests
||||||| Common ancestor
// OAuth Protected Resource Metadata (RFC 9728)
// Scopes that this resource server supports
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
=======
||||||| Common ancestor
<<<<<<< New base: update stuff to remove sse
<<<<<<< New base: refactor stuff, start adding client tests
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
||||||| Common ancestor
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
    'usage_metric:read',
    'usage_metric:write',
    'user:read',
    'user:write',
    'warehouse_table:read',
    'warehouse_view:read',
    'warehouse_view:write',
    'web_analytics:read',
] as const
=======
export const getAuthorizationServerUrl = (): string => resolveAuthorizationServerUrl(CUSTOM_API_BASE_URL)
>>>>>>> Current commit: refactor stuff, start adding client tests
||||||| Common ancestor
// OAuth Protected Resource Metadata (RFC 9728)
// Scopes that this resource server supports
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
=======
=======
>>>>>>> Current commit: fix conflicts
export const getAuthorizationServerUrl = (): string => resolveAuthorizationServerUrl(CUSTOM_API_BASE_URL)
