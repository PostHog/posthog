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
export type MCPAuthTypeEnumApi = (typeof MCPAuthTypeEnumApi)[keyof typeof MCPAuthTypeEnumApi]

export const MCPAuthTypeEnumApi = {
    ApiKey: 'api_key',
    Oauth: 'oauth',
} as const

export interface MCPServerInstallationApi {
    readonly id: string
    /** @nullable */
    readonly template_id: string | null
    readonly name: string
    /** @maxLength 200 */
    display_name?: string
    /** @maxLength 2048 */
    url?: string
    description?: string
    auth_type?: MCPAuthTypeEnumApi
    is_enabled?: boolean
    readonly needs_reauth: boolean
    readonly pending_oauth: boolean
    readonly proxy_url: string
    /** Number of live (non-removed) tools exposed by this installation. */
    readonly tool_count: number
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
 * * `approved` - Approved
 * `needs_approval` - Needs approval
 * `do_not_use` - Do not use
 */
export type MCPServerInstallationToolApprovalStateEnumApi =
    (typeof MCPServerInstallationToolApprovalStateEnumApi)[keyof typeof MCPServerInstallationToolApprovalStateEnumApi]

export const MCPServerInstallationToolApprovalStateEnumApi = {
    Approved: 'approved',
    NeedsApproval: 'needs_approval',
    DoNotUse: 'do_not_use',
} as const

export interface MCPServerInstallationToolApi {
    readonly id: string
    readonly tool_name: string
    readonly display_name: string
    readonly description: string
    readonly input_schema: unknown
    approval_state?: MCPServerInstallationToolApprovalStateEnumApi
    readonly last_seen_at: string
    /** @nullable */
    readonly removed_at: string | null
    readonly created_at: string
    /** @nullable */
    readonly updated_at: string | null
}

export interface PaginatedMCPServerInstallationToolListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: MCPServerInstallationToolApi[]
}

/**
 * * `approved` - approved
 * `needs_approval` - needs_approval
 * `do_not_use` - do_not_use
 */
export type ToolApprovalUpdateApprovalStateEnumApi =
    (typeof ToolApprovalUpdateApprovalStateEnumApi)[keyof typeof ToolApprovalUpdateApprovalStateEnumApi]

export const ToolApprovalUpdateApprovalStateEnumApi = {
    Approved: 'approved',
    NeedsApproval: 'needs_approval',
    DoNotUse: 'do_not_use',
} as const

export interface PatchedToolApprovalUpdateApi {
    approval_state?: ToolApprovalUpdateApprovalStateEnumApi
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
    client_id?: string
    client_secret?: string
    install_source?: InstallSourceEnumApi
    posthog_code_callback_url?: string
}

export interface OAuthRedirectResponseApi {
    redirect_url: string
}

export interface InstallTemplateApi {
    template_id: string
    api_key?: string
    install_source?: InstallSourceEnumApi
    posthog_code_callback_url?: string
}

/**
 * * `business` - Business Operations
 * `data` - Data & Analytics
 * `design` - Design & Content
 * `dev` - Developer Tools & APIs
 * `infra` - Infrastructure
 * `productivity` - Productivity & Collaboration
 */
export type MCPServerTemplateCategoryEnumApi =
    (typeof MCPServerTemplateCategoryEnumApi)[keyof typeof MCPServerTemplateCategoryEnumApi]

export const MCPServerTemplateCategoryEnumApi = {
    Business: 'business',
    Data: 'data',
    Design: 'design',
    Dev: 'dev',
    Infra: 'infra',
    Productivity: 'productivity',
} as const

export interface MCPServerTemplateApi {
    readonly id: string
    /** @maxLength 200 */
    name: string
    /** @maxLength 2048 */
    url: string
    /** @maxLength 2048 */
    docs_url?: string
    description?: string
    auth_type?: MCPAuthTypeEnumApi
    /** @maxLength 100 */
    icon_key?: string
    category?: MCPServerTemplateCategoryEnumApi
}

export interface PaginatedMCPServerTemplateListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: MCPServerTemplateApi[]
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
    installation_id?: string
    posthog_code_callback_url?: string
    template_id?: string
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
