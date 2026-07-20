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
 * * `auto` - Auto-approved
 * * `approved` - Approved
 * * `pending` - Awaiting approval
 * * `blocked` - Blocked
 */
export type MCPAuditDecisionEnumApi = (typeof MCPAuditDecisionEnumApi)[keyof typeof MCPAuditDecisionEnumApi]

export const MCPAuditDecisionEnumApi = {
    Auto: 'auto',
    Approved: 'approved',
    Pending: 'pending',
    Blocked: 'blocked',
} as const

/**
 * * `engineering` - Engineering
 * * `data` - Data
 * * `product` - Product Management
 * * `founder` - Founder
 * * `leadership` - Leadership
 * * `marketing` - Marketing
 * * `sales` - Sales / Success
 * * `other` - Other
 */
export type RoleAtOrganizationEnumApi = (typeof RoleAtOrganizationEnumApi)[keyof typeof RoleAtOrganizationEnumApi]

export const RoleAtOrganizationEnumApi = {
    Engineering: 'engineering',
    Data: 'data',
    Product: 'product',
    Founder: 'founder',
    Leadership: 'leadership',
    Marketing: 'marketing',
    Sales: 'sales',
    Other: 'other',
} as const

export type BlankEnumApi = (typeof BlankEnumApi)[keyof typeof BlankEnumApi]

export const BlankEnumApi = {
    '': '',
} as const

/**
 * @nullable
 */
export type UserBasicApiHedgehogConfig = { [key: string]: unknown } | null

export interface UserBasicApi {
    readonly id: number
    readonly uuid: string
    /**
     * @maxLength 200
     * @nullable
     */
    distinct_id?: string | null
    /** @maxLength 150 */
    first_name?: string
    /** @maxLength 150 */
    last_name?: string
    /** @maxLength 254 */
    email: string
    /** @nullable */
    is_email_verified?: boolean | null
    /** @nullable */
    readonly hedgehog_config: UserBasicApiHedgehogConfig
    role_at_organization?: RoleAtOrganizationEnumApi | BlankEnumApi | null
}

export interface AuditActorServiceAccountApi {
    /** Service account id. */
    id: string
    /** Agent display name. */
    name: string
    /** Agent identity handle. */
    handle: string
}

export interface MCPAuditEventApi {
    readonly id: string
    readonly created_at: string
    /** Gateway server name at call time (denormalized). */
    readonly server_name: string
    /** Tool that was called. */
    readonly tool_name: string
    /** How the gateway decided the call.
     *
     * * `auto` - Auto-approved
     * * `approved` - Approved
     * * `pending` - Awaiting approval
     * * `blocked` - Blocked */
    readonly decision: MCPAuditDecisionEnumApi
    /** Member who made the call, if any. */
    readonly actor_user: UserBasicApi | null
    /** Agent that made the call, if any. Null for member calls. */
    readonly actor_service_account: AuditActorServiceAccountApi | null
    /** Denormalized actor label (email or handle) that survives deletion. */
    readonly actor_label: string
}

export interface PaginatedMCPAuditEventListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: MCPAuditEventApi[]
}

export interface AuditCountsApi {
    /** Every audited tool call. */
    all: number
    /** Calls made by service accounts. */
    agents: number
    /** Calls that were approved or are awaiting approval. */
    approvals: number
    /** Calls the gateway blocked. */
    blocked: number
}

/**
 * * `allow` - Allow all
 * * `user` - Member decides
 * * `ask` - Ask for destructive
 * * `block` - Block destructive
 */
export type MCPPolicyPresetEnumApi = (typeof MCPPolicyPresetEnumApi)[keyof typeof MCPPolicyPresetEnumApi]

export const MCPPolicyPresetEnumApi = {
    Allow: 'allow',
    User: 'user',
    Ask: 'ask',
    Block: 'block',
} as const

export const TeamMCPGatewayConfigApiMemberDefaultPreset = { ...MCPPolicyPresetEnumApi, ...BlankEnumApi } as const
export const TeamMCPGatewayConfigApiAgentDefaultPreset = { ...MCPPolicyPresetEnumApi, ...BlankEnumApi } as const
export interface TeamMCPGatewayConfigApi {
    /** Whether non-admin members may register custom MCP servers with the gateway. */
    allow_custom_servers?: boolean
    /** Baseline preset for members. Empty until an admin applies one from Team settings.
     *
     * * `allow` - Allow all
     * * `user` - Member decides
     * * `ask` - Ask for destructive
     * * `block` - Block destructive */
    member_default_preset?: (typeof TeamMCPGatewayConfigApiMemberDefaultPreset)[keyof typeof TeamMCPGatewayConfigApiMemberDefaultPreset]
    /** Baseline preset deriving default policies for tools an agent has no explicit row for.
     *
     * * `allow` - Allow all
     * * `user` - Member decides
     * * `ask` - Ask for destructive
     * * `block` - Block destructive */
    agent_default_preset?: (typeof TeamMCPGatewayConfigApiAgentDefaultPreset)[keyof typeof TeamMCPGatewayConfigApiAgentDefaultPreset]
    /** Whether the requesting user can administer the gateway (org admin or explicit project admin). */
    readonly is_admin: boolean
}

/**
 * * `members` - members
 * * `agents` - agents
 */
export type AudienceEnumApi = (typeof AudienceEnumApi)[keyof typeof AudienceEnumApi]

export const AudienceEnumApi = {
    Members: 'members',
    Agents: 'agents',
} as const

export interface ApplyPresetApi {
    /** Which audience's baseline to overwrite.
     *
     * * `members` - members
     * * `agents` - agents */
    audience: AudienceEnumApi
    /** Preset to apply.
     *
     * * `allow` - Allow all
     * * `user` - Member decides
     * * `ask` - Ask for destructive
     * * `block` - Block destructive */
    preset: MCPPolicyPresetEnumApi
}

export const GatewayConfigUpdateApiMemberDefaultPreset = { ...MCPPolicyPresetEnumApi, ...BlankEnumApi } as const
export const GatewayConfigUpdateApiAgentDefaultPreset = { ...MCPPolicyPresetEnumApi, ...BlankEnumApi } as const
export interface GatewayConfigUpdateApi {
    /** Whether non-admin members may register custom MCP servers. */
    allow_custom_servers?: boolean
    /** Baseline preset for members.
     *
     * * `allow` - Allow all
     * * `user` - Member decides
     * * `ask` - Ask for destructive
     * * `block` - Block destructive */
    member_default_preset?: (typeof GatewayConfigUpdateApiMemberDefaultPreset)[keyof typeof GatewayConfigUpdateApiMemberDefaultPreset]
    /** Baseline preset for agents.
     *
     * * `allow` - Allow all
     * * `user` - Member decides
     * * `ask` - Ask for destructive
     * * `block` - Block destructive */
    agent_default_preset?: (typeof GatewayConfigUpdateApiAgentDefaultPreset)[keyof typeof GatewayConfigUpdateApiAgentDefaultPreset]
}

/**
 * One team member's gateway posture (admin overview).
 */
export interface GatewayMemberSummaryApi {
    /** The member. */
    user: UserBasicApi
    /** Whether the member is an organization admin or owner. */
    is_org_admin: boolean
    /** Gateway servers the member has a personal connection to. */
    connected_server_ids: string[]
    /** Gateway servers an admin turned off for this member. */
    revoked_server_ids: string[]
}

export interface MemberAccessUpdateApi {
    /** Gateway server to toggle for the member. */
    gateway_server_id: string
    /** False turns the server off for the member; true restores it. */
    enabled: boolean
}

/**
 * * `everyone` - Everyone
 * * `members` - Members
 * * `agents` - Agents
 */
export type AppliesToEnumApi = (typeof AppliesToEnumApi)[keyof typeof AppliesToEnumApi]

export const AppliesToEnumApi = {
    Everyone: 'everyone',
    Members: 'members',
    Agents: 'agents',
} as const

/**
 * * `needs_approval` - Require approval
 * * `do_not_use` - Block
 */
export type EffectEnumApi = (typeof EffectEnumApi)[keyof typeof EffectEnumApi]

export const EffectEnumApi = {
    NeedsApproval: 'needs_approval',
    DoNotUse: 'do_not_use',
} as const

export interface MCPOrgRuleApi {
    readonly id: string
    /**
     * Short rule name shown wherever the rule locks a tool.
     * @maxLength 200
     */
    name: string
    /** Why this guardrail exists. */
    description?: string
    /** Audience the rule constrains.
     *
     * * `everyone` - Everyone
     * * `members` - Members
     * * `agents` - Agents */
    applies_to?: AppliesToEnumApi
    /** State the rule forces on matching tools.
     *
     * * `needs_approval` - Require approval
     * * `do_not_use` - Block */
    effect?: EffectEnumApi
    /**
     * fnmatch pattern against tool names. Blank matches destructive tools heuristically.
     * @maxLength 400
     */
    tool_pattern?: string
    /** Disabled rules are kept but not evaluated. */
    enabled?: boolean
    readonly created_at: string
    readonly updated_at: string
}

export interface PaginatedMCPOrgRuleListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: MCPOrgRuleApi[]
}

export interface PatchedMCPOrgRuleApi {
    readonly id?: string
    /**
     * Short rule name shown wherever the rule locks a tool.
     * @maxLength 200
     */
    name?: string
    /** Why this guardrail exists. */
    description?: string
    /** Audience the rule constrains.
     *
     * * `everyone` - Everyone
     * * `members` - Members
     * * `agents` - Agents */
    applies_to?: AppliesToEnumApi
    /** State the rule forces on matching tools.
     *
     * * `needs_approval` - Require approval
     * * `do_not_use` - Block */
    effect?: EffectEnumApi
    /**
     * fnmatch pattern against tool names. Blank matches destructive tools heuristically.
     * @maxLength 400
     */
    tool_pattern?: string
    /** Disabled rules are kept but not evaluated. */
    enabled?: boolean
    readonly created_at?: string
    readonly updated_at?: string
}

/**
 * * `business` - Business Operations
 * * `data` - Data & Analytics
 * * `design` - Design & Content
 * * `dev` - Developer Tools & APIs
 * * `infra` - Infrastructure
 * * `productivity` - Productivity & Collaboration
 */
export type MCPServerCategoryEnumApi = (typeof MCPServerCategoryEnumApi)[keyof typeof MCPServerCategoryEnumApi]

export const MCPServerCategoryEnumApi = {
    Business: 'business',
    Data: 'data',
    Design: 'design',
    Dev: 'dev',
    Infra: 'infra',
    Productivity: 'productivity',
} as const

/**
 * * `individual` - Individual accounts
 * * `shared` - Shared credential
 */
export type AuthModeEnumApi = (typeof AuthModeEnumApi)[keyof typeof AuthModeEnumApi]

export const AuthModeEnumApi = {
    Individual: 'individual',
    Shared: 'shared',
} as const

/**
 * One member's personal connection to a gateway server.
 */
export interface GatewayConnectionApi {
    /** Installation row backing this connection. */
    installation_id: string
    /** The member who connected. */
    user: UserBasicApi
    /**
     * When this connection last proxied a tool call. Null if never used.
     * @nullable
     */
    last_used_at: string | null
    /** True when the OAuth round-trip has not completed yet. */
    pending_oauth: boolean
    /** True when the stored token was invalidated and needs reauth. */
    needs_reauth: boolean
}

/**
 * * `personal` - personal
 * * `shared` - shared
 */
export type MCPInstallationScopeEnumApi = (typeof MCPInstallationScopeEnumApi)[keyof typeof MCPInstallationScopeEnumApi]

export const MCPInstallationScopeEnumApi = {
    Personal: 'personal',
    Shared: 'shared',
} as const

/**
 * The requesting user's own connection to a gateway server.
 */
export interface GatewayYourConnectionApi {
    /** The caller's installation row for this server. */
    installation_id: string
    /** Whether the caller connects personally or via the shared credential.
     *
     * * `personal` - personal
     * * `shared` - shared */
    scope: MCPInstallationScopeEnumApi
    /** Per-connection switch — false when self-disabled. */
    is_enabled: boolean
    /** True when the OAuth round-trip has not completed yet. */
    pending_oauth: boolean
    /** True when the stored token was invalidated and needs reauth. */
    needs_reauth: boolean
    /**
     * When the caller last proxied a call through this connection.
     * @nullable
     */
    last_used_at: string | null
}

/**
 * The admin-managed shared credential of a shared-auth server.
 */
export interface GatewaySharedCredentialApi {
    /** Shared installation row holding the credential. */
    installation_id: string
    /** Admin who connected the shared credential. */
    managed_by: UserBasicApi | null
    /** Whether the shared credential is enabled. */
    is_enabled: boolean
    /** True when the shared credential has not finished OAuth. */
    pending_oauth: boolean
    /** True when the shared credential needs re-authentication. */
    needs_reauth: boolean
    /**
     * When the shared credential last proxied a call.
     * @nullable
     */
    last_used_at: string | null
}

/**
 * * `active` - Active
 * * `paused` - Paused
 */
export type MCPServiceAccountStatusEnumApi =
    (typeof MCPServiceAccountStatusEnumApi)[keyof typeof MCPServiceAccountStatusEnumApi]

export const MCPServiceAccountStatusEnumApi = {
    Active: 'active',
    Paused: 'paused',
} as const

/**
 * One agent's access to a gateway server.
 */
export interface GatewayAgentAccessApi {
    /** Service account granted access. */
    service_account_id: string
    /** Agent display name. */
    name: string
    /** Agent identity handle, e.g. svc-support. */
    handle: string
    /** active, or paused (all access off).
     *
     * * `active` - Active
     * * `paused` - Paused */
    status: MCPServiceAccountStatusEnumApi
    /**
     * When the agent last made a call.
     * @nullable
     */
    last_active_at: string | null
    /** Admin who shared this server with the agent. */
    granted_by: UserBasicApi | null
}

/**
 * A server registered in the team's gateway, with connection summary.
 */
export interface MCPGatewayServerApi {
    readonly id: string
    readonly name: string
    readonly url: string
    readonly description: string
    readonly category: MCPServerCategoryEnumApi
    readonly auth_mode: AuthModeEnumApi
    readonly is_team_enabled: boolean
    readonly allow_personal_connections: boolean
    /** Lowercase key from the linked template for brand icons. Empty for custom servers. */
    readonly icon_key: string
    /** Documentation URL from the template. */
    readonly docs_url: string
    /**
     * Linked catalog template.
     * @nullable
     */
    readonly template_id: string | null
    /** Number of live tools known for this server. */
    readonly tool_count: number
    /** Members with a personal connection to this server. */
    readonly connections: readonly GatewayConnectionApi[]
    /** The requesting user's own connection, or null when not connected. */
    readonly your_connection: GatewayYourConnectionApi | null
    /** Shared credential details when auth_mode is shared, else null. */
    readonly shared_credential: GatewaySharedCredentialApi | null
    /** Agents this server is shared with. */
    readonly agents: readonly GatewayAgentAccessApi[]
    /** Ids of members whose access an admin has turned off. */
    readonly revoked_user_ids: readonly number[]
    /** True when an admin has turned this server off for the requesting user. */
    readonly is_revoked_for_you: boolean
    /** Who registered the server. */
    readonly created_by: UserBasicApi
    readonly created_at: string
    readonly updated_at: string
}

export interface PaginatedMCPGatewayServerListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: MCPGatewayServerApi[]
}

export interface MCPGatewayServerUpdateApi {
    /**
     * Display name shown across the gateway.
     * @maxLength 200
     */
    name?: string
    /** Short description shown on server cards. */
    description?: string
    /** Catalog category used for filter chips.
     *
     * * `business` - Business Operations
     * * `data` - Data & Analytics
     * * `design` - Design & Content
     * * `dev` - Developer Tools & APIs
     * * `infra` - Infrastructure
     * * `productivity` - Productivity & Collaboration */
    category?: MCPServerCategoryEnumApi
    /** Master switch — off means members and agents can neither see nor call the server. */
    is_team_enabled?: boolean
    /** For shared-credential servers: whether members may also connect their own account. */
    allow_personal_connections?: boolean
}

export interface PatchedMCPGatewayServerUpdateApi {
    /**
     * Display name shown across the gateway.
     * @maxLength 200
     */
    name?: string
    /** Short description shown on server cards. */
    description?: string
    /** Catalog category used for filter chips.
     *
     * * `business` - Business Operations
     * * `data` - Data & Analytics
     * * `design` - Design & Content
     * * `dev` - Developer Tools & APIs
     * * `infra` - Infrastructure
     * * `productivity` - Productivity & Collaboration */
    category?: MCPServerCategoryEnumApi
    /** Master switch — off means members and agents can neither see nor call the server. */
    is_team_enabled?: boolean
    /** For shared-credential servers: whether members may also connect their own account. */
    allow_personal_connections?: boolean
}

/**
 * * `team` - Team default
 * * `member` - Member
 * * `agent` - Agent
 */
export type ScopeTypeEnumApi = (typeof ScopeTypeEnumApi)[keyof typeof ScopeTypeEnumApi]

export const ScopeTypeEnumApi = {
    Team: 'team',
    Member: 'member',
    Agent: 'agent',
} as const

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

export interface ToolPolicyEntryApi {
    /** Tool to set the policy for. */
    tool_name: string
    /** State to apply for this scope.
     *
     * * `approved` - Approved
     * * `needs_approval` - Needs approval
     * * `do_not_use` - Do not use */
    policy_state: MCPToolApprovalStateEnumApi
}

export interface GatewayPoliciesUpsertApi {
    /** Which scope to resolve: the team default, one member, or one agent.
     *
     * * `team` - Team default
     * * `member` - Member
     * * `agent` - Agent */
    scope_type?: ScopeTypeEnumApi
    /** Member scope target. Defaults to the requesting user. */
    scope_user_id?: number
    /** Agent scope target. Required when scope_type is agent. */
    scope_service_account_id?: string
    /** Per-tool states to upsert for the scope. */
    policies: ToolPolicyEntryApi[]
}

/**
 * * `rule` - rule
 * * `scope` - scope
 * * `team` - team
 * * `preset` - preset
 * * `legacy` - legacy
 * * `default` - default
 */
export type DecidedByEnumApi = (typeof DecidedByEnumApi)[keyof typeof DecidedByEnumApi]

export const DecidedByEnumApi = {
    Rule: 'rule',
    Scope: 'scope',
    Team: 'team',
    Preset: 'preset',
    Legacy: 'legacy',
    Default: 'default',
} as const

/**
 * One tool with its effective policy for the requested scope.
 */
export interface ResolvedToolPolicyApi {
    /** Tool name as exposed by the upstream server. */
    tool_name: string
    /** Tool description from the upstream server. */
    description: string
    /** Effective state for the scope.
     *
     * * `approved` - Approved
     * * `needs_approval` - Needs approval
     * * `do_not_use` - Do not use */
    policy_state: MCPToolApprovalStateEnumApi
    /** What the team-level chain (row or preset) yields, ignoring the scope. Null when the team imposes nothing.
     *
     * * `approved` - Approved
     * * `needs_approval` - Needs approval
     * * `do_not_use` - Do not use */
    team_state: MCPToolApprovalStateEnumApi | null
    /** True when the requester can't change this row (rule match, or admin-imposed for a member). */
    locked: boolean
    /** Which policy layer decided the state.
     *
     * * `rule` - rule
     * * `scope` - scope
     * * `team` - team
     * * `preset` - preset
     * * `legacy` - legacy
     * * `default` - default */
    decided_by: DecidedByEnumApi
    /** Matching org rule name, when decided_by is rule. */
    rule_name: string
    /** Matching org rule description, when decided_by is rule. */
    rule_description: string
}

export interface PaginatedResolvedToolPolicyListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: ResolvedToolPolicyApi[]
}

export interface MCPServiceAccountApi {
    readonly id: string
    readonly name: string
    readonly description: string
    /** Stable identity handle the agent authenticates as, e.g. svc-docs-agent. */
    readonly handle: string
    /** active, or paused (all access off).
     *
     * * `active` - Active
     * * `paused` - Paused */
    readonly status: MCPServiceAccountStatusEnumApi
    /** Masked bearer token; the full token is only shown once. */
    readonly token_mask: string
    /** Gateway servers this agent has access to. */
    readonly server_ids: readonly string[]
    /**
     * When the agent last made a call through the gateway.
     * @nullable
     */
    readonly last_active_at: string | null
    readonly created_at: string
    readonly updated_at: string
}

export interface PaginatedMCPServiceAccountListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: MCPServiceAccountApi[]
}

export interface MCPServiceAccountCreateApi {
    /**
     * Agent display name, e.g. Docs Agent.
     * @maxLength 200
     */
    name: string
    /** What this agent does. */
    description?: string
}

export interface MCPServiceAccountWithTokenApi {
    readonly id: string
    readonly name: string
    readonly description: string
    /** Stable identity handle the agent authenticates as, e.g. svc-docs-agent. */
    readonly handle: string
    /** active, or paused (all access off).
     *
     * * `active` - Active
     * * `paused` - Paused */
    readonly status: MCPServiceAccountStatusEnumApi
    /** Masked bearer token; the full token is only shown once. */
    readonly token_mask: string
    /** Gateway servers this agent has access to. */
    readonly server_ids: readonly string[]
    /**
     * When the agent last made a call through the gateway.
     * @nullable
     */
    readonly last_active_at: string | null
    readonly created_at: string
    readonly updated_at: string
    /** The full bearer token. Returned exactly once — on creation or rotation. */
    readonly token: string
}

export interface MCPServiceAccountUpdateApi {
    /**
     * Agent display name.
     * @maxLength 200
     */
    name?: string
    /** What this agent does. */
    description?: string
    /** active, or paused (all access off).
     *
     * * `active` - Active
     * * `paused` - Paused */
    status?: MCPServiceAccountStatusEnumApi
}

export interface PatchedMCPServiceAccountUpdateApi {
    /**
     * Agent display name.
     * @maxLength 200
     */
    name?: string
    /** What this agent does. */
    description?: string
    /** active, or paused (all access off).
     *
     * * `active` - Active
     * * `paused` - Paused */
    status?: MCPServiceAccountStatusEnumApi
}

export interface ServiceAccountAccessUpdateApi {
    /** Gateway server to grant or revoke. */
    gateway_server_id: string
    /** True grants access, false revokes it. */
    enabled: boolean
    /** Optional agent-scope tool policies to set alongside the grant. */
    policies?: ToolPolicyEntryApi[]
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

/**
 * * `personal` - Personal
 * * `shared` - Shared
 */
export type MCPServerInstallationScopeEnumApi =
    (typeof MCPServerInstallationScopeEnumApi)[keyof typeof MCPServerInstallationScopeEnumApi]

export const MCPServerInstallationScopeEnumApi = {
    Personal: 'personal',
    Shared: 'shared',
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
    readonly scope: MCPServerInstallationScopeEnumApi
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
    /** Whether the server starts enabled for the whole team. Non-default values are admin-only. */
    team_enabled?: boolean
    /** For shared-credential servers: whether members may also connect personal accounts. Admin-only. */
    allow_personal?: boolean
    /** Service accounts to share the server with at install time. Admin-only. */
    agent_ids?: string[]
    /** In-app path to land back on after the OAuth round-trip. Must be a same-app relative path. */
    return_path?: string
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
    /** Whether the server starts enabled for the whole team. Non-default values are admin-only. */
    team_enabled?: boolean
    /** For shared-credential servers: whether members may also connect personal accounts. Admin-only. */
    allow_personal?: boolean
    /** Service accounts to share the server with at install time. Admin-only. */
    agent_ids?: string[]
    /** In-app path to land back on after the OAuth round-trip. Must be a same-app relative path. */
    return_path?: string
}

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
    category?: MCPServerCategoryEnumApi
}

export interface PaginatedMCPServerTemplateListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: MCPServerTemplateApi[]
}

export type McpGatewayAuditListParams = {
    /**
     * Only calls made by this service account.
     */
    actor_service_account_id?: string
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
    /**
     * all, agents (agent calls only), approvals (approved or pending), or blocked.
     *
     * * `all` - all
     * * `agents` - agents
     * * `approvals` - approvals
     * * `blocked` - blocked
     * @minLength 1
     */
    quick_filter?: McpGatewayAuditListQuickFilter
}

export type McpGatewayAuditListQuickFilter =
    (typeof McpGatewayAuditListQuickFilter)[keyof typeof McpGatewayAuditListQuickFilter]

export const McpGatewayAuditListQuickFilter = {
    All: 'all',
    Agents: 'agents',
    Approvals: 'approvals',
    Blocked: 'blocked',
} as const

export type McpGatewayRulesListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type McpGatewayServersListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type McpGatewayServersToolsRetrieveParams = {
    /**
     * Agent scope target. Required when scope_type is agent.
     */
    scope_service_account_id?: string
    /**
     * Which scope to resolve: the team default, one member, or one agent.
     *
     * * `team` - Team default
     * * `member` - Member
     * * `agent` - Agent
     * @minLength 1
     */
    scope_type?: McpGatewayServersToolsRetrieveScopeType
    /**
     * Member scope target. Defaults to the requesting user.
     */
    scope_user_id?: number
}

export type McpGatewayServersToolsRetrieveScopeType =
    (typeof McpGatewayServersToolsRetrieveScopeType)[keyof typeof McpGatewayServersToolsRetrieveScopeType]

export const McpGatewayServersToolsRetrieveScopeType = {
    Team: 'team',
    Member: 'member',
    Agent: 'agent',
} as const

export type McpGatewayServiceAccountsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
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
    /**
     * In-app path to land back on after the OAuth round-trip. Must be a same-app relative path.
     */
    return_path?: string
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
