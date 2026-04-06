/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
/**
 * * `api_key` - API Key
 * `oauth` - OAuth
 */
export type MCPServerInstallationAuthTypeEnumApi =
    (typeof MCPServerInstallationAuthTypeEnumApi)[keyof typeof MCPServerInstallationAuthTypeEnumApi]

export const MCPServerInstallationAuthTypeEnumApi = {
    ApiKey: 'api_key',
    Oauth: 'oauth',
} as const

export interface MCPServerInstallationApi {
    readonly id: string
    /** @nullable */
    readonly server_id: string | null
    readonly name: string
    /** @maxLength 200 */
    display_name?: string
    /** @maxLength 2048 */
    url?: string
    description?: string
    auth_type?: MCPServerInstallationAuthTypeEnumApi
    is_enabled?: boolean
    readonly needs_reauth: boolean
    readonly pending_oauth: boolean
    readonly proxy_url: string
    readonly created_at: string
    /** @nullable */
    readonly updated_at: string | null
}

export interface PaginatedMCPServerInstallationListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: MCPServerInstallationApi[]
}

export interface PatchedMCPServerInstallationUpdateApi {
    display_name?: string
    description?: string
    is_enabled?: boolean
}

/**
 * * `api_key` - api_key
 * `oauth` - oauth
 */
export type InstallCustomAuthTypeEnumApi =
    (typeof InstallCustomAuthTypeEnumApi)[keyof typeof InstallCustomAuthTypeEnumApi]

export const InstallCustomAuthTypeEnumApi = {
    ApiKey: 'api_key',
    Oauth: 'oauth',
} as const

/**
 * * `posthog` - posthog
 * `posthog-code` - posthog-code
 */
export type InstallSourceEnumApi = (typeof InstallSourceEnumApi)[keyof typeof InstallSourceEnumApi]

export const InstallSourceEnumApi = {
    Posthog: 'posthog',
    PosthogCode: 'posthog-code',
} as const

export interface InstallCustomApi {
    /** @maxLength 200 */
    name: string
    /** @maxLength 2048 */
    url: string
    auth_type: InstallCustomAuthTypeEnumApi
    api_key?: string
    description?: string
    install_source?: InstallSourceEnumApi
    posthog_code_callback_url?: string
}

export interface OAuthRedirectResponseApi {
    redirect_url: string
}

/**
 * * `none` - none
 * `api_key` - api_key
 * `oauth` - oauth
 */
export type RecommendedServerAuthTypeEnumApi =
    (typeof RecommendedServerAuthTypeEnumApi)[keyof typeof RecommendedServerAuthTypeEnumApi]

export const RecommendedServerAuthTypeEnumApi = {
    None: 'none',
    ApiKey: 'api_key',
    Oauth: 'oauth',
} as const

export interface RecommendedServerApi {
    name: string
    url: string
    description: string
    auth_type: RecommendedServerAuthTypeEnumApi
}

export interface PaginatedRecommendedServerListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: RecommendedServerApi[]
}

export type McpServerInstallationsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type McpServerInstallationsAuthorizeRetrieveParams = {
    /**
     * * `posthog` - posthog
     * `posthog-code` - posthog-code
     * @minLength 1
     */
    install_source?: McpServerInstallationsAuthorizeRetrieveInstallSource
    posthog_code_callback_url?: string
    server_id: string
}

export type McpServerInstallationsAuthorizeRetrieveInstallSource =
    (typeof McpServerInstallationsAuthorizeRetrieveInstallSource)[keyof typeof McpServerInstallationsAuthorizeRetrieveInstallSource]

export const McpServerInstallationsAuthorizeRetrieveInstallSource = {
    Posthog: 'posthog',
    PosthogCode: 'posthog-code',
} as const

export type McpServersListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}
