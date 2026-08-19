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
 * Enable or disable every MCP server for the team (admin-only): flips
 * each registered server and the default for untouched catalog servers,
 * so newly published templates follow the same posture.
 */
export const McpGatewayConfigSetAllServersEnabledCreateBody = /* @__PURE__ */ zod.object({
    enabled: zod
        .boolean()
        .describe(
            'True enables every MCP server for the team; false disables them all. Applies to every registered server and becomes the default for untouched and future catalog servers.'
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
 * The team's gateway server registry. The registry is sparse: rows appear
 * through the install/share/OAuth-start flows in views.py, or when an admin
 * toggles an untouched catalog template here (`set_template_enabled`).
 * Servers with no row follow the team config's `default_servers_enabled`.
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
        .describe('Whether the team can see and call the server. Turning it off also blocks agent access.'),
})

/**
 * The team's gateway server registry. The registry is sparse: rows appear
 * through the install/share/OAuth-start flows in views.py, or when an admin
 * toggles an untouched catalog template here (`set_template_enabled`).
 * Servers with no row follow the team config's `default_servers_enabled`.
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
        .describe('Whether the team can see and call the server. Turning it off also blocks agent access.'),
})

/**
 * Upsert per-tool states for a scope, returning the re-resolved catalog.
 */
export const mcpGatewayServersPoliciesCreateBodyScopeTypeDefault = `team`
export const mcpGatewayServersPoliciesCreateBodyPoliciesItemToolNameMax = 200

export const mcpGatewayServersPoliciesCreateBodyPoliciesMax = 1000

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
                tool_name: zod
                    .string()
                    .max(mcpGatewayServersPoliciesCreateBodyPoliciesItemToolNameMax)
                    .describe('Tool to set the policy for, up to 200 characters.'),
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
        .max(mcpGatewayServersPoliciesCreateBodyPoliciesMax)
        .describe('Per-tool states to upsert for the scope. At most 1,000 entries per request.'),
})

/**
 * Enable or disable a catalog template for the team (admin-only),
 * materializing its gateway registration on the first toggle.
 */
export const McpGatewayServersSetTemplateEnabledCreateBody = /* @__PURE__ */ zod.object({
    template_id: zod.uuid().describe('Active catalog template to enable or disable for the team.'),
    enabled: zod
        .boolean()
        .describe('True lets the team see and call the server; false hides it from members and blocks connections.'),
})

/**
 * PostHog's built-in agents and their MCP access grants.
 *
 * The catalog is fixed. Projects can pause an agent's MCP access and grant or
 * revoke servers, but cannot create, rename, rotate, or delete agents.
 */
export const McpGatewayServiceAccountsUpdateBody = /* @__PURE__ */ zod.object({
    status: zod
        .enum(['active', 'paused'])
        .describe('\* `active` - Active\n\* `paused` - Paused')
        .optional()
        .describe('active, or paused (all MCP access off).\n\n\* `active` - Active\n\* `paused` - Paused'),
})

/**
 * PostHog's built-in agents and their MCP access grants.
 *
 * The catalog is fixed. Projects can pause an agent's MCP access and grant or
 * revoke servers, but cannot create, rename, rotate, or delete agents.
 */
export const McpGatewayServiceAccountsPartialUpdateBody = /* @__PURE__ */ zod.object({
    status: zod
        .enum(['active', 'paused'])
        .describe('\* `active` - Active\n\* `paused` - Paused')
        .optional()
        .describe('active, or paused (all MCP access off).\n\n\* `active` - Active\n\* `paused` - Paused'),
})

/**
 * Share, or stop sharing, one gateway server with this agent.
 *
 * Sharing is personal. `enabled=true` delegates the caller's own
 * connection, and the agent may use it only when acting for the caller,
 * unless the caller sends `scope=team` to lend it to the project's agent
 * runs generally. Scope only ever applies to the caller's own share: it is
 * their credential to lend, so no admin permission is involved and no
 * member can change someone else's share.
 * `enabled=false` removes the caller's own share and leaves other members'
 * shares, and the agent's tool policies, in place.
 *
 * Project admins can send `all=true` alongside `enabled=false` to remove
 * every member's share of this server with this agent, along with the
 * agent's tool policies for it.
 */
export const mcpGatewayServiceAccountsAccessCreateBodyScopeDefault = `personal`
export const mcpGatewayServiceAccountsAccessCreateBodyAllDefault = false
export const mcpGatewayServiceAccountsAccessCreateBodyPoliciesItemToolNameMax = 200

export const mcpGatewayServiceAccountsAccessCreateBodyPoliciesMax = 1000

export const McpGatewayServiceAccountsAccessCreateBody = /* @__PURE__ */ zod.object({
    gateway_server_id: zod.uuid().describe('Gateway server to share or stop sharing.'),
    enabled: zod
        .boolean()
        .describe("True shares the caller's own connection with the agent, false removes the caller's share."),
    scope: zod
        .enum(['personal', 'team'])
        .describe('\* `personal` - Personal\n\* `team` - Team')
        .default(mcpGatewayServiceAccountsAccessCreateBodyScopeDefault)
        .describe(
            "Applies to the caller's own share, and only alongside enabled=true. 'personal' lets the agent use the connection when it works for the caller. 'team' lets it use the connection for the whole project's agent runs, including runs nobody started. It never lets another person use the connection. Defaults to personal, so re-sharing without this field resets the caller's share to personal.\n\n\* `personal` - Personal\n\* `team` - Team"
        ),
    all: zod
        .boolean()
        .default(mcpGatewayServiceAccountsAccessCreateBodyAllDefault)
        .describe(
            "Only valid with enabled=false. Removes every member's share of this server with this agent, along with the agent's tool policies for it. Project admins only."
        ),
    policies: zod
        .array(
            zod.object({
                tool_name: zod
                    .string()
                    .max(mcpGatewayServiceAccountsAccessCreateBodyPoliciesItemToolNameMax)
                    .describe('Tool to set the policy for, up to 200 characters.'),
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
        .max(mcpGatewayServiceAccountsAccessCreateBodyPoliciesMax)
        .optional()
        .describe('Optional agent-scope tool policies to set alongside the grant. At most 1,000 entries per request.'),
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

/**
 * Invoke one tool on a connected MCP server.
 *
 * The request/response shape is plain REST rather than the JSON-RPC envelope
 * `proxy` speaks, because the caller here is an agent surface (the PostHog MCP's
 * `exec`) that wants one tool result, not an MCP transport of its own.
 */
export const mcpServerInstallationsCallToolCreateBodyToolNameMax = 200

export const McpServerInstallationsCallToolCreateBody = /* @__PURE__ */ zod.object({
    tool_name: zod
        .string()
        .max(mcpServerInstallationsCallToolCreateBodyToolNameMax)
        .describe('Name of the tool to invoke, exactly as the upstream server reports it.'),
    arguments: zod
        .record(zod.string(), zod.unknown())
        .optional()
        .describe('Arguments object passed straight to the tool, matching its input schema.'),
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
            "'personal' is per-user; 'shared' makes the credential available to project members. Agent access is granted separately.\n\n\* `personal` - personal\n\* `shared` - shared"
        ),
    team_enabled: zod
        .boolean()
        .default(mcpServerInstallationsInstallCustomCreateBodyTeamEnabledDefault)
        .describe('Whether the server starts enabled for the whole team. Non-default values are admin-only.'),
    agent_ids: zod
        .array(zod.uuid())
        .optional()
        .describe(
            'Service accounts to share the server with at install time. Available to members when team settings allow member-managed agent access.'
        ),
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
            "'personal' is per-user; 'shared' makes the credential available to project members. Agent access is granted separately.\n\n\* `personal` - personal\n\* `shared` - shared"
        ),
    team_enabled: zod
        .boolean()
        .default(mcpServerInstallationsInstallTemplateCreateBodyTeamEnabledDefault)
        .describe('Whether the server starts enabled for the whole team. Non-default values are admin-only.'),
    agent_ids: zod
        .array(zod.uuid())
        .optional()
        .describe(
            'Service accounts to share the server with at install time. Available to members when team settings allow member-managed agent access.'
        ),
    return_path: zod
        .string()
        .default(mcpServerInstallationsInstallTemplateCreateBodyReturnPathDefault)
        .describe('In-app path to land back on after the OAuth round-trip. Must be a same-app relative path.'),
})
