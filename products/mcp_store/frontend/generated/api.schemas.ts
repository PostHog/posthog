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
 * Arguments passed to the tool, matching its input_schema.
 */
export type GatewayCallRequestApiArguments = { [key: string]: unknown }

export interface GatewayCallRequestApi {
    /** Namespaced tool name to execute: {server_slug}/{tool_name}. */
    tool: string
    /** Arguments passed to the tool, matching its input_schema. */
    arguments?: GatewayCallRequestApiArguments
    /** Optional consumer identifier for analytics attribution (e.g. 'tasks', 'max'). */
    consumer?: string
}

export type GatewayCallResponseApiContentItem = { [key: string]: unknown }

/**
 * Structured result payload, when the tool provides one.
 * @nullable
 */
export type GatewayCallResponseApiStructuredContent = { [key: string]: unknown } | null

export interface GatewayCallResponseApi {
    /** MCP CallToolResult content blocks (e.g. {type: 'text', text: ...}). */
    content: GatewayCallResponseApiContentItem[]
    /** True when the tool itself reported an execution error. */
    is_error: boolean
    /**
     * Structured result payload, when the tool provides one.
     * @nullable
     */
    structured_content?: GatewayCallResponseApiStructuredContent
    /** Slug of the server that executed the tool. */
    server_slug: string
    /** The tool's name on the upstream server (not namespaced). */
    tool_name: string
    /** Upstream execution time in milliseconds. */
    duration_ms: number
}

/**
 * * `tool_not_found` - tool_not_found
 * * `tool_needs_approval` - tool_needs_approval
 * * `tool_blocked` - tool_blocked
 * * `upstream_error` - upstream_error
 */
export type CodeEnumApi = (typeof CodeEnumApi)[keyof typeof CodeEnumApi]

export const CodeEnumApi = {
    ToolNotFound: 'tool_not_found',
    ToolNeedsApproval: 'tool_needs_approval',
    ToolBlocked: 'tool_blocked',
    UpstreamError: 'upstream_error',
} as const

export interface GatewayCallErrorApi {
    /** Machine-readable error code.
     *
     * * `tool_not_found` - tool_not_found
     * * `tool_needs_approval` - tool_needs_approval
     * * `tool_blocked` - tool_blocked
     * * `upstream_error` - upstream_error */
    code: CodeEnumApi
    /** Human-readable error description. */
    detail: string
    /** Settings URL where the tool can be approved (tool_needs_approval only). */
    approval_url?: string
    /** Upstream failure category (upstream_error only): e.g. unreachable, timeout, auth_failed. */
    error_type?: string
}

/**
 * * `personal` - Personal
 * * `shared` - Shared
 */
export type MCPServerScopeEnumApi = (typeof MCPServerScopeEnumApi)[keyof typeof MCPServerScopeEnumApi]

export const MCPServerScopeEnumApi = {
    Personal: 'personal',
    Shared: 'shared',
} as const

export interface GatewayServerApi {
    /** URL-safe server identifier, unique within the caller's resolved set. */
    slug: string
    /** Human-readable server name. */
    display_name: string
    /** UUID of the MCP server installation backing this server. */
    installation_id: string
    /** 'personal' is the caller's own installation; 'shared' is team-wide.
     *
     * * `personal` - Personal
     * * `shared` - Shared */
    scope: MCPServerScopeEnumApi
}

/**
 * * `approved` - Approved
 * * `needs_approval` - Needs approval
 * * `do_not_use` - Do not use
 */
export type MCPToolApprovalStateEnumApi = (typeof MCPToolApprovalStateEnumApi)[keyof typeof MCPToolApprovalStateEnumApi]

export const MCPToolApprovalStateEnumApi = {
    Approved: 'approved',
    NeedsApproval: 'needs_approval',
    DoNotUse: 'do_not_use',
} as const

/**
 * JSON Schema describing the tool's arguments.
 */
export type GatewayToolApiInputSchema = { [key: string]: unknown }

export interface GatewayToolApi {
    /** Namespaced tool name: {server_slug}/{tool_name}. */
    name: string
    /** The connected server this tool belongs to. */
    server: GatewayServerApi
    /** The tool's name on the upstream server (not namespaced). */
    tool_name: string
    /** Tool description from the upstream server. */
    description: string
    /** JSON Schema describing the tool's arguments. */
    input_schema: GatewayToolApiInputSchema
    /** Per-tool approval state. 'needs_approval' tools are listed but blocked at call time.
     *
     * * `approved` - Approved
     * * `needs_approval` - Needs approval
     * * `do_not_use` - Do not use */
    approval_state: MCPToolApprovalStateEnumApi
}

export interface GatewayToolsResponseApi {
    /** The page of matching tools. */
    results: GatewayToolApi[]
    /** Total number of matching tools before pagination. */
    count: number
}

/**
 * * `api_key` - API Key
 * * `oauth` - OAuth
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
    /** Lowercase key from the linked template for brand icons. Empty if custom install (no template). */
    readonly icon_key: string
    /** @maxLength 200 */
    display_name?: string
    /** @maxLength 2048 */
    url?: string
    description?: string
    auth_type?: MCPAuthTypeEnumApi
    is_enabled?: boolean
    readonly scope: MCPServerScopeEnumApi
    /** True when the requesting user owns this installation. Lets clients gate owner-only controls instead of surfacing 403s. */
    readonly is_owner: boolean
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

export interface MCPServerInstallationToolApi {
    readonly id: string
    readonly tool_name: string
    readonly display_name: string
    readonly description: string
    readonly input_schema: unknown
    approval_state?: MCPToolApprovalStateEnumApi
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
 * * `needs_approval` - needs_approval
 * * `do_not_use` - do_not_use
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
 * * `oauth` - oauth
 */
export type InstallCustomAuthTypeEnumApi =
    (typeof InstallCustomAuthTypeEnumApi)[keyof typeof InstallCustomAuthTypeEnumApi]

export const InstallCustomAuthTypeEnumApi = {
    ApiKey: 'api_key',
    Oauth: 'oauth',
} as const

/**
 * * `posthog` - posthog
 * * `posthog-code` - posthog-code
 */
export type InstallSourceEnumApi = (typeof InstallSourceEnumApi)[keyof typeof InstallSourceEnumApi]

export const InstallSourceEnumApi = {
    Posthog: 'posthog',
    PosthogCode: 'posthog-code',
} as const

/**
 * * `personal` - personal
 * * `shared` - shared
 */
export type MCPInstallationScopeEnumApi = (typeof MCPInstallationScopeEnumApi)[keyof typeof MCPInstallationScopeEnumApi]

export const MCPInstallationScopeEnumApi = {
    Personal: 'personal',
    Shared: 'shared',
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
    /** 'personal' is per-user; 'shared' is team-wide (visible to all project members and sandbox agents).
     *
     * * `personal` - personal
     * * `shared` - shared */
    scope?: MCPInstallationScopeEnumApi
}

export interface OAuthRedirectResponseApi {
    redirect_url: string
}

export interface InstallTemplateApi {
    template_id: string
    api_key?: string
    install_source?: InstallSourceEnumApi
    posthog_code_callback_url?: string
    /** 'personal' is per-user; 'shared' is team-wide (visible to all project members and sandbox agents).
     *
     * * `personal` - personal
     * * `shared` - shared */
    scope?: MCPInstallationScopeEnumApi
}

/**
 * * `business` - Business Operations
 * * `data` - Data & Analytics
 * * `design` - Design & Content
 * * `dev` - Developer Tools & APIs
 * * `infra` - Infrastructure
 * * `productivity` - Productivity & Collaboration
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

export type McpGatewayMcpCreateBodyOne = { [key: string]: unknown }

export type McpGatewayMcpCreateBodyTwo = { [key: string]: unknown }

export type McpGatewayMcpCreateBodyThree = { [key: string]: unknown }

export type McpGatewayMcpCreate200 = { [key: string]: unknown }

export type McpGatewayToolsRetrieveParams = {
    /**
     * Maximum number of tools to return.
     * @minimum 1
     * @maximum 500
     */
    limit?: number
    /**
     * Exact namespaced tool name ({server_slug}/{tool_name}).
     * @minLength 1
     */
    name?: string
    /**
     * Number of tools to skip (for pagination).
     * @minimum 0
     */
    offset?: number
    /**
     * Substring search over tool name and description; name matches rank first.
     * @minLength 1
     */
    search?: string
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
     * * `posthog-code` - posthog-code
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
