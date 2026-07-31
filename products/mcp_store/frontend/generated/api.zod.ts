/**
 * Auto-generated Zod validation schemas from the Django backend OpenAPI schema.
 * To modify these schemas, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import {
    ApplyPresetApi,
    GatewayConfigUpdateApi,
    GatewayPoliciesUpsertApi,
    InstallCustomApi,
    InstallTemplateApi,
    MCPGatewayServerUpdateApi,
    MCPOrgRuleApi,
    MCPServerInstallationApi,
    MCPServiceAccountUpdateApi,
    MemberAccessUpdateApi,
    PatchedMCPGatewayServerUpdateApi,
    PatchedMCPOrgRuleApi,
    PatchedMCPServerInstallationUpdateApi,
    PatchedMCPServiceAccountUpdateApi,
    PatchedToolApprovalUpdateApi,
    ServiceAccountAccessUpdateApi,
    SetAllServersEnabledApi,
    SetTemplateEnabledApi,
} from './api.zod.schemas'

/**
 * Set the policy baseline for members or agents (admin-only).
 */
export const McpGatewayConfigApplyPresetCreateBody = ApplyPresetApi

/**
 * Enable or disable every MCP server for the team (admin-only): flips
 * each registered server and the default for untouched catalog servers,
 * so newly published templates follow the same posture.
 */
export const McpGatewayConfigSetAllServersEnabledCreateBody = SetAllServersEnabledApi

/**
 * Update team gateway settings (admin-only).
 */
export const McpGatewayConfigUpdateSettingsCreateBody = GatewayConfigUpdateApi

/**
 * Turn one gateway server off (or back on) for one member.
 */
export const McpGatewayMembersSetAccessCreateBody = MemberAccessUpdateApi

/**
 * Team guardrails evaluated before any scope policy.
 */
export const McpGatewayRulesCreateBody = MCPOrgRuleApi

/**
 * Team guardrails evaluated before any scope policy.
 */
export const McpGatewayRulesUpdateBody = MCPOrgRuleApi

/**
 * Team guardrails evaluated before any scope policy.
 */
export const McpGatewayRulesPartialUpdateBody = PatchedMCPOrgRuleApi

/**
 * The team's gateway server registry. The registry is sparse: rows appear
 * through the install/share/OAuth-start flows in views.py, or when an admin
 * toggles an untouched catalog template here (`set_template_enabled`).
 * Servers with no row follow the team config's `default_servers_enabled`.
 */
export const McpGatewayServersUpdateBody = MCPGatewayServerUpdateApi

/**
 * The team's gateway server registry. The registry is sparse: rows appear
 * through the install/share/OAuth-start flows in views.py, or when an admin
 * toggles an untouched catalog template here (`set_template_enabled`).
 * Servers with no row follow the team config's `default_servers_enabled`.
 */
export const McpGatewayServersPartialUpdateBody = PatchedMCPGatewayServerUpdateApi

/**
 * Upsert per-tool states for a scope, returning the re-resolved catalog.
 */
export const McpGatewayServersPoliciesCreateBody = GatewayPoliciesUpsertApi

/**
 * Enable or disable a catalog template for the team (admin-only),
 * materializing its gateway registration on the first toggle.
 */
export const McpGatewayServersSetTemplateEnabledCreateBody = SetTemplateEnabledApi

/**
 * PostHog's built-in agents and their MCP access grants.
 *
 * The catalog is fixed. Projects can pause an agent's MCP access and grant or
 * revoke servers, but cannot create, rename, rotate, or delete agents.
 */
export const McpGatewayServiceAccountsUpdateBody = MCPServiceAccountUpdateApi

/**
 * PostHog's built-in agents and their MCP access grants.
 *
 * The catalog is fixed. Projects can pause an agent's MCP access and grant or
 * revoke servers, but cannot create, rename, rotate, or delete agents.
 */
export const McpGatewayServiceAccountsPartialUpdateBody = PatchedMCPServiceAccountUpdateApi

/**
 * Grant or revoke this agent's access to one gateway server.
 */
export const McpGatewayServiceAccountsAccessCreateBody = ServiceAccountAccessUpdateApi

export const McpServerInstallationsCreateBody = MCPServerInstallationApi

export const McpServerInstallationsUpdateBody = MCPServerInstallationApi

export const McpServerInstallationsPartialUpdateBody = PatchedMCPServerInstallationUpdateApi

export const McpServerInstallationsProxyCreateBody = MCPServerInstallationApi

export const McpServerInstallationsToolsPartialUpdateBody = PatchedToolApprovalUpdateApi

export const McpServerInstallationsToolsRefreshCreateBody = MCPServerInstallationApi

export const McpServerInstallationsInstallCustomCreateBody = InstallCustomApi

export const McpServerInstallationsInstallTemplateCreateBody = InstallTemplateApi
