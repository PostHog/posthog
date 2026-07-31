/**
 * Auto-generated Zod validation schemas from the Django backend OpenAPI schema.
 * To modify these schemas, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import { z as zod } from 'zod'

export const EffectiveMembershipLevelEnumApi = zod.union([zod.literal(1), zod.literal(8), zod.literal(15)])

export type EffectiveMembershipLevelEnumApi = zod.input<typeof EffectiveMembershipLevelEnumApi>
export type EffectiveMembershipLevelEnumApiOutput = zod.output<typeof EffectiveMembershipLevelEnumApi>

export const PluginsAccessLevelEnumApi = zod
    .union([zod.literal(0), zod.literal(3), zod.literal(6), zod.literal(9)])
    .describe('\* `0` - none\n\* `3` - config\n\* `6` - install\n\* `9` - root')

export type PluginsAccessLevelEnumApi = zod.input<typeof PluginsAccessLevelEnumApi>
export type PluginsAccessLevelEnumApiOutput = zod.output<typeof PluginsAccessLevelEnumApi>

export const DefaultExperimentStatsMethodEnumApi = zod
    .enum(['bayesian', 'frequentist'])
    .describe('\* `bayesian` - Bayesian\n\* `frequentist` - Frequentist')

export type DefaultExperimentStatsMethodEnumApi = zod.input<typeof DefaultExperimentStatsMethodEnumApi>
export type DefaultExperimentStatsMethodEnumApiOutput = zod.output<typeof DefaultExperimentStatsMethodEnumApi>

export const BlankEnumApi = zod.enum([''])

export type BlankEnumApi = zod.input<typeof BlankEnumApi>
export type BlankEnumApiOutput = zod.output<typeof BlankEnumApi>

export const organizationApiNameMax = 64

export const organizationApiSlugRegExp = new RegExp('^[-a-zA-Z0-9_]+$')

export const OrganizationApi = zod.object({
    id: zod.uuid(),
    name: zod.string().max(organizationApiNameMax),
    slug: zod.string().regex(organizationApiSlugRegExp),
    logo_media_id: zod.uuid().nullish(),
    created_at: zod.iso.datetime({ offset: true }),
    updated_at: zod.iso.datetime({ offset: true }),
    membership_level: EffectiveMembershipLevelEnumApi,
    plugins_access_level: PluginsAccessLevelEnumApi,
    teams: zod.array(zod.record(zod.string(), zod.unknown())),
    projects: zod.array(zod.record(zod.string(), zod.unknown())),
    available_product_features: zod.array(zod.unknown()).nullable(),
    is_member_join_email_enabled: zod
        .boolean()
        .describe('Legacy field; member-join emails are controlled per user in account notification settings.'),
    metadata: zod.record(zod.string(), zod.string()),
    customer_id: zod.string().nullable(),
    enforce_2fa: zod.boolean().nullish(),
    members_can_invite: zod.boolean().nullish(),
    members_can_create_projects: zod
        .boolean()
        .nullish()
        .describe(
            'When True, organization members (below admin) are allowed to create new projects. Admins and owners can always create projects.'
        ),
    members_can_use_personal_api_keys: zod.boolean().optional(),
    members_can_see_org_members: zod
        .boolean()
        .optional()
        .describe(
            'When False, members (below admin) only see themselves in the members list and only project members in access control.'
        ),
    allow_publicly_shared_resources: zod.boolean().optional(),
    member_count: zod.number(),
    is_ai_data_processing_approved: zod.boolean().nullish(),
    is_ai_training_opted_in: zod
        .boolean()
        .nullish()
        .describe('When True, this organization allows its data to be used to train PostHog AI models.'),
    is_ai_training_locked: zod
        .boolean()
        .nullable()
        .describe('When True, the AI training opt-out setting cannot be modified through the UI or API.'),
    is_ai_training_cta_shown: zod
        .boolean()
        .nullable()
        .describe('When True, in-app callouts inviting members to enable AI training are shown.'),
    is_hipaa: zod.boolean().nullable(),
    default_experiment_stats_method: zod
        .union([DefaultExperimentStatsMethodEnumApi, BlankEnumApi, zod.null()])
        .optional()
        .describe(
            'Default statistical method for new experiments in this organization.\n\n\* `bayesian` - Bayesian\n\* `frequentist` - Frequentist'
        ),
    default_anonymize_ips: zod
        .boolean()
        .optional()
        .describe("Default setting for 'Discard client IP data' for new projects in this organization."),
    default_role_id: zod
        .string()
        .nullish()
        .describe('ID of the role to automatically assign to new members joining the organization'),
    is_active: zod.boolean().nullable().describe("Set this to 'No' to temporarily disable an organization."),
    is_not_active_reason: zod
        .string()
        .nullable()
        .describe(
            '(optional) reason for why the organization has been de-activated. This will be displayed to users on the web app.'
        ),
    is_pending_deletion: zod
        .boolean()
        .nullable()
        .describe(
            'Set to True when org deletion has been initiated. Blocks all UI access until the async task completes.'
        ),
})

export type OrganizationApi = zod.input<typeof OrganizationApi>
export type OrganizationApiOutput = zod.output<typeof OrganizationApi>

export const PaginatedOrganizationListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(OrganizationApi),
})

export type PaginatedOrganizationListApi = zod.input<typeof PaginatedOrganizationListApi>
export type PaginatedOrganizationListApiOutput = zod.output<typeof PaginatedOrganizationListApi>

export const patchedOrganizationApiNameMax = 64

export const patchedOrganizationApiSlugRegExp = new RegExp('^[-a-zA-Z0-9_]+$')

export const PatchedOrganizationApi = zod.object({
    id: zod.uuid().optional(),
    name: zod.string().max(patchedOrganizationApiNameMax).optional(),
    slug: zod.string().regex(patchedOrganizationApiSlugRegExp).optional(),
    logo_media_id: zod.uuid().nullish(),
    created_at: zod.iso.datetime({ offset: true }).optional(),
    updated_at: zod.iso.datetime({ offset: true }).optional(),
    membership_level: EffectiveMembershipLevelEnumApi.optional(),
    plugins_access_level: PluginsAccessLevelEnumApi.optional(),
    teams: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
    projects: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
    available_product_features: zod.array(zod.unknown()).nullish(),
    is_member_join_email_enabled: zod
        .boolean()
        .optional()
        .describe('Legacy field; member-join emails are controlled per user in account notification settings.'),
    metadata: zod.record(zod.string(), zod.string()).optional(),
    customer_id: zod.string().nullish(),
    enforce_2fa: zod.boolean().nullish(),
    members_can_invite: zod.boolean().nullish(),
    members_can_create_projects: zod
        .boolean()
        .nullish()
        .describe(
            'When True, organization members (below admin) are allowed to create new projects. Admins and owners can always create projects.'
        ),
    members_can_use_personal_api_keys: zod.boolean().optional(),
    members_can_see_org_members: zod
        .boolean()
        .optional()
        .describe(
            'When False, members (below admin) only see themselves in the members list and only project members in access control.'
        ),
    allow_publicly_shared_resources: zod.boolean().optional(),
    member_count: zod.number().optional(),
    is_ai_data_processing_approved: zod.boolean().nullish(),
    is_ai_training_opted_in: zod
        .boolean()
        .nullish()
        .describe('When True, this organization allows its data to be used to train PostHog AI models.'),
    is_ai_training_locked: zod
        .boolean()
        .nullish()
        .describe('When True, the AI training opt-out setting cannot be modified through the UI or API.'),
    is_ai_training_cta_shown: zod
        .boolean()
        .nullish()
        .describe('When True, in-app callouts inviting members to enable AI training are shown.'),
    is_hipaa: zod.boolean().nullish(),
    default_experiment_stats_method: zod
        .union([DefaultExperimentStatsMethodEnumApi, BlankEnumApi, zod.null()])
        .optional()
        .describe(
            'Default statistical method for new experiments in this organization.\n\n\* `bayesian` - Bayesian\n\* `frequentist` - Frequentist'
        ),
    default_anonymize_ips: zod
        .boolean()
        .optional()
        .describe("Default setting for 'Discard client IP data' for new projects in this organization."),
    default_role_id: zod
        .string()
        .nullish()
        .describe('ID of the role to automatically assign to new members joining the organization'),
    is_active: zod.boolean().nullish().describe("Set this to 'No' to temporarily disable an organization."),
    is_not_active_reason: zod
        .string()
        .nullish()
        .describe(
            '(optional) reason for why the organization has been de-activated. This will be displayed to users on the web app.'
        ),
    is_pending_deletion: zod
        .boolean()
        .nullish()
        .describe(
            'Set to True when org deletion has been initiated. Blocks all UI access until the async task completes.'
        ),
})

export type PatchedOrganizationApi = zod.input<typeof PatchedOrganizationApi>
export type PatchedOrganizationApiOutput = zod.output<typeof PatchedOrganizationApi>

export const OrganizationAIAccessRequestResponseApi = zod.object({
    success: zod
        .boolean()
        .describe('Whether the access request was accepted and the organization admins were notified.'),
})

export type OrganizationAIAccessRequestResponseApi = zod.input<typeof OrganizationAIAccessRequestResponseApi>
export type OrganizationAIAccessRequestResponseApiOutput = zod.output<typeof OrganizationAIAccessRequestResponseApi>

export const RoleAtOrganizationEnumApi = zod
    .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
    .describe(
        '\* `engineering` - Engineering\n\* `data` - Data\n\* `product` - Product Management\n\* `founder` - Founder\n\* `leadership` - Leadership\n\* `marketing` - Marketing\n\* `sales` - Sales \/ Success\n\* `other` - Other'
    )

export type RoleAtOrganizationEnumApi = zod.input<typeof RoleAtOrganizationEnumApi>
export type RoleAtOrganizationEnumApiOutput = zod.output<typeof RoleAtOrganizationEnumApi>

export const userBasicApiDistinctIdMax = 200

export const userBasicApiFirstNameMax = 150

export const userBasicApiLastNameMax = 150

export const userBasicApiEmailMax = 254

export const UserBasicApi = zod.object({
    id: zod.number(),
    uuid: zod.uuid(),
    distinct_id: zod.string().max(userBasicApiDistinctIdMax).nullish(),
    first_name: zod.string().max(userBasicApiFirstNameMax).optional(),
    last_name: zod.string().max(userBasicApiLastNameMax).optional(),
    email: zod.email().max(userBasicApiEmailMax),
    is_email_verified: zod.boolean().nullish(),
    hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
    role_at_organization: zod.union([RoleAtOrganizationEnumApi, BlankEnumApi, zod.null()]).optional(),
})

export type UserBasicApi = zod.input<typeof UserBasicApi>
export type UserBasicApiOutput = zod.output<typeof UserBasicApi>

export const OrganizationMembershipLevelEnumApi = zod
    .union([zod.literal(1), zod.literal(8), zod.literal(15)])
    .describe('\* `1` - member\n\* `8` - administrator\n\* `15` - owner')

export type OrganizationMembershipLevelEnumApi = zod.input<typeof OrganizationMembershipLevelEnumApi>
export type OrganizationMembershipLevelEnumApiOutput = zod.output<typeof OrganizationMembershipLevelEnumApi>

export const SearchMatchTypeEnumApi = zod.enum(['exact', 'similar'])

export type SearchMatchTypeEnumApi = zod.input<typeof SearchMatchTypeEnumApi>
export type SearchMatchTypeEnumApiOutput = zod.output<typeof SearchMatchTypeEnumApi>

export const OrganizationMemberApi = zod.object({
    id: zod.uuid(),
    user: UserBasicApi,
    level: OrganizationMembershipLevelEnumApi.optional(),
    joined_at: zod.iso.datetime({ offset: true }),
    updated_at: zod.iso.datetime({ offset: true }),
    is_2fa_enabled: zod.boolean(),
    has_social_auth: zod.boolean(),
    last_login: zod.iso.datetime({ offset: true }),
    search_match_type: zod
        .union([SearchMatchTypeEnumApi, zod.null()])
        .describe(
            'How this row matched the `search` query parameter: `exact` (the term is a case-insensitive substring of a searched field) or `similar` (a fuzzy trigram match, returned only when no exact match exists). Null when the list is not filtered by `search`.'
        ),
})

export type OrganizationMemberApi = zod.input<typeof OrganizationMemberApi>
export type OrganizationMemberApiOutput = zod.output<typeof OrganizationMemberApi>

export const PaginatedOrganizationMemberListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(OrganizationMemberApi),
})

export type PaginatedOrganizationMemberListApi = zod.input<typeof PaginatedOrganizationMemberListApi>
export type PaginatedOrganizationMemberListApiOutput = zod.output<typeof PaginatedOrganizationMemberListApi>

export const PatchedOrganizationMemberApi = zod.object({
    id: zod.uuid().optional(),
    user: UserBasicApi.optional(),
    level: OrganizationMembershipLevelEnumApi.optional(),
    joined_at: zod.iso.datetime({ offset: true }).optional(),
    updated_at: zod.iso.datetime({ offset: true }).optional(),
    is_2fa_enabled: zod.boolean().optional(),
    has_social_auth: zod.boolean().optional(),
    last_login: zod.iso.datetime({ offset: true }).optional(),
    search_match_type: zod
        .union([SearchMatchTypeEnumApi, zod.null()])
        .optional()
        .describe(
            'How this row matched the `search` query parameter: `exact` (the term is a case-insensitive substring of a searched field) or `similar` (a fuzzy trigram match, returned only when no exact match exists). Null when the list is not filtered by `search`.'
        ),
})

export type PatchedOrganizationMemberApi = zod.input<typeof PatchedOrganizationMemberApi>
export type PatchedOrganizationMemberApiOutput = zod.output<typeof PatchedOrganizationMemberApi>

export const OrganizationMemberGithubLoginApi = zod.object({
    github_login: zod
        .string()
        .nullable()
        .describe(
            "The member's GitHub username (login), resolved from their linked GitHub integration or OAuth identity. Null when the member has no GitHub identity linked."
        ),
})

export type OrganizationMemberGithubLoginApi = zod.input<typeof OrganizationMemberGithubLoginApi>
export type OrganizationMemberGithubLoginApiOutput = zod.output<typeof OrganizationMemberGithubLoginApi>

export const OrganizationPersonalAPIKeyOwnerApi = zod.object({
    first_name: zod.string().describe("First name of the key's owner."),
    last_name: zod.string().describe("Last name of the key's owner."),
    email: zod.email().describe("Email address of the key's owner."),
})

export type OrganizationPersonalAPIKeyOwnerApi = zod.input<typeof OrganizationPersonalAPIKeyOwnerApi>
export type OrganizationPersonalAPIKeyOwnerApiOutput = zod.output<typeof OrganizationPersonalAPIKeyOwnerApi>

export const OrganizationPersonalAPIKeyProjectScopeApi = zod.object({
    id: zod.number().describe('Project (team) ID the key is scoped to.'),
    name: zod.string().describe('Name of the project the key is scoped to.'),
})

export type OrganizationPersonalAPIKeyProjectScopeApi = zod.input<typeof OrganizationPersonalAPIKeyProjectScopeApi>
export type OrganizationPersonalAPIKeyProjectScopeApiOutput = zod.output<
    typeof OrganizationPersonalAPIKeyProjectScopeApi
>

export const OrganizationPersonalAPIKeyAccessScopeApi = zod.object({
    type: zod
        .string()
        .describe(
            "Breadth of access: 'all' (every project the owner can reach), 'organization' (this whole organization), or 'projects' (specific projects listed under 'projects')."
        ),
    projects: zod
        .array(OrganizationPersonalAPIKeyProjectScopeApi)
        .optional()
        .describe("Projects within this organization the key is scoped to, present only when type is 'projects'."),
})

export type OrganizationPersonalAPIKeyAccessScopeApi = zod.input<typeof OrganizationPersonalAPIKeyAccessScopeApi>
export type OrganizationPersonalAPIKeyAccessScopeApiOutput = zod.output<typeof OrganizationPersonalAPIKeyAccessScopeApi>

export const OrganizationPersonalAPIKeyApi = zod.object({
    owner: OrganizationPersonalAPIKeyOwnerApi.describe('The organization member who owns this key.'),
    mask_value: zod
        .string()
        .describe(
            "Masked, display-safe hint of the key value (e.g. 'phx_\*\*\*1234'). Not the secret. The owner sees the same masked value in their own settings, so it can be used to identify a key."
        ),
    scopes: zod
        .array(zod.string())
        .describe("API scopes granted to the key, e.g. 'insight:read'. A single '\*' means full access."),
    access_scope: OrganizationPersonalAPIKeyAccessScopeApi.describe(
        "Where the key's scopes apply within this organization."
    ),
    last_used_at: zod.iso
        .datetime({ offset: true })
        .nullable()
        .describe('When the key was last used to authenticate, if ever.'),
    created_at: zod.iso.datetime({ offset: true }).describe('When the key was created.'),
})

export type OrganizationPersonalAPIKeyApi = zod.input<typeof OrganizationPersonalAPIKeyApi>
export type OrganizationPersonalAPIKeyApiOutput = zod.output<typeof OrganizationPersonalAPIKeyApi>

export const PaginatedOrganizationPersonalAPIKeyListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(OrganizationPersonalAPIKeyApi),
})

export type PaginatedOrganizationPersonalAPIKeyListApi = zod.input<typeof PaginatedOrganizationPersonalAPIKeyListApi>
export type PaginatedOrganizationPersonalAPIKeyListApiOutput = zod.output<
    typeof PaginatedOrganizationPersonalAPIKeyListApi
>

export const roleApiNameMax = 200

export const RoleApi = zod.object({
    id: zod.uuid(),
    name: zod.string().max(roleApiNameMax),
    created_at: zod.iso.datetime({ offset: true }),
    created_by: UserBasicApi,
    members: zod.array(zod.record(zod.string(), zod.unknown())).describe('Members assigned to this role'),
    is_default: zod.boolean(),
})

export type RoleApi = zod.input<typeof RoleApi>
export type RoleApiOutput = zod.output<typeof RoleApi>

export const PaginatedRoleListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(RoleApi),
})

export type PaginatedRoleListApi = zod.input<typeof PaginatedRoleListApi>
export type PaginatedRoleListApiOutput = zod.output<typeof PaginatedRoleListApi>

export const patchedRoleApiNameMax = 200

export const PatchedRoleApi = zod.object({
    id: zod.uuid().optional(),
    name: zod.string().max(patchedRoleApiNameMax).optional(),
    created_at: zod.iso.datetime({ offset: true }).optional(),
    created_by: UserBasicApi.optional(),
    members: zod.array(zod.record(zod.string(), zod.unknown())).optional().describe('Members assigned to this role'),
    is_default: zod.boolean().optional(),
})

export type PatchedRoleApi = zod.input<typeof PatchedRoleApi>
export type PatchedRoleApiOutput = zod.output<typeof PatchedRoleApi>

export const RoleMembershipApi = zod.object({
    id: zod.uuid(),
    role_id: zod.uuid(),
    organization_member: OrganizationMemberApi,
    user: UserBasicApi,
    joined_at: zod.iso.datetime({ offset: true }),
    updated_at: zod.iso.datetime({ offset: true }),
    user_uuid: zod.uuid(),
})

export type RoleMembershipApi = zod.input<typeof RoleMembershipApi>
export type RoleMembershipApiOutput = zod.output<typeof RoleMembershipApi>

export const PaginatedRoleMembershipListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(RoleMembershipApi),
})

export type PaginatedRoleMembershipListApi = zod.input<typeof PaginatedRoleMembershipListApi>
export type PaginatedRoleMembershipListApiOutput = zod.output<typeof PaginatedRoleMembershipListApi>

export const _WelcomeInviterApi = zod.object({
    name: zod.string(),
    email: zod.email(),
})

export type _WelcomeInviterApi = zod.input<typeof _WelcomeInviterApi>
export type _WelcomeInviterApiOutput = zod.output<typeof _WelcomeInviterApi>

export const LastActiveEnumApi = zod
    .enum(['today', 'this_week', 'inactive', 'never'])
    .describe('\* `today` - today\n\* `this_week` - this_week\n\* `inactive` - inactive\n\* `never` - never')

export type LastActiveEnumApi = zod.input<typeof LastActiveEnumApi>
export type LastActiveEnumApiOutput = zod.output<typeof LastActiveEnumApi>

export const _WelcomeTeamMemberApi = zod.object({
    name: zod.string(),
    email: zod.email(),
    avatar: zod.string().nullable(),
    role: zod.string(),
    last_active: LastActiveEnumApi,
})

export type _WelcomeTeamMemberApi = zod.input<typeof _WelcomeTeamMemberApi>
export type _WelcomeTeamMemberApiOutput = zod.output<typeof _WelcomeTeamMemberApi>

export const _WelcomeRecentActivityApi = zod.object({
    type: zod.string().describe("Scope.activity pair, e.g. 'Insight.created'."),
    actor_name: zod.string(),
    entity_name: zod.string(),
    entity_url: zod.string().nullable(),
    timestamp: zod.iso.datetime({ offset: true }),
})

export type _WelcomeRecentActivityApi = zod.input<typeof _WelcomeRecentActivityApi>
export type _WelcomeRecentActivityApiOutput = zod.output<typeof _WelcomeRecentActivityApi>

export const _WelcomePopularDashboardApi = zod.object({
    id: zod.number(),
    name: zod.string(),
    description: zod.string(),
    team_id: zod.number(),
    url: zod.string(),
})

export type _WelcomePopularDashboardApi = zod.input<typeof _WelcomePopularDashboardApi>
export type _WelcomePopularDashboardApiOutput = zod.output<typeof _WelcomePopularDashboardApi>

export const _WelcomeSuggestedStepApi = zod.object({
    label: zod.string(),
    href: zod.string(),
    reason: zod.string(),
    docs_href: zod.string().optional(),
    product_key: zod.string().optional(),
})

export type _WelcomeSuggestedStepApi = zod.input<typeof _WelcomeSuggestedStepApi>
export type _WelcomeSuggestedStepApiOutput = zod.output<typeof _WelcomeSuggestedStepApi>

export const WelcomeResponseApi = zod.object({
    organization_name: zod.string(),
    inviter: zod.union([_WelcomeInviterApi, zod.null()]),
    team_members: zod.array(_WelcomeTeamMemberApi),
    recent_activity: zod.array(_WelcomeRecentActivityApi),
    popular_dashboards: zod.array(_WelcomePopularDashboardApi),
    products_in_use: zod.array(zod.string()),
    suggested_next_steps: zod.array(_WelcomeSuggestedStepApi),
    is_organization_first_user: zod.boolean(),
})

export type WelcomeResponseApi = zod.input<typeof WelcomeResponseApi>
export type WelcomeResponseApiOutput = zod.output<typeof WelcomeResponseApi>

export const activityLogApiTeamIdMin = 0
export const activityLogApiTeamIdMax = 2147483647

export const activityLogApiClientMax = 32

export const activityLogApiActivityMax = 79

export const activityLogApiItemIdMax = 72

export const activityLogApiScopeMax = 79

export const ActivityLogApi = zod.object({
    id: zod.uuid(),
    user: UserBasicApi,
    unread: zod.boolean().describe("is the date of this log item newer than the user's bookmark"),
    team_id: zod.number().min(activityLogApiTeamIdMin).max(activityLogApiTeamIdMax).nullish(),
    organization_id: zod.uuid().nullish(),
    was_impersonated: zod.boolean().nullish(),
    is_system: zod.boolean().nullish(),
    client: zod.string().max(activityLogApiClientMax).nullish(),
    ip_address: zod.string().nullish(),
    activity: zod.string().max(activityLogApiActivityMax),
    item_id: zod.string().max(activityLogApiItemIdMax).nullish(),
    scope: zod.string().max(activityLogApiScopeMax),
    detail: zod.unknown().optional(),
    created_at: zod.iso.datetime({ offset: true }).optional(),
})

export type ActivityLogApi = zod.input<typeof ActivityLogApi>
export type ActivityLogApiOutput = zod.output<typeof ActivityLogApi>

export const PaginatedActivityLogListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(ActivityLogApi),
})

export type PaginatedActivityLogListApi = zod.input<typeof PaginatedActivityLogListApi>
export type PaginatedActivityLogListApiOutput = zod.output<typeof PaginatedActivityLogListApi>

export const StaticFiltersApi = zod.object({
    users: zod.array(zod.record(zod.string(), zod.unknown())).describe('Users who have logged activity.'),
    scopes: zod.array(zod.record(zod.string(), zod.unknown())).describe('Available activity scopes.'),
    activities: zod.array(zod.record(zod.string(), zod.unknown())).describe('Available activity types.'),
    clients: zod
        .array(zod.record(zod.string(), zod.unknown()))
        .describe('API clients that have generated activity (from x-posthog-client header).'),
})

export type StaticFiltersApi = zod.input<typeof StaticFiltersApi>
export type StaticFiltersApiOutput = zod.output<typeof StaticFiltersApi>

export const AvailableFiltersResponseApi = zod.object({
    static_filters: StaticFiltersApi.describe('Pre-computed filter options for scopes, activities, and users.'),
    detail_fields: zod
        .record(zod.string(), zod.unknown())
        .describe('Discovered detail fields and their value distributions.'),
})

export type AvailableFiltersResponseApi = zod.input<typeof AvailableFiltersResponseApi>
export type AvailableFiltersResponseApiOutput = zod.output<typeof AvailableFiltersResponseApi>

export const approvalPolicyApiActionKeyMax = 128

export const ApprovalPolicyApi = zod.object({
    id: zod.uuid(),
    action_key: zod.string().max(approvalPolicyApiActionKeyMax),
    conditions: zod.unknown().optional(),
    approver_config: zod.unknown(),
    allow_self_approve: zod.boolean().optional(),
    bypass_org_membership_levels: zod.unknown().optional(),
    bypass_roles: zod.array(zod.uuid()).optional(),
    expires_after: zod.string().optional().describe('Auto-expire change requests after this duration'),
    enabled: zod.boolean().optional(),
    created_by: UserBasicApi,
    created_at: zod.iso.datetime({ offset: true }),
    updated_at: zod.iso.datetime({ offset: true }).nullable(),
})

export type ApprovalPolicyApi = zod.input<typeof ApprovalPolicyApi>
export type ApprovalPolicyApiOutput = zod.output<typeof ApprovalPolicyApi>

export const PaginatedApprovalPolicyListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(ApprovalPolicyApi),
})

export type PaginatedApprovalPolicyListApi = zod.input<typeof PaginatedApprovalPolicyListApi>
export type PaginatedApprovalPolicyListApiOutput = zod.output<typeof PaginatedApprovalPolicyListApi>

export const patchedApprovalPolicyApiActionKeyMax = 128

export const PatchedApprovalPolicyApi = zod.object({
    id: zod.uuid().optional(),
    action_key: zod.string().max(patchedApprovalPolicyApiActionKeyMax).optional(),
    conditions: zod.unknown().optional(),
    approver_config: zod.unknown().optional(),
    allow_self_approve: zod.boolean().optional(),
    bypass_org_membership_levels: zod.unknown().optional(),
    bypass_roles: zod.array(zod.uuid()).optional(),
    expires_after: zod.string().optional().describe('Auto-expire change requests after this duration'),
    enabled: zod.boolean().optional(),
    created_by: UserBasicApi.optional(),
    created_at: zod.iso.datetime({ offset: true }).optional(),
    updated_at: zod.iso.datetime({ offset: true }).nullish(),
})

export type PatchedApprovalPolicyApi = zod.input<typeof PatchedApprovalPolicyApi>
export type PatchedApprovalPolicyApiOutput = zod.output<typeof PatchedApprovalPolicyApi>

export const ValidationStatusEnumApi = zod
    .enum(['valid', 'invalid', 'stale'])
    .describe('\* `valid` - Valid\n\* `invalid` - Invalid\n\* `stale` - Stale (resource changed)')

export type ValidationStatusEnumApi = zod.input<typeof ValidationStatusEnumApi>
export type ValidationStatusEnumApiOutput = zod.output<typeof ValidationStatusEnumApi>

export const ChangeRequestStateEnumApi = zod
    .enum(['pending', 'approved', 'applied', 'rejected', 'expired', 'failed'])
    .describe(
        '\* `pending` - Pending\n\* `approved` - Approved (awaiting application)\n\* `applied` - Applied\n\* `rejected` - Rejected\n\* `expired` - Expired\n\* `failed` - Failed to apply'
    )

export type ChangeRequestStateEnumApi = zod.input<typeof ChangeRequestStateEnumApi>
export type ChangeRequestStateEnumApiOutput = zod.output<typeof ChangeRequestStateEnumApi>

export const ChangeRequestApi = zod.object({
    id: zod.uuid(),
    action_key: zod.string(),
    action_version: zod.number(),
    resource_type: zod.string(),
    resource_id: zod.string().nullable(),
    intent: zod.unknown(),
    intent_display: zod.unknown(),
    policy_snapshot: zod.unknown(),
    validation_status: ValidationStatusEnumApi,
    validation_errors: zod.unknown(),
    validated_at: zod.iso.datetime({ offset: true }).nullable(),
    state: ChangeRequestStateEnumApi,
    created_by: UserBasicApi,
    applied_by: UserBasicApi,
    created_at: zod.iso.datetime({ offset: true }),
    updated_at: zod.iso.datetime({ offset: true }).nullable(),
    expires_at: zod.iso.datetime({ offset: true }),
    applied_at: zod.iso.datetime({ offset: true }).nullable(),
    apply_error: zod.string(),
    result_data: zod.unknown(),
    approvals: zod.array(zod.record(zod.string(), zod.unknown())),
    can_approve: zod.boolean().describe('Check if current user can approve this change request.'),
    can_cancel: zod.boolean(),
    is_requester: zod.boolean().describe('Check if current user is the requester.'),
    user_decision: zod.string().nullable().describe("Get the current user's approval decision if they have voted."),
})

export type ChangeRequestApi = zod.input<typeof ChangeRequestApi>
export type ChangeRequestApiOutput = zod.output<typeof ChangeRequestApi>

export const PaginatedChangeRequestListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(ChangeRequestApi),
})

export type PaginatedChangeRequestListApi = zod.input<typeof PaginatedChangeRequestListApi>
export type PaginatedChangeRequestListApiOutput = zod.output<typeof PaginatedChangeRequestListApi>

export const ChangeRequestApproveApi = zod.object({
    reason: zod.string().optional().describe('Optional note recorded with the approval vote explaining the decision.'),
})

export type ChangeRequestApproveApi = zod.input<typeof ChangeRequestApproveApi>
export type ChangeRequestApproveApiOutput = zod.output<typeof ChangeRequestApproveApi>

export const ChangeRequestDecisionResponseApi = zod.object({
    status: zod
        .string()
        .describe(
            "The change request's resulting state after the vote (e.g. 'pending', 'approved', 'applied', 'rejected')."
        ),
    message: zod.string().describe('Human-readable summary of what happened.'),
    change_request: ChangeRequestApi.describe('The change request after the vote was recorded.'),
    result: zod
        .unknown()
        .optional()
        .describe(
            'Present only when the vote reached quorum and the change was applied immediately: details of the affected resource (e.g. resource_id, resource_version).'
        ),
})

export type ChangeRequestDecisionResponseApi = zod.input<typeof ChangeRequestDecisionResponseApi>
export type ChangeRequestDecisionResponseApiOutput = zod.output<typeof ChangeRequestDecisionResponseApi>

export const ChangeRequestRejectApi = zod.object({
    reason: zod
        .string()
        .describe(
            'Reason for rejecting the change request. Required — recorded with the rejection vote and shown to the requester.'
        ),
})

export type ChangeRequestRejectApi = zod.input<typeof ChangeRequestRejectApi>
export type ChangeRequestRejectApiOutput = zod.output<typeof ChangeRequestRejectApi>

export const commentApiIsTaskDefault = false
export const commentApiItemIdMax = 72

export const commentApiScopeMax = 79

export const CommentApi = zod.object({
    id: zod.uuid(),
    created_by: UserBasicApi,
    deleted: zod.boolean().nullish(),
    mentions: zod.array(zod.number()).optional(),
    slug: zod.string().optional(),
    is_task: zod
        .boolean()
        .default(commentApiIsTaskDefault)
        .describe(
            'Whether this comment is an actionable task that can be marked complete. Tasks render with a checkbox in the UI and can be filtered as a separate kind. Cannot be set on replies (source_comment) or emoji reactions. Immutable after creation.'
        ),
    completed_by: zod
        .union([UserBasicApi, zod.null()])
        .describe('The user who marked this task complete. Null for open tasks and non-task comments.'),
    content: zod.string().nullish(),
    rich_content: zod.unknown().optional(),
    version: zod.number(),
    created_at: zod.iso.datetime({ offset: true }),
    item_id: zod.string().max(commentApiItemIdMax).nullish(),
    item_context: zod.unknown().optional(),
    scope: zod.string().max(commentApiScopeMax),
    completed_at: zod.iso
        .datetime({ offset: true })
        .nullable()
        .describe(
            'ISO timestamp when the task was marked complete. Only meaningful when is_task is true. Read-only — toggled via the \/complete and \/reopen actions, not via PATCH.'
        ),
    source_comment: zod.uuid().nullish(),
})

export type CommentApi = zod.input<typeof CommentApi>
export type CommentApiOutput = zod.output<typeof CommentApi>

export const PaginatedCommentListApi = zod.object({
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(CommentApi),
})

export type PaginatedCommentListApi = zod.input<typeof PaginatedCommentListApi>
export type PaginatedCommentListApiOutput = zod.output<typeof PaginatedCommentListApi>

export const patchedCommentApiIsTaskDefault = false
export const patchedCommentApiItemIdMax = 72

export const patchedCommentApiScopeMax = 79

export const PatchedCommentApi = zod.object({
    id: zod.uuid().optional(),
    created_by: UserBasicApi.optional(),
    deleted: zod.boolean().nullish(),
    mentions: zod.array(zod.number()).optional(),
    slug: zod.string().optional(),
    is_task: zod
        .boolean()
        .default(patchedCommentApiIsTaskDefault)
        .describe(
            'Whether this comment is an actionable task that can be marked complete. Tasks render with a checkbox in the UI and can be filtered as a separate kind. Cannot be set on replies (source_comment) or emoji reactions. Immutable after creation.'
        ),
    completed_by: zod
        .union([UserBasicApi, zod.null()])
        .optional()
        .describe('The user who marked this task complete. Null for open tasks and non-task comments.'),
    content: zod.string().nullish(),
    rich_content: zod.unknown().optional(),
    version: zod.number().optional(),
    created_at: zod.iso.datetime({ offset: true }).optional(),
    item_id: zod.string().max(patchedCommentApiItemIdMax).nullish(),
    item_context: zod.unknown().optional(),
    scope: zod.string().max(patchedCommentApiScopeMax).optional(),
    completed_at: zod.iso
        .datetime({ offset: true })
        .nullish()
        .describe(
            'ISO timestamp when the task was marked complete. Only meaningful when is_task is true. Read-only — toggled via the \/complete and \/reopen actions, not via PATCH.'
        ),
    source_comment: zod.uuid().nullish(),
})

export type PatchedCommentApi = zod.input<typeof PatchedCommentApi>
export type PatchedCommentApiOutput = zod.output<typeof PatchedCommentApi>

export const PinnedSceneTabApi = zod.object({
    id: zod
        .string()
        .optional()
        .describe('Stable identifier for the tab. Generated client-side; safe to omit on create.'),
    pathname: zod
        .string()
        .optional()
        .describe(
            'URL pathname the tab points at — for example `\/project\/123\/dashboard\/45` or `\/project\/123\/insights`. Combined with `search` and `hash` to reconstruct the destination.'
        ),
    search: zod
        .string()
        .optional()
        .describe('Query string portion of the URL, including the leading `?`. Empty string when there is no query.'),
    hash: zod
        .string()
        .optional()
        .describe('Fragment portion of the URL, including the leading `#`. Empty string when there is no fragment.'),
    title: zod
        .string()
        .optional()
        .describe('Default tab title derived from the destination scene. Used when `customTitle` is not set.'),
    customTitle: zod
        .string()
        .nullish()
        .describe('Optional user-provided title that overrides `title` in the navigation UI.'),
    iconType: zod
        .string()
        .optional()
        .describe('Icon key shown next to the tab in the sidebar — for example `dashboard`, `insight`, `blank`.'),
    sceneId: zod
        .string()
        .nullish()
        .describe(
            'Scene identifier resolved from the pathname when known — used by the frontend for icon\/title hints.'
        ),
    sceneKey: zod
        .string()
        .nullish()
        .describe('Scene key (logic key) for the destination, paired with `sceneParams` for deeper routing context.'),
    sceneParams: zod
        .unknown()
        .optional()
        .describe(
            'Free-form scene parameters captured at pin time, used by the frontend to rehydrate the destination.'
        ),
    pinned: zod
        .boolean()
        .optional()
        .describe('Whether this entry is pinned. Always coerced to true on save — pass true or omit.'),
})

export type PinnedSceneTabApi = zod.input<typeof PinnedSceneTabApi>
export type PinnedSceneTabApiOutput = zod.output<typeof PinnedSceneTabApi>

export const PinnedSceneTabsApi = zod.object({
    tabs: zod
        .array(PinnedSceneTabApi)
        .optional()
        .describe(
            'Ordered list of pinned navigation tabs shown in the sidebar for the authenticated user within the current team. Send the full list to replace the existing pins; omit to leave them unchanged.'
        ),
    homepage: zod
        .union([PinnedSceneTabApi, zod.null()])
        .optional()
        .describe(
            "Tab descriptor for the user's chosen home page — the destination opened when they click the PostHog logo or hit `\/`. Set to a tab descriptor to pick a homepage, send `null` or `{}` to clear it and fall back to the project default."
        ),
})

export type PinnedSceneTabsApi = zod.input<typeof PinnedSceneTabsApi>
export type PinnedSceneTabsApiOutput = zod.output<typeof PinnedSceneTabsApi>

export const PatchedPinnedSceneTabsApi = zod.object({
    tabs: zod
        .array(PinnedSceneTabApi)
        .optional()
        .describe(
            'Ordered list of pinned navigation tabs shown in the sidebar for the authenticated user within the current team. Send the full list to replace the existing pins; omit to leave them unchanged.'
        ),
    homepage: zod
        .union([PinnedSceneTabApi, zod.null()])
        .optional()
        .describe(
            "Tab descriptor for the user's chosen home page — the destination opened when they click the PostHog logo or hit `\/`. Set to a tab descriptor to pick a homepage, send `null` or `{}` to clear it and fall back to the project default."
        ),
})

export type PatchedPinnedSceneTabsApi = zod.input<typeof PatchedPinnedSceneTabsApi>
export type PatchedPinnedSceneTabsApiOutput = zod.output<typeof PatchedPinnedSceneTabsApi>
