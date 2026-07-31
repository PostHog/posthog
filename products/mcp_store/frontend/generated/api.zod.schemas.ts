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

export const MCPAuditDecisionEnumApi = zod
    .enum(['auto', 'approved', 'pending', 'blocked'])
    .describe(
        '\* `auto` - Auto-approved\n\* `approved` - Approved\n\* `pending` - Awaiting approval\n\* `blocked` - Blocked'
    )

export type MCPAuditDecisionEnumApi = zod.input<typeof MCPAuditDecisionEnumApi>
export type MCPAuditDecisionEnumApiOutput = zod.output<typeof MCPAuditDecisionEnumApi>

export const RoleAtOrganizationEnumApi = zod
    .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
    .describe(
        '\* `engineering` - Engineering\n\* `data` - Data\n\* `product` - Product Management\n\* `founder` - Founder\n\* `leadership` - Leadership\n\* `marketing` - Marketing\n\* `sales` - Sales \/ Success\n\* `other` - Other'
    )

export type RoleAtOrganizationEnumApi = zod.input<typeof RoleAtOrganizationEnumApi>
export type RoleAtOrganizationEnumApiOutput = zod.output<typeof RoleAtOrganizationEnumApi>

export const BlankEnumApi = zod.enum([''])

export type BlankEnumApi = zod.input<typeof BlankEnumApi>
export type BlankEnumApiOutput = zod.output<typeof BlankEnumApi>

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

export const AuditActorServiceAccountApi = zod.object({
    id: zod.uuid().describe('Service account id.'),
    name: zod.string().describe('Agent display name.'),
    handle: zod.string().describe('Agent identity handle.'),
})

export type AuditActorServiceAccountApi = zod.input<typeof AuditActorServiceAccountApi>
export type AuditActorServiceAccountApiOutput = zod.output<typeof AuditActorServiceAccountApi>

export const MCPAuditEventApi = zod.object({
    id: zod.uuid(),
    created_at: zod.iso.datetime({ offset: true }),
    server_name: zod.string().describe('Gateway server name at call time (denormalized).'),
    tool_name: zod.string().describe('Tool that was called.'),
    decision: MCPAuditDecisionEnumApi.describe(
        'How the gateway decided the call.\n\n\* `auto` - Auto-approved\n\* `approved` - Approved\n\* `pending` - Awaiting approval\n\* `blocked` - Blocked'
    ),
    actor_user: zod.union([UserBasicApi, zod.null()]).describe('Member who made the call, if any.'),
    actor_service_account: zod
        .union([AuditActorServiceAccountApi, zod.null()])
        .describe('Agent that made the call, if any. Null for member calls.'),
    actor_label: zod.string().describe('Denormalized actor label (email or handle) that survives deletion.'),
})

export type MCPAuditEventApi = zod.input<typeof MCPAuditEventApi>
export type MCPAuditEventApiOutput = zod.output<typeof MCPAuditEventApi>

export const PaginatedMCPAuditEventListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(MCPAuditEventApi),
})

export type PaginatedMCPAuditEventListApi = zod.input<typeof PaginatedMCPAuditEventListApi>
export type PaginatedMCPAuditEventListApiOutput = zod.output<typeof PaginatedMCPAuditEventListApi>

export const AuditCountsApi = zod.object({
    all: zod.number().describe('Every audited tool call.'),
    agents: zod.number().describe('Calls made by service accounts.'),
    approvals: zod.number().describe('Calls that were approved or are awaiting approval.'),
    blocked: zod.number().describe('Calls the gateway blocked.'),
})

export type AuditCountsApi = zod.input<typeof AuditCountsApi>
export type AuditCountsApiOutput = zod.output<typeof AuditCountsApi>

export const MCPPolicyPresetEnumApi = zod
    .enum(['allow', 'user', 'ask', 'block'])
    .describe(
        '\* `allow` - Allow all\n\* `user` - Member decides\n\* `ask` - Ask for destructive\n\* `block` - Block destructive'
    )

export type MCPPolicyPresetEnumApi = zod.input<typeof MCPPolicyPresetEnumApi>
export type MCPPolicyPresetEnumApiOutput = zod.output<typeof MCPPolicyPresetEnumApi>

export const TeamMCPGatewayConfigApi = zod.object({
    allow_custom_servers: zod
        .boolean()
        .optional()
        .describe('Whether non-admin members may register custom MCP servers with the gateway.'),
    allow_member_agent_access: zod
        .boolean()
        .optional()
        .describe(
            'Whether non-admin members may share their available MCP connections with agents and manage agent tool policies.'
        ),
    default_servers_enabled: zod
        .boolean()
        .optional()
        .describe(
            "Whether servers with no gateway registration — including catalog templates published later — are enabled for the team. A registered server's own toggle always wins."
        ),
    member_default_preset: zod
        .union([MCPPolicyPresetEnumApi, BlankEnumApi])
        .optional()
        .describe(
            'Baseline preset for members. Empty until an admin applies one from Team settings.\n\n\* `allow` - Allow all\n\* `user` - Member decides\n\* `ask` - Ask for destructive\n\* `block` - Block destructive'
        ),
    agent_default_preset: zod
        .union([MCPPolicyPresetEnumApi, BlankEnumApi])
        .optional()
        .describe(
            'Baseline preset deriving default policies for tools an agent has no explicit row for.\n\n\* `allow` - Allow all\n\* `user` - Member decides\n\* `ask` - Ask for destructive\n\* `block` - Block destructive'
        ),
    is_admin: zod
        .boolean()
        .describe('Whether the requesting user can administer the gateway (org admin or explicit project admin).'),
})

export type TeamMCPGatewayConfigApi = zod.input<typeof TeamMCPGatewayConfigApi>
export type TeamMCPGatewayConfigApiOutput = zod.output<typeof TeamMCPGatewayConfigApi>

export const AudienceEnumApi = zod.enum(['members', 'agents']).describe('\* `members` - members\n\* `agents` - agents')

export type AudienceEnumApi = zod.input<typeof AudienceEnumApi>
export type AudienceEnumApiOutput = zod.output<typeof AudienceEnumApi>

export const ApplyPresetApi = zod.object({
    audience: AudienceEnumApi.describe(
        "Which audience's baseline to overwrite.\n\n\* `members` - members\n\* `agents` - agents"
    ),
    preset: MCPPolicyPresetEnumApi.describe(
        'Preset to apply.\n\n\* `allow` - Allow all\n\* `user` - Member decides\n\* `ask` - Ask for destructive\n\* `block` - Block destructive'
    ),
})

export type ApplyPresetApi = zod.input<typeof ApplyPresetApi>
export type ApplyPresetApiOutput = zod.output<typeof ApplyPresetApi>

export const SetAllServersEnabledApi = zod.object({
    enabled: zod
        .boolean()
        .describe(
            'True enables every MCP server for the team; false disables them all. Applies to every registered server and becomes the default for untouched and future catalog servers.'
        ),
})

export type SetAllServersEnabledApi = zod.input<typeof SetAllServersEnabledApi>
export type SetAllServersEnabledApiOutput = zod.output<typeof SetAllServersEnabledApi>

export const GatewayConfigUpdateApi = zod.object({
    allow_custom_servers: zod
        .boolean()
        .optional()
        .describe('Whether non-admin members may register custom MCP servers.'),
    allow_member_agent_access: zod
        .boolean()
        .optional()
        .describe(
            'Whether non-admin members may share their available MCP connections with agents and manage agent tool policies.'
        ),
    default_servers_enabled: zod
        .boolean()
        .optional()
        .describe(
            "Whether servers with no gateway registration — including catalog templates published later — are enabled for the team. A registered server's own toggle always wins."
        ),
    member_default_preset: zod
        .union([MCPPolicyPresetEnumApi, BlankEnumApi])
        .optional()
        .describe(
            'Baseline preset for members.\n\n\* `allow` - Allow all\n\* `user` - Member decides\n\* `ask` - Ask for destructive\n\* `block` - Block destructive'
        ),
    agent_default_preset: zod
        .union([MCPPolicyPresetEnumApi, BlankEnumApi])
        .optional()
        .describe(
            'Baseline preset for agents.\n\n\* `allow` - Allow all\n\* `user` - Member decides\n\* `ask` - Ask for destructive\n\* `block` - Block destructive'
        ),
})

export type GatewayConfigUpdateApi = zod.input<typeof GatewayConfigUpdateApi>
export type GatewayConfigUpdateApiOutput = zod.output<typeof GatewayConfigUpdateApi>

export const GatewayMemberSummaryApi = zod
    .object({
        user: UserBasicApi.describe('The member.'),
        is_org_admin: zod.boolean().describe('Whether the member is an organization admin or owner.'),
        connected_server_ids: zod
            .array(zod.uuid())
            .describe('Gateway servers the member has a personal connection to.'),
        revoked_server_ids: zod.array(zod.uuid()).describe('Gateway servers an admin turned off for this member.'),
    })
    .describe("One team member's gateway posture (admin overview).")

export type GatewayMemberSummaryApi = zod.input<typeof GatewayMemberSummaryApi>
export type GatewayMemberSummaryApiOutput = zod.output<typeof GatewayMemberSummaryApi>

export const PaginatedGatewayMemberSummaryListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(GatewayMemberSummaryApi),
})

export type PaginatedGatewayMemberSummaryListApi = zod.input<typeof PaginatedGatewayMemberSummaryListApi>
export type PaginatedGatewayMemberSummaryListApiOutput = zod.output<typeof PaginatedGatewayMemberSummaryListApi>

export const MemberAccessUpdateApi = zod.object({
    gateway_server_id: zod.uuid().describe('Gateway server to toggle for the member.'),
    enabled: zod.boolean().describe('False turns the server off for the member; true restores it.'),
})

export type MemberAccessUpdateApi = zod.input<typeof MemberAccessUpdateApi>
export type MemberAccessUpdateApiOutput = zod.output<typeof MemberAccessUpdateApi>

export const AppliesToEnumApi = zod
    .enum(['everyone', 'members', 'agents'])
    .describe('\* `everyone` - Everyone\n\* `members` - Members\n\* `agents` - Agents')

export type AppliesToEnumApi = zod.input<typeof AppliesToEnumApi>
export type AppliesToEnumApiOutput = zod.output<typeof AppliesToEnumApi>

export const EffectEnumApi = zod
    .enum(['needs_approval', 'do_not_use'])
    .describe('\* `needs_approval` - Require approval\n\* `do_not_use` - Block')

export type EffectEnumApi = zod.input<typeof EffectEnumApi>
export type EffectEnumApiOutput = zod.output<typeof EffectEnumApi>

export const mCPOrgRuleApiNameMax = 200

export const mCPOrgRuleApiToolPatternMax = 400

export const MCPOrgRuleApi = zod.object({
    id: zod.uuid(),
    name: zod.string().max(mCPOrgRuleApiNameMax).describe('Short rule name shown wherever the rule locks a tool.'),
    description: zod.string().optional().describe('Why this guardrail exists.'),
    applies_to: AppliesToEnumApi.optional().describe(
        'Audience the rule constrains.\n\n\* `everyone` - Everyone\n\* `members` - Members\n\* `agents` - Agents'
    ),
    effect: EffectEnumApi.optional().describe(
        'State the rule forces on matching tools.\n\n\* `needs_approval` - Require approval\n\* `do_not_use` - Block'
    ),
    tool_pattern: zod
        .string()
        .max(mCPOrgRuleApiToolPatternMax)
        .optional()
        .describe('fnmatch pattern against tool names. Blank matches destructive tools heuristically.'),
    enabled: zod.boolean().optional().describe('Disabled rules are kept but not evaluated.'),
    created_at: zod.iso.datetime({ offset: true }),
    updated_at: zod.iso.datetime({ offset: true }),
})

export type MCPOrgRuleApi = zod.input<typeof MCPOrgRuleApi>
export type MCPOrgRuleApiOutput = zod.output<typeof MCPOrgRuleApi>

export const PaginatedMCPOrgRuleListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(MCPOrgRuleApi),
})

export type PaginatedMCPOrgRuleListApi = zod.input<typeof PaginatedMCPOrgRuleListApi>
export type PaginatedMCPOrgRuleListApiOutput = zod.output<typeof PaginatedMCPOrgRuleListApi>

export const patchedMCPOrgRuleApiNameMax = 200

export const patchedMCPOrgRuleApiToolPatternMax = 400

export const PatchedMCPOrgRuleApi = zod.object({
    id: zod.uuid().optional(),
    name: zod
        .string()
        .max(patchedMCPOrgRuleApiNameMax)
        .optional()
        .describe('Short rule name shown wherever the rule locks a tool.'),
    description: zod.string().optional().describe('Why this guardrail exists.'),
    applies_to: AppliesToEnumApi.optional().describe(
        'Audience the rule constrains.\n\n\* `everyone` - Everyone\n\* `members` - Members\n\* `agents` - Agents'
    ),
    effect: EffectEnumApi.optional().describe(
        'State the rule forces on matching tools.\n\n\* `needs_approval` - Require approval\n\* `do_not_use` - Block'
    ),
    tool_pattern: zod
        .string()
        .max(patchedMCPOrgRuleApiToolPatternMax)
        .optional()
        .describe('fnmatch pattern against tool names. Blank matches destructive tools heuristically.'),
    enabled: zod.boolean().optional().describe('Disabled rules are kept but not evaluated.'),
    created_at: zod.iso.datetime({ offset: true }).optional(),
    updated_at: zod.iso.datetime({ offset: true }).optional(),
})

export type PatchedMCPOrgRuleApi = zod.input<typeof PatchedMCPOrgRuleApi>
export type PatchedMCPOrgRuleApiOutput = zod.output<typeof PatchedMCPOrgRuleApi>

export const MCPServerCategoryEnumApi = zod
    .enum(['business', 'data', 'design', 'dev', 'infra', 'productivity'])
    .describe(
        '\* `business` - Business Operations\n\* `data` - Data & Analytics\n\* `design` - Design & Content\n\* `dev` - Developer Tools & APIs\n\* `infra` - Infrastructure\n\* `productivity` - Productivity & Collaboration'
    )

export type MCPServerCategoryEnumApi = zod.input<typeof MCPServerCategoryEnumApi>
export type MCPServerCategoryEnumApiOutput = zod.output<typeof MCPServerCategoryEnumApi>

export const MCPAuthTypeEnumApi = zod.enum(['api_key', 'oauth']).describe('\* `api_key` - API Key\n\* `oauth` - OAuth')

export type MCPAuthTypeEnumApi = zod.input<typeof MCPAuthTypeEnumApi>
export type MCPAuthTypeEnumApiOutput = zod.output<typeof MCPAuthTypeEnumApi>

export const GatewayConnectionApi = zod
    .object({
        installation_id: zod.uuid().describe('Installation row backing this connection.'),
        user: UserBasicApi.describe('The member who connected.'),
        last_used_at: zod.iso
            .datetime({ offset: true })
            .nullable()
            .describe('When this connection last proxied a tool call. Null if never used.'),
        pending_oauth: zod.boolean().describe('True when the OAuth round-trip has not completed yet.'),
        needs_reauth: zod.boolean().describe('True when the stored token was invalidated and needs reauth.'),
    })
    .describe("One member's personal connection to a gateway server.")

export type GatewayConnectionApi = zod.input<typeof GatewayConnectionApi>
export type GatewayConnectionApiOutput = zod.output<typeof GatewayConnectionApi>

export const GatewayYourConnectionApi = zod
    .object({
        installation_id: zod.uuid().describe("The caller's installation row for this server."),
        is_enabled: zod.boolean().describe('Per-connection switch — false when self-disabled.'),
        pending_oauth: zod.boolean().describe('True when the OAuth round-trip has not completed yet.'),
        needs_reauth: zod.boolean().describe('True when the stored token was invalidated and needs reauth.'),
        last_used_at: zod.iso
            .datetime({ offset: true })
            .nullable()
            .describe('When the caller last proxied a call through this connection.'),
    })
    .describe("The requesting user's own connection to a gateway server.")

export type GatewayYourConnectionApi = zod.input<typeof GatewayYourConnectionApi>
export type GatewayYourConnectionApiOutput = zod.output<typeof GatewayYourConnectionApi>

export const MCPServiceAccountStatusEnumApi = zod
    .enum(['active', 'paused'])
    .describe('\* `active` - Active\n\* `paused` - Paused')

export type MCPServiceAccountStatusEnumApi = zod.input<typeof MCPServiceAccountStatusEnumApi>
export type MCPServiceAccountStatusEnumApiOutput = zod.output<typeof MCPServiceAccountStatusEnumApi>

export const GatewayAgentAccessApi = zod
    .object({
        service_account_id: zod.uuid().describe('Service account granted access.'),
        name: zod.string().describe('Agent display name.'),
        handle: zod.string().describe('Agent identity handle, e.g. posthog-support.'),
        status: MCPServiceAccountStatusEnumApi.describe(
            'active, or paused (all access off).\n\n\* `active` - Active\n\* `paused` - Paused'
        ),
        last_active_at: zod.iso.datetime({ offset: true }).nullable().describe('When the agent last made a call.'),
        granted_by: zod.union([UserBasicApi, zod.null()]).describe('Admin who shared this server with the agent.'),
    })
    .describe("One agent's access to a gateway server.")

export type GatewayAgentAccessApi = zod.input<typeof GatewayAgentAccessApi>
export type GatewayAgentAccessApiOutput = zod.output<typeof GatewayAgentAccessApi>

export const mCPGatewayServerApiIconKeyDefault = ``
export const mCPGatewayServerApiIconDomainDefault = ``
export const mCPGatewayServerApiDocsUrlDefault = ``

export const MCPGatewayServerApi = zod
    .object({
        id: zod.uuid(),
        name: zod.string(),
        url: zod.url(),
        description: zod.string(),
        category: MCPServerCategoryEnumApi,
        template_auth_type: zod
            .union([MCPAuthTypeEnumApi, zod.null()])
            .describe(
                'Fixed authentication type for catalog templates. Null for custom servers, where members choose.\n\n\* `api_key` - API Key\n\* `oauth` - OAuth'
            ),
        is_team_enabled: zod.boolean(),
        icon_key: zod
            .string()
            .default(mCPGatewayServerApiIconKeyDefault)
            .describe('Deprecated brand icon key from the linked template. Empty for custom servers.'),
        icon_domain: zod
            .string()
            .default(mCPGatewayServerApiIconDomainDefault)
            .describe('Brand domain from the linked template. Empty for custom servers.'),
        docs_url: zod
            .string()
            .default(mCPGatewayServerApiDocsUrlDefault)
            .describe('Documentation URL from the template.'),
        template_id: zod.uuid().nullable().describe('Linked catalog template.'),
        tool_count: zod.number().describe('Number of live tools known for this server.'),
        connections: zod
            .array(GatewayConnectionApi)
            .describe('Members with a connection to this server. Only project admins receive this list.'),
        your_connection: zod
            .union([GatewayYourConnectionApi, zod.null()])
            .describe("The requesting user's own connection, or null when not connected."),
        agents: zod.array(GatewayAgentAccessApi).describe('Agents this server is shared with.'),
        revoked_user_ids: zod
            .array(zod.number())
            .describe('Ids of members whose access an admin has turned off. Only project admins receive this list.'),
        is_revoked_for_you: zod
            .boolean()
            .describe('True when an admin has turned this server off for the requesting user.'),
        created_by: zod
            .union([UserBasicApi, zod.null()])
            .describe('Who registered the server. Null when that user was deleted.'),
        created_at: zod.iso.datetime({ offset: true }),
        updated_at: zod.iso.datetime({ offset: true }),
    })
    .describe("A server registered in the team's gateway, with connection summary.")

export type MCPGatewayServerApi = zod.input<typeof MCPGatewayServerApi>
export type MCPGatewayServerApiOutput = zod.output<typeof MCPGatewayServerApi>

export const PaginatedMCPGatewayServerListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(MCPGatewayServerApi),
})

export type PaginatedMCPGatewayServerListApi = zod.input<typeof PaginatedMCPGatewayServerListApi>
export type PaginatedMCPGatewayServerListApiOutput = zod.output<typeof PaginatedMCPGatewayServerListApi>

export const mCPGatewayServerUpdateApiNameMax = 200

export const MCPGatewayServerUpdateApi = zod.object({
    name: zod
        .string()
        .max(mCPGatewayServerUpdateApiNameMax)
        .optional()
        .describe('Display name shown across the gateway.'),
    description: zod.string().optional().describe('Short description shown on server cards.'),
    category: MCPServerCategoryEnumApi.optional().describe(
        'Catalog category used for filter chips.\n\n\* `business` - Business Operations\n\* `data` - Data & Analytics\n\* `design` - Design & Content\n\* `dev` - Developer Tools & APIs\n\* `infra` - Infrastructure\n\* `productivity` - Productivity & Collaboration'
    ),
    is_team_enabled: zod
        .boolean()
        .optional()
        .describe('Whether the team can see and call the server. Turning it off also blocks agent access.'),
})

export type MCPGatewayServerUpdateApi = zod.input<typeof MCPGatewayServerUpdateApi>
export type MCPGatewayServerUpdateApiOutput = zod.output<typeof MCPGatewayServerUpdateApi>

export const patchedMCPGatewayServerUpdateApiNameMax = 200

export const PatchedMCPGatewayServerUpdateApi = zod.object({
    name: zod
        .string()
        .max(patchedMCPGatewayServerUpdateApiNameMax)
        .optional()
        .describe('Display name shown across the gateway.'),
    description: zod.string().optional().describe('Short description shown on server cards.'),
    category: MCPServerCategoryEnumApi.optional().describe(
        'Catalog category used for filter chips.\n\n\* `business` - Business Operations\n\* `data` - Data & Analytics\n\* `design` - Design & Content\n\* `dev` - Developer Tools & APIs\n\* `infra` - Infrastructure\n\* `productivity` - Productivity & Collaboration'
    ),
    is_team_enabled: zod
        .boolean()
        .optional()
        .describe('Whether the team can see and call the server. Turning it off also blocks agent access.'),
})

export type PatchedMCPGatewayServerUpdateApi = zod.input<typeof PatchedMCPGatewayServerUpdateApi>
export type PatchedMCPGatewayServerUpdateApiOutput = zod.output<typeof PatchedMCPGatewayServerUpdateApi>

export const ScopeTypeEnumApi = zod
    .enum(['team', 'member', 'agent'])
    .describe('\* `team` - Team default\n\* `member` - Member\n\* `agent` - Agent')

export type ScopeTypeEnumApi = zod.input<typeof ScopeTypeEnumApi>
export type ScopeTypeEnumApiOutput = zod.output<typeof ScopeTypeEnumApi>

export const MCPToolApprovalStateEnumApi = zod.enum(['approved', 'needs_approval', 'do_not_use'])

export type MCPToolApprovalStateEnumApi = zod.input<typeof MCPToolApprovalStateEnumApi>
export type MCPToolApprovalStateEnumApiOutput = zod.output<typeof MCPToolApprovalStateEnumApi>

export const toolPolicyEntryApiToolNameMax = 200

export const ToolPolicyEntryApi = zod.object({
    tool_name: zod
        .string()
        .max(toolPolicyEntryApiToolNameMax)
        .describe('Tool to set the policy for, up to 200 characters.'),
    policy_state: MCPToolApprovalStateEnumApi.describe(
        'State to apply for this scope.\n\n\* `approved` - Approved\n\* `needs_approval` - Needs approval\n\* `do_not_use` - Do not use'
    ),
})

export type ToolPolicyEntryApi = zod.input<typeof ToolPolicyEntryApi>
export type ToolPolicyEntryApiOutput = zod.output<typeof ToolPolicyEntryApi>

export const gatewayPoliciesUpsertApiScopeTypeDefault = `team`
export const gatewayPoliciesUpsertApiPoliciesMax = 1000

export const GatewayPoliciesUpsertApi = zod.object({
    scope_type: ScopeTypeEnumApi.default(gatewayPoliciesUpsertApiScopeTypeDefault).describe(
        'Which scope to resolve: the team default, one member, or one agent.\n\n\* `team` - Team default\n\* `member` - Member\n\* `agent` - Agent'
    ),
    scope_user_id: zod.number().optional().describe('Member scope target. Defaults to the requesting user.'),
    scope_service_account_id: zod.uuid().optional().describe('Agent scope target. Required when scope_type is agent.'),
    policies: zod
        .array(ToolPolicyEntryApi)
        .max(gatewayPoliciesUpsertApiPoliciesMax)
        .describe('Per-tool states to upsert for the scope. At most 1,000 entries per request.'),
})

export type GatewayPoliciesUpsertApi = zod.input<typeof GatewayPoliciesUpsertApi>
export type GatewayPoliciesUpsertApiOutput = zod.output<typeof GatewayPoliciesUpsertApi>

export const DecidedByEnumApi = zod
    .enum(['rule', 'scope', 'team', 'preset', 'legacy', 'default'])
    .describe(
        '\* `rule` - rule\n\* `scope` - scope\n\* `team` - team\n\* `preset` - preset\n\* `legacy` - legacy\n\* `default` - default'
    )

export type DecidedByEnumApi = zod.input<typeof DecidedByEnumApi>
export type DecidedByEnumApiOutput = zod.output<typeof DecidedByEnumApi>

export const ResolvedToolPolicyApi = zod
    .object({
        tool_name: zod.string().describe('Tool name as exposed by the upstream server.'),
        description: zod.string().describe('Tool description from the upstream server.'),
        input_schema: zod
            .record(zod.string(), zod.unknown())
            .describe("JSON Schema describing the tool's input arguments."),
        policy_state: MCPToolApprovalStateEnumApi.describe(
            'Effective state for the scope.\n\n\* `approved` - Approved\n\* `needs_approval` - Needs approval\n\* `do_not_use` - Do not use'
        ),
        team_state: zod
            .union([MCPToolApprovalStateEnumApi, zod.null()])
            .describe(
                'What the team-level chain (row or preset) yields, ignoring the scope. Null when the team imposes nothing.\n\n\* `approved` - Approved\n\* `needs_approval` - Needs approval\n\* `do_not_use` - Do not use'
            ),
        locked: zod
            .boolean()
            .describe('True when no state is editable for this scope (a rule match or a Blocked team ceiling).'),
        decided_by: DecidedByEnumApi.describe(
            'Which policy layer decided the state.\n\n\* `rule` - rule\n\* `scope` - scope\n\* `team` - team\n\* `preset` - preset\n\* `legacy` - legacy\n\* `default` - default'
        ),
        rule_name: zod.string().describe('Matching org rule name, when decided_by is rule.'),
        rule_description: zod.string().describe('Matching org rule description, when decided_by is rule.'),
    })
    .describe('One tool with its effective policy for the requested scope.')

export type ResolvedToolPolicyApi = zod.input<typeof ResolvedToolPolicyApi>
export type ResolvedToolPolicyApiOutput = zod.output<typeof ResolvedToolPolicyApi>

export const PaginatedResolvedToolPolicyListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(ResolvedToolPolicyApi),
})

export type PaginatedResolvedToolPolicyListApi = zod.input<typeof PaginatedResolvedToolPolicyListApi>
export type PaginatedResolvedToolPolicyListApiOutput = zod.output<typeof PaginatedResolvedToolPolicyListApi>

export const SetTemplateEnabledApi = zod.object({
    template_id: zod.uuid().describe('Active catalog template to enable or disable for the team.'),
    enabled: zod
        .boolean()
        .describe('True lets the team see and call the server; false hides it from members and blocks connections.'),
})

export type SetTemplateEnabledApi = zod.input<typeof SetTemplateEnabledApi>
export type SetTemplateEnabledApiOutput = zod.output<typeof SetTemplateEnabledApi>

export const AgentKeyEnumApi = zod.enum(['support', 'scout'])

export type AgentKeyEnumApi = zod.input<typeof AgentKeyEnumApi>
export type AgentKeyEnumApiOutput = zod.output<typeof AgentKeyEnumApi>

export const ConnectionStateEnumApi = zod
    .enum(['ready', 'pending_oauth', 'needs_reauth', 'disabled', 'missing_credential'])
    .describe(
        '\* `ready` - ready\n\* `pending_oauth` - pending_oauth\n\* `needs_reauth` - needs_reauth\n\* `disabled` - disabled\n\* `missing_credential` - missing_credential'
    )

export type ConnectionStateEnumApi = zod.input<typeof ConnectionStateEnumApi>
export type ConnectionStateEnumApiOutput = zod.output<typeof ConnectionStateEnumApi>

export const MCPServiceAccountServerApi = zod
    .object({
        id: zod.uuid().describe('Gateway server granted to the agent.'),
        name: zod.string().describe('Server display name.'),
        description: zod.string().describe('Server description.'),
        icon_key: zod.string().describe('Deprecated brand icon key. Empty for custom servers.'),
        icon_domain: zod.string().describe('Brand domain. Empty for custom servers.'),
        connection_state: ConnectionStateEnumApi.describe(
            'Whether the credential delegated to the agent is ready to use.\n\n\* `ready` - ready\n\* `pending_oauth` - pending_oauth\n\* `needs_reauth` - needs_reauth\n\* `disabled` - disabled\n\* `missing_credential` - missing_credential'
        ),
    })
    .describe('A credential-safe summary of a server configured for an agent.')

export type MCPServiceAccountServerApi = zod.input<typeof MCPServiceAccountServerApi>
export type MCPServiceAccountServerApiOutput = zod.output<typeof MCPServiceAccountServerApi>

export const MCPServiceAccountApi = zod.object({
    id: zod.uuid(),
    name: zod.string(),
    description: zod.string(),
    handle: zod.string().describe('Stable internal identity handle for this PostHog agent.'),
    agent_key: AgentKeyEnumApi.describe('Stable PostHog agent identifier.'),
    status: MCPServiceAccountStatusEnumApi.describe(
        'active, or paused (all MCP access off).\n\n\* `active` - Active\n\* `paused` - Paused'
    ),
    server_ids: zod.array(zod.uuid()).describe('Gateway servers configured for this agent.'),
    servers: zod
        .array(MCPServiceAccountServerApi)
        .describe('Credential-safe summaries of the gateway servers configured for this agent.'),
    last_active_at: zod.iso
        .datetime({ offset: true })
        .nullable()
        .describe('When the agent last made a call through the gateway.'),
    created_at: zod.iso.datetime({ offset: true }),
    updated_at: zod.iso.datetime({ offset: true }),
})

export type MCPServiceAccountApi = zod.input<typeof MCPServiceAccountApi>
export type MCPServiceAccountApiOutput = zod.output<typeof MCPServiceAccountApi>

export const PaginatedMCPServiceAccountListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(MCPServiceAccountApi),
})

export type PaginatedMCPServiceAccountListApi = zod.input<typeof PaginatedMCPServiceAccountListApi>
export type PaginatedMCPServiceAccountListApiOutput = zod.output<typeof PaginatedMCPServiceAccountListApi>

export const MCPServiceAccountUpdateApi = zod.object({
    status: MCPServiceAccountStatusEnumApi.optional().describe(
        'active, or paused (all MCP access off).\n\n\* `active` - Active\n\* `paused` - Paused'
    ),
})

export type MCPServiceAccountUpdateApi = zod.input<typeof MCPServiceAccountUpdateApi>
export type MCPServiceAccountUpdateApiOutput = zod.output<typeof MCPServiceAccountUpdateApi>

export const PatchedMCPServiceAccountUpdateApi = zod.object({
    status: MCPServiceAccountStatusEnumApi.optional().describe(
        'active, or paused (all MCP access off).\n\n\* `active` - Active\n\* `paused` - Paused'
    ),
})

export type PatchedMCPServiceAccountUpdateApi = zod.input<typeof PatchedMCPServiceAccountUpdateApi>
export type PatchedMCPServiceAccountUpdateApiOutput = zod.output<typeof PatchedMCPServiceAccountUpdateApi>

export const serviceAccountAccessUpdateApiPoliciesMax = 1000

export const ServiceAccountAccessUpdateApi = zod.object({
    gateway_server_id: zod.uuid().describe('Gateway server to grant or revoke.'),
    enabled: zod.boolean().describe('True grants access, false revokes it.'),
    policies: zod
        .array(ToolPolicyEntryApi)
        .max(serviceAccountAccessUpdateApiPoliciesMax)
        .optional()
        .describe('Optional agent-scope tool policies to set alongside the grant. At most 1,000 entries per request.'),
})

export type ServiceAccountAccessUpdateApi = zod.input<typeof ServiceAccountAccessUpdateApi>
export type ServiceAccountAccessUpdateApiOutput = zod.output<typeof ServiceAccountAccessUpdateApi>

export const MCPServerInstallationScopeEnumApi = zod
    .enum(['personal', 'shared'])
    .describe('\* `personal` - Personal\n\* `shared` - Shared')

export type MCPServerInstallationScopeEnumApi = zod.input<typeof MCPServerInstallationScopeEnumApi>
export type MCPServerInstallationScopeEnumApiOutput = zod.output<typeof MCPServerInstallationScopeEnumApi>

export const mCPServerInstallationApiIconKeyDefault = ``
export const mCPServerInstallationApiIconDomainDefault = ``
export const mCPServerInstallationApiDisplayNameMax = 200

export const mCPServerInstallationApiUrlMax = 2048

export const MCPServerInstallationApi = zod.object({
    id: zod.uuid(),
    template_id: zod.uuid().nullable(),
    name: zod.string(),
    icon_key: zod
        .string()
        .default(mCPServerInstallationApiIconKeyDefault)
        .describe(
            'Deprecated: use icon_domain instead. Lowercase key from the linked template for clients that still render bundled icon assets. Empty if custom install (no template).'
        ),
    icon_domain: zod
        .string()
        .default(mCPServerInstallationApiIconDomainDefault)
        .describe(
            'Brand domain from the linked template, rendered via the logo.dev icon proxy. Empty if custom install (no template).'
        ),
    display_name: zod.string().max(mCPServerInstallationApiDisplayNameMax).optional(),
    url: zod.url().max(mCPServerInstallationApiUrlMax).optional(),
    description: zod.string().optional(),
    auth_type: MCPAuthTypeEnumApi.optional(),
    is_enabled: zod.boolean().optional(),
    scope: MCPServerInstallationScopeEnumApi,
    is_owner: zod
        .boolean()
        .describe(
            'True when the requesting user owns this installation. Lets clients gate owner-only controls instead of surfacing 403s.'
        ),
    needs_reauth: zod.boolean(),
    pending_oauth: zod.boolean(),
    proxy_url: zod.string(),
    tool_count: zod.number().describe('Number of live (non-removed) tools exposed by this installation.'),
    created_at: zod.iso.datetime({ offset: true }),
    updated_at: zod.iso.datetime({ offset: true }).nullable(),
})

export type MCPServerInstallationApi = zod.input<typeof MCPServerInstallationApi>
export type MCPServerInstallationApiOutput = zod.output<typeof MCPServerInstallationApi>

export const PaginatedMCPServerInstallationListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(MCPServerInstallationApi),
})

export type PaginatedMCPServerInstallationListApi = zod.input<typeof PaginatedMCPServerInstallationListApi>
export type PaginatedMCPServerInstallationListApiOutput = zod.output<typeof PaginatedMCPServerInstallationListApi>

export const PatchedMCPServerInstallationUpdateApi = zod.object({
    display_name: zod.string().optional(),
    description: zod.string().optional(),
    is_enabled: zod.boolean().optional(),
})

export type PatchedMCPServerInstallationUpdateApi = zod.input<typeof PatchedMCPServerInstallationUpdateApi>
export type PatchedMCPServerInstallationUpdateApiOutput = zod.output<typeof PatchedMCPServerInstallationUpdateApi>

export const MCPServerInstallationToolApi = zod.object({
    id: zod.uuid(),
    tool_name: zod.string(),
    display_name: zod.string(),
    description: zod.string(),
    input_schema: zod.unknown(),
    approval_state: MCPToolApprovalStateEnumApi.describe('Effective state after applying the team ceiling.'),
    team_state: zod
        .union([MCPToolApprovalStateEnumApi, zod.null()])
        .describe('Team-admin ceiling for this tool. Null when the team imposes no ceiling.'),
    locked: zod.boolean().describe('True when a rule or Blocked team ceiling leaves no editable state.'),
    decided_by: zod.string().describe('Policy layer that decided the effective state.'),
    last_seen_at: zod.iso.datetime({ offset: true }),
    removed_at: zod.iso.datetime({ offset: true }).nullable(),
    created_at: zod.iso.datetime({ offset: true }),
    updated_at: zod.iso.datetime({ offset: true }).nullable(),
})

export type MCPServerInstallationToolApi = zod.input<typeof MCPServerInstallationToolApi>
export type MCPServerInstallationToolApiOutput = zod.output<typeof MCPServerInstallationToolApi>

export const PaginatedMCPServerInstallationToolListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(MCPServerInstallationToolApi),
})

export type PaginatedMCPServerInstallationToolListApi = zod.input<typeof PaginatedMCPServerInstallationToolListApi>
export type PaginatedMCPServerInstallationToolListApiOutput = zod.output<
    typeof PaginatedMCPServerInstallationToolListApi
>

export const ToolApprovalUpdateApprovalStateEnumApi = zod
    .enum(['approved', 'needs_approval', 'do_not_use'])
    .describe('\* `approved` - approved\n\* `needs_approval` - needs_approval\n\* `do_not_use` - do_not_use')

export type ToolApprovalUpdateApprovalStateEnumApi = zod.input<typeof ToolApprovalUpdateApprovalStateEnumApi>
export type ToolApprovalUpdateApprovalStateEnumApiOutput = zod.output<typeof ToolApprovalUpdateApprovalStateEnumApi>

export const PatchedToolApprovalUpdateApi = zod.object({
    approval_state: ToolApprovalUpdateApprovalStateEnumApi.optional(),
})

export type PatchedToolApprovalUpdateApi = zod.input<typeof PatchedToolApprovalUpdateApi>
export type PatchedToolApprovalUpdateApiOutput = zod.output<typeof PatchedToolApprovalUpdateApi>

export const InstallCustomAuthTypeEnumApi = zod
    .enum(['api_key', 'oauth'])
    .describe('\* `api_key` - api_key\n\* `oauth` - oauth')

export type InstallCustomAuthTypeEnumApi = zod.input<typeof InstallCustomAuthTypeEnumApi>
export type InstallCustomAuthTypeEnumApiOutput = zod.output<typeof InstallCustomAuthTypeEnumApi>

export const InstallSourceEnumApi = zod
    .enum(['posthog', 'posthog-code'])
    .describe('\* `posthog` - posthog\n\* `posthog-code` - posthog-code')

export type InstallSourceEnumApi = zod.input<typeof InstallSourceEnumApi>
export type InstallSourceEnumApiOutput = zod.output<typeof InstallSourceEnumApi>

export const MCPInstallationScopeEnumApi = zod
    .enum(['personal', 'shared'])
    .describe('\* `personal` - personal\n\* `shared` - shared')

export type MCPInstallationScopeEnumApi = zod.input<typeof MCPInstallationScopeEnumApi>
export type MCPInstallationScopeEnumApiOutput = zod.output<typeof MCPInstallationScopeEnumApi>

export const installCustomApiNameMax = 200

export const installCustomApiUrlMax = 2048

export const installCustomApiApiKeyDefault = ``
export const installCustomApiDescriptionDefault = ``
export const installCustomApiClientIdDefault = ``
export const installCustomApiClientSecretDefault = ``
export const installCustomApiInstallSourceDefault = `posthog`
export const installCustomApiPosthogCodeCallbackUrlDefault = ``
export const installCustomApiScopeDefault = `personal`
export const installCustomApiTeamEnabledDefault = true
export const installCustomApiReturnPathDefault = ``

export const InstallCustomApi = zod.object({
    name: zod.string().max(installCustomApiNameMax),
    url: zod.url().max(installCustomApiUrlMax),
    auth_type: InstallCustomAuthTypeEnumApi,
    api_key: zod.string().default(installCustomApiApiKeyDefault),
    description: zod.string().default(installCustomApiDescriptionDefault),
    client_id: zod.string().default(installCustomApiClientIdDefault),
    client_secret: zod.string().default(installCustomApiClientSecretDefault),
    install_source: InstallSourceEnumApi.default(installCustomApiInstallSourceDefault),
    posthog_code_callback_url: zod.string().default(installCustomApiPosthogCodeCallbackUrlDefault),
    scope: MCPInstallationScopeEnumApi.default(installCustomApiScopeDefault).describe(
        "'personal' is per-user; 'shared' makes the credential available to project members. Agent access is granted separately.\n\n\* `personal` - personal\n\* `shared` - shared"
    ),
    team_enabled: zod
        .boolean()
        .default(installCustomApiTeamEnabledDefault)
        .describe('Whether the server starts enabled for the whole team. Non-default values are admin-only.'),
    agent_ids: zod
        .array(zod.uuid())
        .optional()
        .describe(
            'Service accounts to share the server with at install time. Available to members when team settings allow member-managed agent access.'
        ),
    return_path: zod
        .string()
        .default(installCustomApiReturnPathDefault)
        .describe('In-app path to land back on after the OAuth round-trip. Must be a same-app relative path.'),
})

export type InstallCustomApi = zod.input<typeof InstallCustomApi>
export type InstallCustomApiOutput = zod.output<typeof InstallCustomApi>

export const OAuthRedirectResponseApi = zod.object({
    redirect_url: zod.url(),
})

export type OAuthRedirectResponseApi = zod.input<typeof OAuthRedirectResponseApi>
export type OAuthRedirectResponseApiOutput = zod.output<typeof OAuthRedirectResponseApi>

export const installTemplateApiApiKeyDefault = ``
export const installTemplateApiInstallSourceDefault = `posthog`
export const installTemplateApiPosthogCodeCallbackUrlDefault = ``
export const installTemplateApiScopeDefault = `personal`
export const installTemplateApiTeamEnabledDefault = true
export const installTemplateApiReturnPathDefault = ``

export const InstallTemplateApi = zod.object({
    template_id: zod.uuid(),
    api_key: zod.string().default(installTemplateApiApiKeyDefault),
    install_source: InstallSourceEnumApi.default(installTemplateApiInstallSourceDefault),
    posthog_code_callback_url: zod.string().default(installTemplateApiPosthogCodeCallbackUrlDefault),
    scope: MCPInstallationScopeEnumApi.default(installTemplateApiScopeDefault).describe(
        "'personal' is per-user; 'shared' makes the credential available to project members. Agent access is granted separately.\n\n\* `personal` - personal\n\* `shared` - shared"
    ),
    team_enabled: zod
        .boolean()
        .default(installTemplateApiTeamEnabledDefault)
        .describe('Whether the server starts enabled for the whole team. Non-default values are admin-only.'),
    agent_ids: zod
        .array(zod.uuid())
        .optional()
        .describe(
            'Service accounts to share the server with at install time. Available to members when team settings allow member-managed agent access.'
        ),
    return_path: zod
        .string()
        .default(installTemplateApiReturnPathDefault)
        .describe('In-app path to land back on after the OAuth round-trip. Must be a same-app relative path.'),
})

export type InstallTemplateApi = zod.input<typeof InstallTemplateApi>
export type InstallTemplateApiOutput = zod.output<typeof InstallTemplateApi>

export const mCPServerTemplateApiNameMax = 200

export const mCPServerTemplateApiUrlMax = 2048

export const mCPServerTemplateApiDocsUrlMax = 2048

export const MCPServerTemplateApi = zod.object({
    id: zod.uuid(),
    name: zod.string().max(mCPServerTemplateApiNameMax),
    url: zod.url().max(mCPServerTemplateApiUrlMax),
    docs_url: zod.url().max(mCPServerTemplateApiDocsUrlMax).optional(),
    description: zod.string().optional(),
    auth_type: MCPAuthTypeEnumApi.optional(),
    icon_key: zod
        .string()
        .describe(
            'Deprecated: use icon_domain instead. Lowercase key for clients that still render bundled icon assets.'
        ),
    icon_domain: zod
        .string()
        .describe(
            "The vendor's brand domain (e.g. 'linear.app'), resolved to an icon at render time via the logo.dev proxy endpoint. Empty when no brand icon is known."
        ),
    category: MCPServerCategoryEnumApi.optional(),
})

export type MCPServerTemplateApi = zod.input<typeof MCPServerTemplateApi>
export type MCPServerTemplateApiOutput = zod.output<typeof MCPServerTemplateApi>

export const PaginatedMCPServerTemplateListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(MCPServerTemplateApi),
})

export type PaginatedMCPServerTemplateListApi = zod.input<typeof PaginatedMCPServerTemplateListApi>
export type PaginatedMCPServerTemplateListApiOutput = zod.output<typeof PaginatedMCPServerTemplateListApi>
