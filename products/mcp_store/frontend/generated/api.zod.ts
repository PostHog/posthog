/**
 * Auto-generated Zod validation schemas from the Django backend OpenAPI schema.
 * To modify these schemas, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * Set the policy baseline for members or agents (admin-only).
 */
export const McpGatewayConfigApplyPresetCreateBody = /* @__PURE__ */ zod.object({
    audience: zod
        .enum(['members', 'agents'])
        .describe('\* `members` - members\n\* `agents` - agents')
        .describe("Which audience's baseline to overwrite.\n\n\* `members` - members\n\* `agents` - agents"),
    preset: zod
        .enum(['allow', 'user', 'ask', 'block'])
        .describe(
            '\* `allow` - Allow all\n\* `user` - Member decides\n\* `ask` - Ask for destructive\n\* `block` - Block destructive'
        )
        .describe(
            'Preset to apply.\n\n\* `allow` - Allow all\n\* `user` - Member decides\n\* `ask` - Ask for destructive\n\* `block` - Block destructive'
        ),
})

/**
 * Update team gateway settings (admin-only).
 */
export const McpGatewayConfigUpdateSettingsCreateBody = /* @__PURE__ */ zod.object({
    allow_custom_servers: zod
        .boolean()
        .optional()
        .describe('Whether non-admin members may register custom MCP servers.'),
    member_default_preset: zod
        .union([
            zod
                .enum(['allow', 'user', 'ask', 'block'])
                .describe(
                    '\* `allow` - Allow all\n\* `user` - Member decides\n\* `ask` - Ask for destructive\n\* `block` - Block destructive'
                ),
            zod.enum(['']),
        ])
        .optional()
        .describe(
            'Baseline preset for members.\n\n\* `allow` - Allow all\n\* `user` - Member decides\n\* `ask` - Ask for destructive\n\* `block` - Block destructive'
        ),
    agent_default_preset: zod
        .union([
            zod
                .enum(['allow', 'user', 'ask', 'block'])
                .describe(
                    '\* `allow` - Allow all\n\* `user` - Member decides\n\* `ask` - Ask for destructive\n\* `block` - Block destructive'
                ),
            zod.enum(['']),
        ])
        .optional()
        .describe(
            'Baseline preset for agents.\n\n\* `allow` - Allow all\n\* `user` - Member decides\n\* `ask` - Ask for destructive\n\* `block` - Block destructive'
        ),
})

/**
 * Turn one gateway server off (or back on) for one member.
 */
export const McpGatewayMembersSetAccessCreateBody = /* @__PURE__ */ zod.object({
    gateway_server_id: zod.uuid().describe('Gateway server to toggle for the member.'),
    enabled: zod.boolean().describe('False turns the server off for the member; true restores it.'),
})

/**
 * Team guardrails evaluated before any scope policy.
 */
export const mcpGatewayRulesCreateBodyNameMax = 200

export const mcpGatewayRulesCreateBodyToolPatternMax = 400

export const McpGatewayRulesCreateBody = /* @__PURE__ */ zod.object({
    name: zod
        .string()
        .max(mcpGatewayRulesCreateBodyNameMax)
        .describe('Short rule name shown wherever the rule locks a tool.'),
    description: zod.string().optional().describe('Why this guardrail exists.'),
    applies_to: zod
        .enum(['everyone', 'members', 'agents'])
        .describe('\* `everyone` - Everyone\n\* `members` - Members\n\* `agents` - Agents')
        .optional()
        .describe(
            'Audience the rule constrains.\n\n\* `everyone` - Everyone\n\* `members` - Members\n\* `agents` - Agents'
        ),
    effect: zod
        .enum(['needs_approval', 'do_not_use'])
        .describe('\* `needs_approval` - Require approval\n\* `do_not_use` - Block')
        .optional()
        .describe(
            'State the rule forces on matching tools.\n\n\* `needs_approval` - Require approval\n\* `do_not_use` - Block'
        ),
    tool_pattern: zod
        .string()
        .max(mcpGatewayRulesCreateBodyToolPatternMax)
        .optional()
        .describe('fnmatch pattern against tool names. Blank matches destructive tools heuristically.'),
    enabled: zod.boolean().optional().describe('Disabled rules are kept but not evaluated.'),
})

/**
 * Team guardrails evaluated before any scope policy.
 */
export const mcpGatewayRulesUpdateBodyNameMax = 200

export const mcpGatewayRulesUpdateBodyToolPatternMax = 400

export const McpGatewayRulesUpdateBody = /* @__PURE__ */ zod.object({
    name: zod
        .string()
        .max(mcpGatewayRulesUpdateBodyNameMax)
        .describe('Short rule name shown wherever the rule locks a tool.'),
    description: zod.string().optional().describe('Why this guardrail exists.'),
    applies_to: zod
        .enum(['everyone', 'members', 'agents'])
        .describe('\* `everyone` - Everyone\n\* `members` - Members\n\* `agents` - Agents')
        .optional()
        .describe(
            'Audience the rule constrains.\n\n\* `everyone` - Everyone\n\* `members` - Members\n\* `agents` - Agents'
        ),
    effect: zod
        .enum(['needs_approval', 'do_not_use'])
        .describe('\* `needs_approval` - Require approval\n\* `do_not_use` - Block')
        .optional()
        .describe(
            'State the rule forces on matching tools.\n\n\* `needs_approval` - Require approval\n\* `do_not_use` - Block'
        ),
    tool_pattern: zod
        .string()
        .max(mcpGatewayRulesUpdateBodyToolPatternMax)
        .optional()
        .describe('fnmatch pattern against tool names. Blank matches destructive tools heuristically.'),
    enabled: zod.boolean().optional().describe('Disabled rules are kept but not evaluated.'),
})

/**
 * Team guardrails evaluated before any scope policy.
 */
export const mcpGatewayRulesPartialUpdateBodyNameMax = 200

export const mcpGatewayRulesPartialUpdateBodyToolPatternMax = 400

export const McpGatewayRulesPartialUpdateBody = /* @__PURE__ */ zod.object({
    name: zod
        .string()
        .max(mcpGatewayRulesPartialUpdateBodyNameMax)
        .optional()
        .describe('Short rule name shown wherever the rule locks a tool.'),
    description: zod.string().optional().describe('Why this guardrail exists.'),
    applies_to: zod
        .enum(['everyone', 'members', 'agents'])
        .describe('\* `everyone` - Everyone\n\* `members` - Members\n\* `agents` - Agents')
        .optional()
        .describe(
            'Audience the rule constrains.\n\n\* `everyone` - Everyone\n\* `members` - Members\n\* `agents` - Agents'
        ),
    effect: zod
        .enum(['needs_approval', 'do_not_use'])
        .describe('\* `needs_approval` - Require approval\n\* `do_not_use` - Block')
        .optional()
        .describe(
            'State the rule forces on matching tools.\n\n\* `needs_approval` - Require approval\n\* `do_not_use` - Block'
        ),
    tool_pattern: zod
        .string()
        .max(mcpGatewayRulesPartialUpdateBodyToolPatternMax)
        .optional()
        .describe('fnmatch pattern against tool names. Blank matches destructive tools heuristically.'),
    enabled: zod.boolean().optional().describe('Disabled rules are kept but not evaluated.'),
})

/**
 * The team's gateway server registry. Registration happens through the
 * install/share flows in views.py — this surface reads, tunes, and removes.
 */
export const mcpGatewayServersUpdateBodyNameMax = 200

export const McpGatewayServersUpdateBody = /* @__PURE__ */ zod.object({
    name: zod
        .string()
        .max(mcpGatewayServersUpdateBodyNameMax)
        .optional()
        .describe('Display name shown across the gateway.'),
    description: zod.string().optional().describe('Short description shown on server cards.'),
    category: zod
        .enum(['business', 'data', 'design', 'dev', 'infra', 'productivity'])
        .describe(
            '\* `business` - Business Operations\n\* `data` - Data & Analytics\n\* `design` - Design & Content\n\* `dev` - Developer Tools & APIs\n\* `infra` - Infrastructure\n\* `productivity` - Productivity & Collaboration'
        )
        .optional()
        .describe(
            'Catalog category used for filter chips.\n\n\* `business` - Business Operations\n\* `data` - Data & Analytics\n\* `design` - Design & Content\n\* `dev` - Developer Tools & APIs\n\* `infra` - Infrastructure\n\* `productivity` - Productivity & Collaboration'
        ),
    is_team_enabled: zod
        .boolean()
        .optional()
        .describe('Master switch — off means members and agents can neither see nor call the server.'),
    allow_personal_connections: zod
        .boolean()
        .optional()
        .describe('For shared-credential servers: whether members may also connect their own account.'),
})

/**
 * The team's gateway server registry. Registration happens through the
 * install/share flows in views.py — this surface reads, tunes, and removes.
 */
export const mcpGatewayServersPartialUpdateBodyNameMax = 200

export const McpGatewayServersPartialUpdateBody = /* @__PURE__ */ zod.object({
    name: zod
        .string()
        .max(mcpGatewayServersPartialUpdateBodyNameMax)
        .optional()
        .describe('Display name shown across the gateway.'),
    description: zod.string().optional().describe('Short description shown on server cards.'),
    category: zod
        .enum(['business', 'data', 'design', 'dev', 'infra', 'productivity'])
        .describe(
            '\* `business` - Business Operations\n\* `data` - Data & Analytics\n\* `design` - Design & Content\n\* `dev` - Developer Tools & APIs\n\* `infra` - Infrastructure\n\* `productivity` - Productivity & Collaboration'
        )
        .optional()
        .describe(
            'Catalog category used for filter chips.\n\n\* `business` - Business Operations\n\* `data` - Data & Analytics\n\* `design` - Design & Content\n\* `dev` - Developer Tools & APIs\n\* `infra` - Infrastructure\n\* `productivity` - Productivity & Collaboration'
        ),
    is_team_enabled: zod
        .boolean()
        .optional()
        .describe('Master switch — off means members and agents can neither see nor call the server.'),
    allow_personal_connections: zod
        .boolean()
        .optional()
        .describe('For shared-credential servers: whether members may also connect their own account.'),
})

/**
 * Upsert per-tool states for a scope, returning the re-resolved catalog.
 */
export const mcpGatewayServersPoliciesCreateBodyScopeTypeDefault = `team`

export const McpGatewayServersPoliciesCreateBody = /* @__PURE__ */ zod.object({
    scope_type: zod
        .enum(['team', 'member', 'agent'])
        .describe('\* `team` - Team default\n\* `member` - Member\n\* `agent` - Agent')
        .default(mcpGatewayServersPoliciesCreateBodyScopeTypeDefault)
        .describe(
            'Which scope to resolve: the team default, one member, or one agent.\n\n\* `team` - Team default\n\* `member` - Member\n\* `agent` - Agent'
        ),
    scope_user_id: zod.number().optional().describe('Member scope target. Defaults to the requesting user.'),
    scope_service_account_id: zod.uuid().optional().describe('Agent scope target. Required when scope_type is agent.'),
    policies: zod
        .array(
            zod.object({
                tool_name: zod.string().describe('Tool to set the policy for.'),
                policy_state: zod
                    .enum(['approved', 'needs_approval', 'do_not_use'])
                    .describe(
                        '\* `approved` - Approved\n\* `needs_approval` - Needs approval\n\* `do_not_use` - Do not use'
                    )
                    .describe(
                        'State to apply for this scope.\n\n\* `approved` - Approved\n\* `needs_approval` - Needs approval\n\* `do_not_use` - Do not use'
                    ),
            })
        )
        .describe('Per-tool states to upsert for the scope.'),
})

/**
 * Create an agent and mint its gateway token (returned exactly once).
 */
export const mcpGatewayServiceAccountsCreateBodyNameMax = 200

export const mcpGatewayServiceAccountsCreateBodyDescriptionDefault = ``

export const McpGatewayServiceAccountsCreateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(mcpGatewayServiceAccountsCreateBodyNameMax).describe('Agent display name, e.g. Docs Agent.'),
    description: zod
        .string()
        .default(mcpGatewayServiceAccountsCreateBodyDescriptionDefault)
        .describe('What this agent does.'),
})

/**
 * Agent identities: creation mints a bearer token (shown once), access
 * grants tie them to gateway servers. Reads are open to members so agent
 * activity stays legible; every write is admin-only.
 */
export const mcpGatewayServiceAccountsUpdateBodyNameMax = 200

export const McpGatewayServiceAccountsUpdateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(mcpGatewayServiceAccountsUpdateBodyNameMax).optional().describe('Agent display name.'),
    description: zod.string().optional().describe('What this agent does.'),
    status: zod
        .enum(['active', 'paused'])
        .describe('\* `active` - Active\n\* `paused` - Paused')
        .optional()
        .describe('active, or paused (all access off).\n\n\* `active` - Active\n\* `paused` - Paused'),
})

/**
 * Agent identities: creation mints a bearer token (shown once), access
 * grants tie them to gateway servers. Reads are open to members so agent
 * activity stays legible; every write is admin-only.
 */
export const mcpGatewayServiceAccountsPartialUpdateBodyNameMax = 200

export const McpGatewayServiceAccountsPartialUpdateBody = /* @__PURE__ */ zod.object({
    name: zod
        .string()
        .max(mcpGatewayServiceAccountsPartialUpdateBodyNameMax)
        .optional()
        .describe('Agent display name.'),
    description: zod.string().optional().describe('What this agent does.'),
    status: zod
        .enum(['active', 'paused'])
        .describe('\* `active` - Active\n\* `paused` - Paused')
        .optional()
        .describe('active, or paused (all access off).\n\n\* `active` - Active\n\* `paused` - Paused'),
})

/**
 * Grant or revoke this agent's access to one gateway server.
 */
export const McpGatewayServiceAccountsAccessCreateBody = /* @__PURE__ */ zod.object({
    gateway_server_id: zod.uuid().describe('Gateway server to grant or revoke.'),
    enabled: zod.boolean().describe('True grants access, false revokes it.'),
    policies: zod
        .array(
            zod.object({
                tool_name: zod.string().describe('Tool to set the policy for.'),
                policy_state: zod
                    .enum(['approved', 'needs_approval', 'do_not_use'])
                    .describe(
                        '\* `approved` - Approved\n\* `needs_approval` - Needs approval\n\* `do_not_use` - Do not use'
                    )
                    .describe(
                        'State to apply for this scope.\n\n\* `approved` - Approved\n\* `needs_approval` - Needs approval\n\* `do_not_use` - Do not use'
                    ),
            })
        )
        .optional()
        .describe('Optional agent-scope tool policies to set alongside the grant.'),
})

export const mcpServerInstallationsCreateBodyDisplayNameMax = 200

export const mcpServerInstallationsCreateBodyUrlMax = 2048

export const McpServerInstallationsCreateBody = /* @__PURE__ */ zod.object({
    display_name: zod.string().max(mcpServerInstallationsCreateBodyDisplayNameMax).optional(),
    url: zod.url().max(mcpServerInstallationsCreateBodyUrlMax).optional(),
    description: zod.string().optional(),
    auth_type: zod.enum(['api_key', 'oauth']).optional().describe('\* `api_key` - API Key\n\* `oauth` - OAuth'),
    is_enabled: zod.boolean().optional(),
})

export const mcpServerInstallationsUpdateBodyDisplayNameMax = 200

export const mcpServerInstallationsUpdateBodyUrlMax = 2048

export const McpServerInstallationsUpdateBody = /* @__PURE__ */ zod.object({
    display_name: zod.string().max(mcpServerInstallationsUpdateBodyDisplayNameMax).optional(),
    url: zod.url().max(mcpServerInstallationsUpdateBodyUrlMax).optional(),
    description: zod.string().optional(),
    auth_type: zod.enum(['api_key', 'oauth']).optional().describe('\* `api_key` - API Key\n\* `oauth` - OAuth'),
    is_enabled: zod.boolean().optional(),
})

export const McpServerInstallationsPartialUpdateBody = /* @__PURE__ */ zod.object({
    display_name: zod.string().optional(),
    description: zod.string().optional(),
    is_enabled: zod.boolean().optional(),
})

export const mcpServerInstallationsProxyCreateBodyDisplayNameMax = 200

export const mcpServerInstallationsProxyCreateBodyUrlMax = 2048

export const McpServerInstallationsProxyCreateBody = /* @__PURE__ */ zod.object({
    display_name: zod.string().max(mcpServerInstallationsProxyCreateBodyDisplayNameMax).optional(),
    url: zod.url().max(mcpServerInstallationsProxyCreateBodyUrlMax).optional(),
    description: zod.string().optional(),
    auth_type: zod.enum(['api_key', 'oauth']).optional().describe('\* `api_key` - API Key\n\* `oauth` - OAuth'),
    is_enabled: zod.boolean().optional(),
})

export const McpServerInstallationsToolsPartialUpdateBody = /* @__PURE__ */ zod.object({
    approval_state: zod
        .enum(['approved', 'needs_approval', 'do_not_use'])
        .optional()
        .describe('\* `approved` - approved\n\* `needs_approval` - needs_approval\n\* `do_not_use` - do_not_use'),
})

export const mcpServerInstallationsToolsRefreshCreateBodyDisplayNameMax = 200

export const mcpServerInstallationsToolsRefreshCreateBodyUrlMax = 2048

export const McpServerInstallationsToolsRefreshCreateBody = /* @__PURE__ */ zod.object({
    display_name: zod.string().max(mcpServerInstallationsToolsRefreshCreateBodyDisplayNameMax).optional(),
    url: zod.url().max(mcpServerInstallationsToolsRefreshCreateBodyUrlMax).optional(),
    description: zod.string().optional(),
    auth_type: zod.enum(['api_key', 'oauth']).optional().describe('\* `api_key` - API Key\n\* `oauth` - OAuth'),
    is_enabled: zod.boolean().optional(),
})

export const mcpServerInstallationsInstallCustomCreateBodyNameMax = 200

export const mcpServerInstallationsInstallCustomCreateBodyUrlMax = 2048

export const mcpServerInstallationsInstallCustomCreateBodyApiKeyDefault = ``
export const mcpServerInstallationsInstallCustomCreateBodyDescriptionDefault = ``
export const mcpServerInstallationsInstallCustomCreateBodyClientIdDefault = ``
export const mcpServerInstallationsInstallCustomCreateBodyClientSecretDefault = ``
export const mcpServerInstallationsInstallCustomCreateBodyInstallSourceDefault = `posthog`
export const mcpServerInstallationsInstallCustomCreateBodyPosthogCodeCallbackUrlDefault = ``
export const mcpServerInstallationsInstallCustomCreateBodyScopeDefault = `personal`
export const mcpServerInstallationsInstallCustomCreateBodyTeamEnabledDefault = true
export const mcpServerInstallationsInstallCustomCreateBodyAllowPersonalDefault = true
export const mcpServerInstallationsInstallCustomCreateBodyReturnPathDefault = ``

export const McpServerInstallationsInstallCustomCreateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(mcpServerInstallationsInstallCustomCreateBodyNameMax),
    url: zod.url().max(mcpServerInstallationsInstallCustomCreateBodyUrlMax),
    auth_type: zod.enum(['api_key', 'oauth']).describe('\* `api_key` - api_key\n\* `oauth` - oauth'),
    api_key: zod.string().default(mcpServerInstallationsInstallCustomCreateBodyApiKeyDefault),
    description: zod.string().default(mcpServerInstallationsInstallCustomCreateBodyDescriptionDefault),
    client_id: zod.string().default(mcpServerInstallationsInstallCustomCreateBodyClientIdDefault),
    client_secret: zod.string().default(mcpServerInstallationsInstallCustomCreateBodyClientSecretDefault),
    install_source: zod
        .enum(['posthog', 'posthog-code'])
        .describe('\* `posthog` - posthog\n\* `posthog-code` - posthog-code')
        .default(mcpServerInstallationsInstallCustomCreateBodyInstallSourceDefault),
    posthog_code_callback_url: zod
        .string()
        .default(mcpServerInstallationsInstallCustomCreateBodyPosthogCodeCallbackUrlDefault),
    scope: zod
        .enum(['personal', 'shared'])
        .describe('\* `personal` - personal\n\* `shared` - shared')
        .default(mcpServerInstallationsInstallCustomCreateBodyScopeDefault)
        .describe(
            "'personal' is per-user; 'shared' is team-wide (visible to all project members and sandbox agents).\n\n\* `personal` - personal\n\* `shared` - shared"
        ),
    team_enabled: zod
        .boolean()
        .default(mcpServerInstallationsInstallCustomCreateBodyTeamEnabledDefault)
        .describe('Whether the server starts enabled for the whole team. Non-default values are admin-only.'),
    allow_personal: zod
        .boolean()
        .default(mcpServerInstallationsInstallCustomCreateBodyAllowPersonalDefault)
        .describe('For shared-credential servers: whether members may also connect personal accounts. Admin-only.'),
    agent_ids: zod
        .array(zod.uuid())
        .optional()
        .describe('Service accounts to share the server with at install time. Admin-only.'),
    return_path: zod
        .string()
        .default(mcpServerInstallationsInstallCustomCreateBodyReturnPathDefault)
        .describe('In-app path to land back on after the OAuth round-trip. Must be a same-app relative path.'),
})

export const mcpServerInstallationsInstallTemplateCreateBodyApiKeyDefault = ``
export const mcpServerInstallationsInstallTemplateCreateBodyInstallSourceDefault = `posthog`
export const mcpServerInstallationsInstallTemplateCreateBodyPosthogCodeCallbackUrlDefault = ``
export const mcpServerInstallationsInstallTemplateCreateBodyScopeDefault = `personal`
export const mcpServerInstallationsInstallTemplateCreateBodyTeamEnabledDefault = true
export const mcpServerInstallationsInstallTemplateCreateBodyAllowPersonalDefault = true
export const mcpServerInstallationsInstallTemplateCreateBodyReturnPathDefault = ``

export const McpServerInstallationsInstallTemplateCreateBody = /* @__PURE__ */ zod.object({
    template_id: zod.uuid(),
    api_key: zod.string().default(mcpServerInstallationsInstallTemplateCreateBodyApiKeyDefault),
    install_source: zod
        .enum(['posthog', 'posthog-code'])
        .describe('\* `posthog` - posthog\n\* `posthog-code` - posthog-code')
        .default(mcpServerInstallationsInstallTemplateCreateBodyInstallSourceDefault),
    posthog_code_callback_url: zod
        .string()
        .default(mcpServerInstallationsInstallTemplateCreateBodyPosthogCodeCallbackUrlDefault),
    scope: zod
        .enum(['personal', 'shared'])
        .describe('\* `personal` - personal\n\* `shared` - shared')
        .default(mcpServerInstallationsInstallTemplateCreateBodyScopeDefault)
        .describe(
            "'personal' is per-user; 'shared' is team-wide (visible to all project members and sandbox agents).\n\n\* `personal` - personal\n\* `shared` - shared"
        ),
    team_enabled: zod
        .boolean()
        .default(mcpServerInstallationsInstallTemplateCreateBodyTeamEnabledDefault)
        .describe('Whether the server starts enabled for the whole team. Non-default values are admin-only.'),
    allow_personal: zod
        .boolean()
        .default(mcpServerInstallationsInstallTemplateCreateBodyAllowPersonalDefault)
        .describe('For shared-credential servers: whether members may also connect personal accounts. Admin-only.'),
    agent_ids: zod
        .array(zod.uuid())
        .optional()
        .describe('Service accounts to share the server with at install time. Admin-only.'),
    return_path: zod
        .string()
        .default(mcpServerInstallationsInstallTemplateCreateBodyReturnPathDefault)
        .describe('In-app path to land back on after the OAuth round-trip. Must be a same-app relative path.'),
})
