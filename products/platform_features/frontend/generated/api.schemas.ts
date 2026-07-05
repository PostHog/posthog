/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
export type EffectiveMembershipLevelEnumApi =
    (typeof EffectiveMembershipLevelEnumApi)[keyof typeof EffectiveMembershipLevelEnumApi]

export const EffectiveMembershipLevelEnumApi = {
    Number1: 1,
    Number8: 8,
    Number15: 15,
} as const

/**
 * * `0` - none
 * * `3` - config
 * * `6` - install
 * * `9` - root
 */
export type PluginsAccessLevelEnumApi = (typeof PluginsAccessLevelEnumApi)[keyof typeof PluginsAccessLevelEnumApi]

export const PluginsAccessLevelEnumApi = {
    Number0: 0,
    Number3: 3,
    Number6: 6,
    Number9: 9,
} as const

/**
 * * `bayesian` - Bayesian
 * * `frequentist` - Frequentist
 */
export type DefaultExperimentStatsMethodEnumApi =
    (typeof DefaultExperimentStatsMethodEnumApi)[keyof typeof DefaultExperimentStatsMethodEnumApi]

export const DefaultExperimentStatsMethodEnumApi = {
    Bayesian: 'bayesian',
    Frequentist: 'frequentist',
} as const

export type BlankEnumApi = (typeof BlankEnumApi)[keyof typeof BlankEnumApi]

export const BlankEnumApi = {
    '': '',
} as const

export type OrganizationApiTeamsItem = { [key: string]: unknown }

export type OrganizationApiProjectsItem = { [key: string]: unknown }

export type OrganizationApiMetadata = { [key: string]: string }

export interface OrganizationApi {
    readonly id: string
    /** @maxLength 64 */
    name: string
    /** @pattern ^[-a-zA-Z0-9_]+$ */
    readonly slug: string
    /** @nullable */
    logo_media_id?: string | null
    readonly created_at: string
    readonly updated_at: string
    readonly membership_level: EffectiveMembershipLevelEnumApi
    readonly plugins_access_level: PluginsAccessLevelEnumApi
    readonly teams: readonly OrganizationApiTeamsItem[]
    readonly projects: readonly OrganizationApiProjectsItem[]
    /** @nullable */
    readonly available_product_features: readonly unknown[] | null
    /** Legacy field; member-join emails are controlled per user in account notification settings. */
    readonly is_member_join_email_enabled: boolean
    readonly metadata: OrganizationApiMetadata
    /** @nullable */
    readonly customer_id: string | null
    /** @nullable */
    enforce_2fa?: boolean | null
    /** @nullable */
    members_can_invite?: boolean | null
    /**
     * When True, organization members (below admin) are allowed to create new projects. Admins and owners can always create projects.
     * @nullable
     */
    members_can_create_projects?: boolean | null
    members_can_use_personal_api_keys?: boolean
    allow_publicly_shared_resources?: boolean
    readonly member_count: number
    /** @nullable */
    is_ai_data_processing_approved?: boolean | null
    /**
     * When True, this organization allows its data to be used to train PostHog AI models.
     * @nullable
     */
    is_ai_training_opted_in?: boolean | null
    /**
     * When True, the AI training opt-out setting cannot be modified through the UI or API.
     * @nullable
     */
    readonly is_ai_training_locked: boolean | null
    /**
     * When True, in-app callouts inviting members to enable AI training are shown.
     * @nullable
     */
    readonly is_ai_training_cta_shown: boolean | null
    /** @nullable */
    readonly is_hipaa: boolean | null
    /** Default statistical method for new experiments in this organization.
     *
     * * `bayesian` - Bayesian
     * * `frequentist` - Frequentist */
    default_experiment_stats_method?: DefaultExperimentStatsMethodEnumApi | BlankEnumApi | null
    /** Default setting for 'Discard client IP data' for new projects in this organization. */
    default_anonymize_ips?: boolean
    /**
     * ID of the role to automatically assign to new members joining the organization
     * @nullable
     */
    default_role_id?: string | null
    /**
     * Set this to 'No' to temporarily disable an organization.
     * @nullable
     */
    readonly is_active: boolean | null
    /**
     * (optional) reason for why the organization has been de-activated. This will be displayed to users on the web app.
     * @nullable
     */
    readonly is_not_active_reason: string | null
    /**
     * Set to True when org deletion has been initiated. Blocks all UI access until the async task completes.
     * @nullable
     */
    readonly is_pending_deletion: boolean | null
}

export interface PaginatedOrganizationListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: OrganizationApi[]
}

export type PatchedOrganizationApiTeamsItem = { [key: string]: unknown }

export type PatchedOrganizationApiProjectsItem = { [key: string]: unknown }

export type PatchedOrganizationApiMetadata = { [key: string]: string }

export interface PatchedOrganizationApi {
    readonly id?: string
    /** @maxLength 64 */
    name?: string
    /** @pattern ^[-a-zA-Z0-9_]+$ */
    readonly slug?: string
    /** @nullable */
    logo_media_id?: string | null
    readonly created_at?: string
    readonly updated_at?: string
    readonly membership_level?: EffectiveMembershipLevelEnumApi
    readonly plugins_access_level?: PluginsAccessLevelEnumApi
    readonly teams?: readonly PatchedOrganizationApiTeamsItem[]
    readonly projects?: readonly PatchedOrganizationApiProjectsItem[]
    /** @nullable */
    readonly available_product_features?: readonly unknown[] | null
    /** Legacy field; member-join emails are controlled per user in account notification settings. */
    readonly is_member_join_email_enabled?: boolean
    readonly metadata?: PatchedOrganizationApiMetadata
    /** @nullable */
    readonly customer_id?: string | null
    /** @nullable */
    enforce_2fa?: boolean | null
    /** @nullable */
    members_can_invite?: boolean | null
    /**
     * When True, organization members (below admin) are allowed to create new projects. Admins and owners can always create projects.
     * @nullable
     */
    members_can_create_projects?: boolean | null
    members_can_use_personal_api_keys?: boolean
    allow_publicly_shared_resources?: boolean
    readonly member_count?: number
    /** @nullable */
    is_ai_data_processing_approved?: boolean | null
    /**
     * When True, this organization allows its data to be used to train PostHog AI models.
     * @nullable
     */
    is_ai_training_opted_in?: boolean | null
    /**
     * When True, the AI training opt-out setting cannot be modified through the UI or API.
     * @nullable
     */
    readonly is_ai_training_locked?: boolean | null
    /**
     * When True, in-app callouts inviting members to enable AI training are shown.
     * @nullable
     */
    readonly is_ai_training_cta_shown?: boolean | null
    /** @nullable */
    readonly is_hipaa?: boolean | null
    /** Default statistical method for new experiments in this organization.
     *
     * * `bayesian` - Bayesian
     * * `frequentist` - Frequentist */
    default_experiment_stats_method?: DefaultExperimentStatsMethodEnumApi | BlankEnumApi | null
    /** Default setting for 'Discard client IP data' for new projects in this organization. */
    default_anonymize_ips?: boolean
    /**
     * ID of the role to automatically assign to new members joining the organization
     * @nullable
     */
    default_role_id?: string | null
    /**
     * Set this to 'No' to temporarily disable an organization.
     * @nullable
     */
    readonly is_active?: boolean | null
    /**
     * (optional) reason for why the organization has been de-activated. This will be displayed to users on the web app.
     * @nullable
     */
    readonly is_not_active_reason?: string | null
    /**
     * Set to True when org deletion has been initiated. Blocks all UI access until the async task completes.
     * @nullable
     */
    readonly is_pending_deletion?: boolean | null
}

export interface OrganizationAIAccessRequestResponseApi {
    /** Whether the access request was accepted and the organization admins were notified. */
    success: boolean
}

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

/**
 * * `1` - member
 * * `8` - administrator
 * * `15` - owner
 */
export type OrganizationMembershipLevelEnumApi =
    (typeof OrganizationMembershipLevelEnumApi)[keyof typeof OrganizationMembershipLevelEnumApi]

export const OrganizationMembershipLevelEnumApi = {
    Number1: 1,
    Number8: 8,
    Number15: 15,
} as const

export type SearchMatchTypeEnumApi = (typeof SearchMatchTypeEnumApi)[keyof typeof SearchMatchTypeEnumApi]

export const SearchMatchTypeEnumApi = {
    Exact: 'exact',
    Similar: 'similar',
} as const

export interface OrganizationMemberApi {
    readonly id: string
    readonly user: UserBasicApi
    level?: OrganizationMembershipLevelEnumApi
    readonly joined_at: string
    readonly updated_at: string
    readonly is_2fa_enabled: boolean
    readonly has_social_auth: boolean
    readonly last_login: string
    /** How this row matched the `search` query parameter: `exact` (the term is a case-insensitive substring of a searched field) or `similar` (a fuzzy trigram match only). Results are ordered exact-first. Null when the list is not filtered by `search`. */
    readonly search_match_type: SearchMatchTypeEnumApi | null
}

export interface PaginatedOrganizationMemberListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: OrganizationMemberApi[]
}

export interface PatchedOrganizationMemberApi {
    readonly id?: string
    readonly user?: UserBasicApi
    level?: OrganizationMembershipLevelEnumApi
    readonly joined_at?: string
    readonly updated_at?: string
    readonly is_2fa_enabled?: boolean
    readonly has_social_auth?: boolean
    readonly last_login?: string
    /** How this row matched the `search` query parameter: `exact` (the term is a case-insensitive substring of a searched field) or `similar` (a fuzzy trigram match only). Results are ordered exact-first. Null when the list is not filtered by `search`. */
    readonly search_match_type?: SearchMatchTypeEnumApi | null
}

export interface OrganizationMemberGithubLoginApi {
    /**
     * The member's GitHub username (login), resolved from their linked GitHub integration or OAuth identity. Null when the member has no GitHub identity linked.
     * @nullable
     */
    github_login: string | null
}

export interface OrganizationPersonalAPIKeyOwnerApi {
    /** First name of the key's owner. */
    readonly first_name: string
    /** Last name of the key's owner. */
    readonly last_name: string
    /** Email address of the key's owner. */
    readonly email: string
}

export interface OrganizationPersonalAPIKeyProjectScopeApi {
    /** Project (team) ID the key is scoped to. */
    id: number
    /** Name of the project the key is scoped to. */
    name: string
}

export interface OrganizationPersonalAPIKeyAccessScopeApi {
    /** Breadth of access: 'all' (every project the owner can reach), 'organization' (this whole organization), or 'projects' (specific projects listed under 'projects'). */
    type: string
    /** Projects within this organization the key is scoped to, present only when type is 'projects'. */
    projects?: OrganizationPersonalAPIKeyProjectScopeApi[]
}

export interface OrganizationPersonalAPIKeyApi {
    /** The organization member who owns this key. */
    readonly owner: OrganizationPersonalAPIKeyOwnerApi
    /** Masked, display-safe hint of the key value (e.g. 'phx_***1234'). Not the secret. The owner sees the same masked value in their own settings, so it can be used to identify a key. */
    readonly mask_value: string
    /** API scopes granted to the key, e.g. 'insight:read'. A single '*' means full access. */
    readonly scopes: readonly string[]
    /** Where the key's scopes apply within this organization. */
    readonly access_scope: OrganizationPersonalAPIKeyAccessScopeApi
    /**
     * When the key was last used to authenticate, if ever.
     * @nullable
     */
    readonly last_used_at: string | null
    /** When the key was created. */
    readonly created_at: string
}

export interface PaginatedOrganizationPersonalAPIKeyListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: OrganizationPersonalAPIKeyApi[]
}

export type RoleApiMembersItem = { [key: string]: unknown }

export interface RoleApi {
    readonly id: string
    /** @maxLength 200 */
    name: string
    readonly created_at: string
    readonly created_by: UserBasicApi
    /** Members assigned to this role */
    readonly members: readonly RoleApiMembersItem[]
    readonly is_default: boolean
}

export interface PaginatedRoleListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: RoleApi[]
}

export type PatchedRoleApiMembersItem = { [key: string]: unknown }

export interface PatchedRoleApi {
    readonly id?: string
    /** @maxLength 200 */
    name?: string
    readonly created_at?: string
    readonly created_by?: UserBasicApi
    /** Members assigned to this role */
    readonly members?: readonly PatchedRoleApiMembersItem[]
    readonly is_default?: boolean
}

export interface RoleMembershipApi {
    readonly id: string
    readonly role_id: string
    readonly organization_member: OrganizationMemberApi
    readonly user: UserBasicApi
    readonly joined_at: string
    readonly updated_at: string
    user_uuid: string
}

export interface PaginatedRoleMembershipListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: RoleMembershipApi[]
}

export interface _WelcomeInviterApi {
    name: string
    email: string
}

/**
 * * `today` - today
 * * `this_week` - this_week
 * * `inactive` - inactive
 * * `never` - never
 */
export type LastActiveEnumApi = (typeof LastActiveEnumApi)[keyof typeof LastActiveEnumApi]

export const LastActiveEnumApi = {
    Today: 'today',
    ThisWeek: 'this_week',
    Inactive: 'inactive',
    Never: 'never',
} as const

export interface _WelcomeTeamMemberApi {
    name: string
    email: string
    /** @nullable */
    avatar: string | null
    role: string
    last_active: LastActiveEnumApi
}

export interface _WelcomeRecentActivityApi {
    /** Scope.activity pair, e.g. 'Insight.created'. */
    type: string
    actor_name: string
    entity_name: string
    /** @nullable */
    entity_url: string | null
    timestamp: string
}

export interface _WelcomePopularDashboardApi {
    id: number
    name: string
    description: string
    team_id: number
    url: string
}

export interface _WelcomeSuggestedStepApi {
    label: string
    href: string
    reason: string
    docs_href?: string
    product_key?: string
}

export interface WelcomeResponseApi {
    organization_name: string
    inviter: _WelcomeInviterApi | null
    team_members: _WelcomeTeamMemberApi[]
    recent_activity: _WelcomeRecentActivityApi[]
    popular_dashboards: _WelcomePopularDashboardApi[]
    products_in_use: string[]
    suggested_next_steps: _WelcomeSuggestedStepApi[]
    is_organization_first_user: boolean
}

export interface ActivityLogApi {
    readonly id: string
    user: UserBasicApi
    /** is the date of this log item newer than the user's bookmark */
    readonly unread: boolean
    /**
     * @minimum 0
     * @maximum 2147483647
     * @nullable
     */
    team_id?: number | null
    /** @nullable */
    organization_id?: string | null
    /** @nullable */
    was_impersonated?: boolean | null
    /** @nullable */
    is_system?: boolean | null
    /**
     * @maxLength 32
     * @nullable
     */
    client?: string | null
    /** @nullable */
    ip_address?: string | null
    /** @maxLength 79 */
    activity: string
    /**
     * @maxLength 72
     * @nullable
     */
    item_id?: string | null
    /** @maxLength 79 */
    scope: string
    detail?: unknown
    created_at?: string
}

export interface PaginatedActivityLogListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: ActivityLogApi[]
}

/**
 * Discovered detail fields and their value distributions.
 */
export type AvailableFiltersResponseApiDetailFields = { [key: string]: unknown }

export type StaticFiltersApiUsersItem = { [key: string]: unknown }

export type StaticFiltersApiScopesItem = { [key: string]: unknown }

export type StaticFiltersApiActivitiesItem = { [key: string]: unknown }

export type StaticFiltersApiClientsItem = { [key: string]: unknown }

export interface StaticFiltersApi {
    /** Users who have logged activity. */
    users: StaticFiltersApiUsersItem[]
    /** Available activity scopes. */
    scopes: StaticFiltersApiScopesItem[]
    /** Available activity types. */
    activities: StaticFiltersApiActivitiesItem[]
    /** API clients that have generated activity (from x-posthog-client header). */
    clients: StaticFiltersApiClientsItem[]
}

export interface AvailableFiltersResponseApi {
    /** Pre-computed filter options for scopes, activities, and users. */
    static_filters: StaticFiltersApi
    /** Discovered detail fields and their value distributions. */
    detail_fields: AvailableFiltersResponseApiDetailFields
}

export interface ApprovalPolicyApi {
    readonly id: string
    /** @maxLength 128 */
    action_key: string
    conditions?: unknown
    approver_config: unknown
    allow_self_approve?: boolean
    bypass_org_membership_levels?: unknown
    bypass_roles?: string[]
    /** Auto-expire change requests after this duration */
    expires_after?: string
    enabled?: boolean
    readonly created_by: UserBasicApi
    readonly created_at: string
    /** @nullable */
    readonly updated_at: string | null
}

export interface PaginatedApprovalPolicyListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: ApprovalPolicyApi[]
}

export interface PatchedApprovalPolicyApi {
    readonly id?: string
    /** @maxLength 128 */
    action_key?: string
    conditions?: unknown
    approver_config?: unknown
    allow_self_approve?: boolean
    bypass_org_membership_levels?: unknown
    bypass_roles?: string[]
    /** Auto-expire change requests after this duration */
    expires_after?: string
    enabled?: boolean
    readonly created_by?: UserBasicApi
    readonly created_at?: string
    /** @nullable */
    readonly updated_at?: string | null
}

/**
 * * `valid` - Valid
 * * `invalid` - Invalid
 * * `expired` - Expired
 * * `stale` - Stale (resource changed)
 */
export type ValidationStatusEnumApi = (typeof ValidationStatusEnumApi)[keyof typeof ValidationStatusEnumApi]

export const ValidationStatusEnumApi = {
    Valid: 'valid',
    Invalid: 'invalid',
    Expired: 'expired',
    Stale: 'stale',
} as const

/**
 * * `pending` - Pending
 * * `approved` - Approved (awaiting application)
 * * `applied` - Applied
 * * `rejected` - Rejected
 * * `expired` - Expired
 * * `failed` - Failed to apply
 */
export type ChangeRequestStateEnumApi = (typeof ChangeRequestStateEnumApi)[keyof typeof ChangeRequestStateEnumApi]

export const ChangeRequestStateEnumApi = {
    Pending: 'pending',
    Approved: 'approved',
    Applied: 'applied',
    Rejected: 'rejected',
    Expired: 'expired',
    Failed: 'failed',
} as const

export type ChangeRequestApiApprovalsItem = { [key: string]: unknown }

export interface ChangeRequestApi {
    readonly id: string
    readonly action_key: string
    readonly action_version: number
    readonly resource_type: string
    /** @nullable */
    readonly resource_id: string | null
    readonly intent: unknown
    readonly intent_display: unknown
    readonly policy_snapshot: unknown
    readonly validation_status: ValidationStatusEnumApi
    readonly validation_errors: unknown
    /** @nullable */
    readonly validated_at: string | null
    readonly state: ChangeRequestStateEnumApi
    readonly created_by: UserBasicApi
    readonly applied_by: UserBasicApi
    readonly created_at: string
    /** @nullable */
    readonly updated_at: string | null
    readonly expires_at: string
    /** @nullable */
    readonly applied_at: string | null
    readonly apply_error: string
    readonly result_data: unknown
    readonly approvals: readonly ChangeRequestApiApprovalsItem[]
    /** Check if current user can approve this change request. */
    readonly can_approve: boolean
    readonly can_cancel: boolean
    /** Check if current user is the requester. */
    readonly is_requester: boolean
    /**
     * Get the current user's approval decision if they have voted.
     * @nullable
     */
    readonly user_decision: string | null
}

export interface PaginatedChangeRequestListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: ChangeRequestApi[]
}

export interface CommentApi {
    readonly id: string
    readonly created_by: UserBasicApi
    /** @nullable */
    deleted?: boolean | null
    mentions?: number[]
    slug?: string
    /** Whether this comment is an actionable task that can be marked complete. Tasks render with a checkbox in the UI and can be filtered as a separate kind. Cannot be set on replies (source_comment) or emoji reactions. Immutable after creation. */
    is_task?: boolean
    /** The user who marked this task complete. Null for open tasks and non-task comments. */
    readonly completed_by: UserBasicApi | null
    /** @nullable */
    content?: string | null
    rich_content?: unknown
    readonly version: number
    readonly created_at: string
    /**
     * @maxLength 72
     * @nullable
     */
    item_id?: string | null
    item_context?: unknown
    /** @maxLength 79 */
    scope: string
    /**
     * ISO timestamp when the task was marked complete. Only meaningful when is_task is true. Read-only — toggled via the /complete and /reopen actions, not via PATCH.
     * @nullable
     */
    readonly completed_at: string | null
    /** @nullable */
    source_comment?: string | null
}

export interface PaginatedCommentListApi {
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: CommentApi[]
}

export interface PatchedCommentApi {
    readonly id?: string
    readonly created_by?: UserBasicApi
    /** @nullable */
    deleted?: boolean | null
    mentions?: number[]
    slug?: string
    /** Whether this comment is an actionable task that can be marked complete. Tasks render with a checkbox in the UI and can be filtered as a separate kind. Cannot be set on replies (source_comment) or emoji reactions. Immutable after creation. */
    is_task?: boolean
    /** The user who marked this task complete. Null for open tasks and non-task comments. */
    readonly completed_by?: UserBasicApi | null
    /** @nullable */
    content?: string | null
    rich_content?: unknown
    readonly version?: number
    readonly created_at?: string
    /**
     * @maxLength 72
     * @nullable
     */
    item_id?: string | null
    item_context?: unknown
    /** @maxLength 79 */
    scope?: string
    /**
     * ISO timestamp when the task was marked complete. Only meaningful when is_task is true. Read-only — toggled via the /complete and /reopen actions, not via PATCH.
     * @nullable
     */
    readonly completed_at?: string | null
    /** @nullable */
    source_comment?: string | null
}

export interface PinnedSceneTabApi {
    /** Stable identifier for the tab. Generated client-side; safe to omit on create. */
    id?: string
    /** URL pathname the tab points at — for example `/project/123/dashboard/45` or `/project/123/insights`. Combined with `search` and `hash` to reconstruct the destination. */
    pathname?: string
    /** Query string portion of the URL, including the leading `?`. Empty string when there is no query. */
    search?: string
    /** Fragment portion of the URL, including the leading `#`. Empty string when there is no fragment. */
    hash?: string
    /** Default tab title derived from the destination scene. Used when `customTitle` is not set. */
    title?: string
    /**
     * Optional user-provided title that overrides `title` in the navigation UI.
     * @nullable
     */
    customTitle?: string | null
    /** Icon key shown next to the tab in the sidebar — for example `dashboard`, `insight`, `blank`. */
    iconType?: string
    /**
     * Scene identifier resolved from the pathname when known — used by the frontend for icon/title hints.
     * @nullable
     */
    sceneId?: string | null
    /**
     * Scene key (logic key) for the destination, paired with `sceneParams` for deeper routing context.
     * @nullable
     */
    sceneKey?: string | null
    /** Free-form scene parameters captured at pin time, used by the frontend to rehydrate the destination. */
    sceneParams?: unknown
    /** Whether this entry is pinned. Always coerced to true on save — pass true or omit. */
    pinned?: boolean
}

export interface PinnedSceneTabsApi {
    /** Ordered list of pinned navigation tabs shown in the sidebar for the authenticated user within the current team. Send the full list to replace the existing pins; omit to leave them unchanged. */
    tabs?: PinnedSceneTabApi[]
    /** Tab descriptor for the user's chosen home page — the destination opened when they click the PostHog logo or hit `/`. Set to a tab descriptor to pick a homepage, send `null` or `{}` to clear it and fall back to the project default. */
    homepage?: PinnedSceneTabApi | null
}

export interface PatchedPinnedSceneTabsApi {
    /** Ordered list of pinned navigation tabs shown in the sidebar for the authenticated user within the current team. Send the full list to replace the existing pins; omit to leave them unchanged. */
    tabs?: PinnedSceneTabApi[]
    /** Tab descriptor for the user's chosen home page — the destination opened when they click the PostHog logo or hit `/`. Set to a tab descriptor to pick a homepage, send `null` or `{}` to clear it and fall back to the project default. */
    homepage?: PinnedSceneTabApi | null
}

export type ListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type MembersListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
    /**
     * Sort order. Defaults to `-joined_at`.
     */
    order?: string
    /**
     * Match against member `first_name`, `last_name`, and `email`. Returns case-insensitive substring matches and fuzzy trigram matches (typos, prefix-as-you-type) together, ordered exact-first; each result's `search_match_type` is `exact` or `similar`. Capped at 200 characters.
     */
    search?: string
}

export type PersonalApiKeysListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type RolesListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type RolesRoleMembershipsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type ActivityLogListParams = {
    /**
     * Filter by the ID of the affected resource.
     * @minLength 1
     */
    item_id?: string
    /**
     * Page number for pagination. When provided, uses page-based pagination ordered by most recent first.
     * @minimum 1
     */
    page?: number
    /**
     * Number of results per page (default: 100, max: 1000). Only used with page-based pagination.
     * @minimum 1
     * @maximum 1000
     */
    page_size?: number
    /**
     * Filter by a single activity scope, e.g. "FeatureFlag", "Insight", "Dashboard", "Experiment".
     *
     * * `Cohort` - Cohort
     * * `FeatureFlag` - FeatureFlag
     * * `Person` - Person
     * * `Group` - Group
     * * `Insight` - Insight
     * * `Plugin` - Plugin
     * * `PluginConfig` - PluginConfig
     * * `HogFunction` - HogFunction
     * * `HogFlow` - HogFlow
     * * `DataManagement` - DataManagement
     * * `EventDefinition` - EventDefinition
     * * `PropertyDefinition` - PropertyDefinition
     * * `Notebook` - Notebook
     * * `Endpoint` - Endpoint
     * * `EndpointVersion` - EndpointVersion
     * * `Dashboard` - Dashboard
     * * `Replay` - Replay
     * * `Experiment` - Experiment
     * * `ExperimentHoldout` - ExperimentHoldout
     * * `ExperimentSavedMetric` - ExperimentSavedMetric
     * * `Survey` - Survey
     * * `EarlyAccessFeature` - EarlyAccessFeature
     * * `SessionRecordingPlaylist` - SessionRecordingPlaylist
     * * `Comment` - Comment
     * * `Team` - Team
     * * `Project` - Project
     * * `ErrorTrackingIssue` - ErrorTrackingIssue
     * * `DataWarehouseSavedQuery` - DataWarehouseSavedQuery
     * * `LegalDocument` - LegalDocument
     * * `Organization` - Organization
     * * `OrganizationDomain` - OrganizationDomain
     * * `OrganizationMembership` - OrganizationMembership
     * * `Role` - Role
     * * `UserGroup` - UserGroup
     * * `BatchExport` - BatchExport
     * * `BatchImport` - BatchImport
     * * `ExportedAsset` - ExportedAsset
     * * `Integration` - Integration
     * * `Annotation` - Annotation
     * * `Tag` - Tag
     * * `TaggedItem` - TaggedItem
     * * `Subscription` - Subscription
     * * `PersonalAPIKey` - PersonalAPIKey
     * * `ProjectSecretAPIKey` - ProjectSecretAPIKey
     * * `OAuthApplication` - OAuthApplication
     * * `User` - User
     * * `Action` - Action
     * * `AlertConfiguration` - AlertConfiguration
     * * `Threshold` - Threshold
     * * `AlertSubscription` - AlertSubscription
     * * `ExternalDataSource` - ExternalDataSource
     * * `ExternalDataSchema` - ExternalDataSchema
     * * `Evaluation` - Evaluation
     * * `LLMTrace` - LLMTrace
     * * `WebAnalyticsFilterPreset` - WebAnalyticsFilterPreset
     * * `CustomerProfileConfig` - CustomerProfileConfig
     * * `Log` - Log
     * * `LogsAlertConfiguration` - LogsAlertConfiguration
     * * `LogsExclusionRule` - LogsExclusionRule
     * * `DashboardWidget` - DashboardWidget
     * * `ProductTour` - ProductTour
     * * `Ticket` - Ticket
     * * `InstanceSetting` - InstanceSetting
     * * `SignalReport` - SignalReport
     * * `SignalScoutConfig` - SignalScoutConfig
     * @minLength 1
     */
    scope?: ActivityLogListScope
    /**
     * Filter by multiple activity scopes, comma-separated. Values must be valid ActivityScope enum values. E.g. "FeatureFlag,Insight".
     */
    scopes?: ActivityLogListScopesItem[]
    /**
     * Filter by user UUID who performed the action.
     */
    user?: string
}

export type ActivityLogListScope = (typeof ActivityLogListScope)[keyof typeof ActivityLogListScope]

export const ActivityLogListScope = {
    Cohort: 'Cohort',
    FeatureFlag: 'FeatureFlag',
    Person: 'Person',
    Group: 'Group',
    Insight: 'Insight',
    Plugin: 'Plugin',
    PluginConfig: 'PluginConfig',
    HogFunction: 'HogFunction',
    HogFlow: 'HogFlow',
    DataManagement: 'DataManagement',
    EventDefinition: 'EventDefinition',
    PropertyDefinition: 'PropertyDefinition',
    Notebook: 'Notebook',
    Endpoint: 'Endpoint',
    EndpointVersion: 'EndpointVersion',
    Dashboard: 'Dashboard',
    Replay: 'Replay',
    Experiment: 'Experiment',
    ExperimentHoldout: 'ExperimentHoldout',
    ExperimentSavedMetric: 'ExperimentSavedMetric',
    Survey: 'Survey',
    EarlyAccessFeature: 'EarlyAccessFeature',
    SessionRecordingPlaylist: 'SessionRecordingPlaylist',
    Comment: 'Comment',
    Team: 'Team',
    Project: 'Project',
    ErrorTrackingIssue: 'ErrorTrackingIssue',
    DataWarehouseSavedQuery: 'DataWarehouseSavedQuery',
    LegalDocument: 'LegalDocument',
    Organization: 'Organization',
    OrganizationDomain: 'OrganizationDomain',
    OrganizationMembership: 'OrganizationMembership',
    Role: 'Role',
    UserGroup: 'UserGroup',
    BatchExport: 'BatchExport',
    BatchImport: 'BatchImport',
    ExportedAsset: 'ExportedAsset',
    Integration: 'Integration',
    Annotation: 'Annotation',
    Tag: 'Tag',
    TaggedItem: 'TaggedItem',
    Subscription: 'Subscription',
    PersonalAPIKey: 'PersonalAPIKey',
    ProjectSecretAPIKey: 'ProjectSecretAPIKey',
    OAuthApplication: 'OAuthApplication',
    User: 'User',
    Action: 'Action',
    AlertConfiguration: 'AlertConfiguration',
    Threshold: 'Threshold',
    AlertSubscription: 'AlertSubscription',
    ExternalDataSource: 'ExternalDataSource',
    ExternalDataSchema: 'ExternalDataSchema',
    Evaluation: 'Evaluation',
    LLMTrace: 'LLMTrace',
    WebAnalyticsFilterPreset: 'WebAnalyticsFilterPreset',
    CustomerProfileConfig: 'CustomerProfileConfig',
    Log: 'Log',
    LogsAlertConfiguration: 'LogsAlertConfiguration',
    LogsExclusionRule: 'LogsExclusionRule',
    DashboardWidget: 'DashboardWidget',
    ProductTour: 'ProductTour',
    Ticket: 'Ticket',
    InstanceSetting: 'InstanceSetting',
    SignalReport: 'SignalReport',
    SignalScoutConfig: 'SignalScoutConfig',
} as const

/**
 * * `Cohort` - Cohort
 * * `FeatureFlag` - FeatureFlag
 * * `Person` - Person
 * * `Group` - Group
 * * `Insight` - Insight
 * * `Plugin` - Plugin
 * * `PluginConfig` - PluginConfig
 * * `HogFunction` - HogFunction
 * * `HogFlow` - HogFlow
 * * `DataManagement` - DataManagement
 * * `EventDefinition` - EventDefinition
 * * `PropertyDefinition` - PropertyDefinition
 * * `Notebook` - Notebook
 * * `Endpoint` - Endpoint
 * * `EndpointVersion` - EndpointVersion
 * * `Dashboard` - Dashboard
 * * `Replay` - Replay
 * * `Experiment` - Experiment
 * * `ExperimentHoldout` - ExperimentHoldout
 * * `ExperimentSavedMetric` - ExperimentSavedMetric
 * * `Survey` - Survey
 * * `EarlyAccessFeature` - EarlyAccessFeature
 * * `SessionRecordingPlaylist` - SessionRecordingPlaylist
 * * `Comment` - Comment
 * * `Team` - Team
 * * `Project` - Project
 * * `ErrorTrackingIssue` - ErrorTrackingIssue
 * * `DataWarehouseSavedQuery` - DataWarehouseSavedQuery
 * * `LegalDocument` - LegalDocument
 * * `Organization` - Organization
 * * `OrganizationDomain` - OrganizationDomain
 * * `OrganizationMembership` - OrganizationMembership
 * * `Role` - Role
 * * `UserGroup` - UserGroup
 * * `BatchExport` - BatchExport
 * * `BatchImport` - BatchImport
 * * `ExportedAsset` - ExportedAsset
 * * `Integration` - Integration
 * * `Annotation` - Annotation
 * * `Tag` - Tag
 * * `TaggedItem` - TaggedItem
 * * `Subscription` - Subscription
 * * `PersonalAPIKey` - PersonalAPIKey
 * * `ProjectSecretAPIKey` - ProjectSecretAPIKey
 * * `OAuthApplication` - OAuthApplication
 * * `User` - User
 * * `Action` - Action
 * * `AlertConfiguration` - AlertConfiguration
 * * `Threshold` - Threshold
 * * `AlertSubscription` - AlertSubscription
 * * `ExternalDataSource` - ExternalDataSource
 * * `ExternalDataSchema` - ExternalDataSchema
 * * `Evaluation` - Evaluation
 * * `LLMTrace` - LLMTrace
 * * `WebAnalyticsFilterPreset` - WebAnalyticsFilterPreset
 * * `CustomerProfileConfig` - CustomerProfileConfig
 * * `Log` - Log
 * * `LogsAlertConfiguration` - LogsAlertConfiguration
 * * `LogsExclusionRule` - LogsExclusionRule
 * * `DashboardWidget` - DashboardWidget
 * * `ProductTour` - ProductTour
 * * `Ticket` - Ticket
 * * `InstanceSetting` - InstanceSetting
 * * `SignalReport` - SignalReport
 * * `SignalScoutConfig` - SignalScoutConfig
 */
export type ActivityLogListScopesItem = (typeof ActivityLogListScopesItem)[keyof typeof ActivityLogListScopesItem]

export const ActivityLogListScopesItem = {
    Cohort: 'Cohort',
    FeatureFlag: 'FeatureFlag',
    Person: 'Person',
    Group: 'Group',
    Insight: 'Insight',
    Plugin: 'Plugin',
    PluginConfig: 'PluginConfig',
    HogFunction: 'HogFunction',
    HogFlow: 'HogFlow',
    DataManagement: 'DataManagement',
    EventDefinition: 'EventDefinition',
    PropertyDefinition: 'PropertyDefinition',
    Notebook: 'Notebook',
    Endpoint: 'Endpoint',
    EndpointVersion: 'EndpointVersion',
    Dashboard: 'Dashboard',
    Replay: 'Replay',
    Experiment: 'Experiment',
    ExperimentHoldout: 'ExperimentHoldout',
    ExperimentSavedMetric: 'ExperimentSavedMetric',
    Survey: 'Survey',
    EarlyAccessFeature: 'EarlyAccessFeature',
    SessionRecordingPlaylist: 'SessionRecordingPlaylist',
    Comment: 'Comment',
    Team: 'Team',
    Project: 'Project',
    ErrorTrackingIssue: 'ErrorTrackingIssue',
    DataWarehouseSavedQuery: 'DataWarehouseSavedQuery',
    LegalDocument: 'LegalDocument',
    Organization: 'Organization',
    OrganizationDomain: 'OrganizationDomain',
    OrganizationMembership: 'OrganizationMembership',
    Role: 'Role',
    UserGroup: 'UserGroup',
    BatchExport: 'BatchExport',
    BatchImport: 'BatchImport',
    ExportedAsset: 'ExportedAsset',
    Integration: 'Integration',
    Annotation: 'Annotation',
    Tag: 'Tag',
    TaggedItem: 'TaggedItem',
    Subscription: 'Subscription',
    PersonalAPIKey: 'PersonalAPIKey',
    ProjectSecretAPIKey: 'ProjectSecretAPIKey',
    OAuthApplication: 'OAuthApplication',
    User: 'User',
    Action: 'Action',
    AlertConfiguration: 'AlertConfiguration',
    Threshold: 'Threshold',
    AlertSubscription: 'AlertSubscription',
    ExternalDataSource: 'ExternalDataSource',
    ExternalDataSchema: 'ExternalDataSchema',
    Evaluation: 'Evaluation',
    LLMTrace: 'LLMTrace',
    WebAnalyticsFilterPreset: 'WebAnalyticsFilterPreset',
    CustomerProfileConfig: 'CustomerProfileConfig',
    Log: 'Log',
    LogsAlertConfiguration: 'LogsAlertConfiguration',
    LogsExclusionRule: 'LogsExclusionRule',
    DashboardWidget: 'DashboardWidget',
    ProductTour: 'ProductTour',
    Ticket: 'Ticket',
    InstanceSetting: 'InstanceSetting',
    SignalReport: 'SignalReport',
    SignalScoutConfig: 'SignalScoutConfig',
} as const

export type AdvancedActivityLogsListParams = {
    /**
     * Filter by activity types (e.g. "created", "updated", "deleted").
     */
    activities?: string[]
    /**
     * Filter by API clients that generated the activity (from x-posthog-client header).
     */
    clients?: string[]
    /**
     * JSON-encoded map of `detail` field paths to {operation, value} filters. Allowed operations: exact, contains, in.
     */
    detail_filters?: string
    /**
     * Upper bound on `created_at` (inclusive), ISO-8601.
     */
    end_date?: string
    /**
     * Reserved for future HogQL-based filtering.
     */
    hogql_filter?: string
    /**
     * Filter by client IP addresses. Accepts exact IPv4/IPv6 values or wildcard patterns using `*` (e.g. `203.0.113.*`). Multiple entries are OR-combined.
     */
    ip_addresses?: string[]
    /**
     * When set, filters rows authored by the system (no user).
     * @nullable
     */
    is_system?: boolean | null
    /**
     * Filter by the `item_id` of the affected resource(s).
     */
    item_ids?: string[]
    /**
     * Page number for pagination. When provided, uses page-based pagination ordered by most recent first.
     * @minimum 1
     */
    page?: number
    /**
     * Number of results per page (default: 100, max: 1000). Only used with page-based pagination.
     * @minimum 1
     * @maximum 1000
     */
    page_size?: number
    /**
     * Filter by activity scopes (e.g. "FeatureFlag", "Insight").
     */
    scopes?: string[]
    /**
     * Free-text search across the `detail` JSON column.
     */
    search_text?: string
    /**
     * Lower bound on `created_at` (inclusive), ISO-8601.
     */
    start_date?: string
    /**
     * Filter by project (team) IDs. Only honored on the organization-scoped endpoint; ignored on the project-scoped endpoint.
     */
    team_ids?: number[]
    /**
     * Filter by users who performed the activity (user UUIDs).
     */
    users?: string[]
    /**
     * When set, filters rows where the actor was impersonating another user.
     * @nullable
     */
    was_impersonated?: boolean | null
}

export type AdvancedActivityLogsAvailableFiltersRetrieveParams = {
    /**
     * Whether to include the per-scope `detail_fields` enumeration. This section can be very large on projects with a lot of activity (it grows with the number of distinct detail keys seen), so set it to false to return only the compact `static_filters` (scopes, activities, users, clients).
     */
    include_detail_fields?: boolean
}

export type ApprovalPoliciesListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type ChangeRequestsListParams = {
    action_key?: string
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
    requester?: number
    resource_id?: string
    resource_type?: string
    /**
     * Multiple values may be separated by commas.
     */
    state?: string[]
}

export type CommentsListParams = {
    /**
     * When kind=task, restrict to open (incomplete) or completed tasks. Ignored when kind is not 'task'. Defaults to 'any' (no filter).
     *
     * * `any` - any
     * * `open` - open
     * * `completed` - completed
     * @minLength 1
     */
    completed?: CommentsListCompleted
    /**
     * The pagination cursor value.
     */
    cursor?: string
    /**
     * Filter by the ID of the resource being commented on.
     * @minLength 1
     */
    item_id?: string
    /**
     * Filter by comment kind. 'task' returns only items intentionally created as actionable. 'comment' excludes tasks. Defaults to 'any' (no filter).
     *
     * * `any` - any
     * * `comment` - comment
     * * `task` - task
     * @minLength 1
     */
    kind?: CommentsListKind
    /**
     * Filter by resource type (e.g. Dashboard, FeatureFlag, Insight, Replay).
     * @minLength 1
     */
    scope?: string
    /**
     * Full-text search within comment content.
     * @minLength 1
     */
    search?: string
    /**
     * Filter replies to a specific parent comment.
     * @minLength 1
     */
    source_comment?: string
}

export type CommentsListCompleted = (typeof CommentsListCompleted)[keyof typeof CommentsListCompleted]

export const CommentsListCompleted = {
    Any: 'any',
    Open: 'open',
    Completed: 'completed',
} as const

export type CommentsListKind = (typeof CommentsListKind)[keyof typeof CommentsListKind]

export const CommentsListKind = {
    Any: 'any',
    Comment: 'comment',
    Task: 'task',
} as const
