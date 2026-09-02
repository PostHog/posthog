import { MakeLogicType, actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'

import { lemonToast } from '@posthog/lemon-ui'

import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import { UserType } from '~/types'

import {
    mcpGatewayConfigApplyPresetCreate,
    mcpGatewayConfigList,
    mcpGatewayConfigSetAllServersEnabledCreate,
    mcpGatewayConfigUpdateSettingsCreate,
    mcpGatewayMembersList,
    mcpGatewayMembersSetAccessCreate,
    mcpGatewayRulesList,
    mcpGatewayRulesPartialUpdate,
    mcpGatewayServersDestroy,
    mcpGatewayServersList,
    mcpGatewayServersPartialUpdate,
    mcpGatewayServersSetTemplateEnabledCreate,
    mcpGatewayServiceAccountsAccessCreate,
    mcpGatewayServiceAccountsList,
    mcpGatewayServiceAccountsPartialUpdate,
    getMcpServerInstallationsAuthorizeRetrieveUrl,
    mcpServerInstallationsDestroy,
    mcpServerInstallationsInstallCustomCreate,
    mcpServerInstallationsInstallTemplateCreate,
    mcpServerInstallationsPartialUpdate,
    mcpServerInstallationsToolsRefreshCreate,
    mcpServersList,
} from '../generated/api'
import {
    AudienceEnumApi,
    GatewayMemberSummaryApi,
    InstallCustomAuthTypeEnumApi,
    MCPAgentGrantScopeEnumApi,
    MCPGatewayServerApi,
    MCPOrgRuleApi,
    MCPPolicyPresetEnumApi,
    MCPServerTemplateApi,
    MCPServiceAccountApi,
    TeamMCPGatewayConfigApi,
    ToolPolicyEntryApi,
    UserBasicApi,
} from '../generated/api.schemas'
import {
    buildGatewayInstallRequest,
    canSubmitGatewayServer,
    GATEWAY_ADD_SERVER_DEFAULTS,
    GatewayAddServerValues,
} from './gatewayAddServer'

export const GATEWAY_CATEGORY_LABELS: Record<string, string> = {
    business: 'Business operations',
    data: 'Data & analytics',
    design: 'Design & content',
    dev: 'Developer tools & APIs',
    infra: 'Infrastructure',
    productivity: 'Productivity & collaboration',
}

function currentProjectId(): string {
    return String(teamLogic.values.currentTeamId)
}

function currentReturnPath(): string {
    return `${router.values.location.pathname}${window.location.search}${window.location.hash}`
}

/** The registry is sparse: catalog templates without a row are rendered from
 * client-side entries whose ids carry this prefix. */
export const TEMPLATE_SERVER_ID_PREFIX = 'template:'

/** A real registry row, or a catalog template synthesized client-side (no
 * `created_by` until an install or admin toggle materializes the row). */
export type GatewayServerEntry = MCPGatewayServerApi

export function isTemplateOnlyServer(server: Pick<GatewayServerEntry, 'id'>): boolean {
    return server.id.startsWith(TEMPLATE_SERVER_ID_PREFIX)
}

function normalizeServerUrl(url: string): string {
    return url.replace(/\/+$/, '')
}

function templateAsGatewayServer(template: MCPServerTemplateApi, enabled: boolean): GatewayServerEntry {
    return {
        id: `${TEMPLATE_SERVER_ID_PREFIX}${template.id}`,
        name: template.name,
        url: template.url,
        description: template.description ?? '',
        category: template.category ?? 'dev',
        template_auth_type: template.auth_type ?? 'oauth',
        is_team_enabled: enabled,
        icon_key: template.icon_key,
        icon_domain: template.icon_domain,
        docs_url: template.docs_url ?? '',
        template_id: template.id,
        tool_count: 0,
        connections: [],
        your_connection: null,
        agents: [],
        revoked_user_ids: [],
        is_revoked_for_you: false,
        created_by: null,
        created_at: '',
        updated_at: '',
    }
}

async function fetchGatewayServers(): Promise<MCPGatewayServerApi[]> {
    const response = await mcpGatewayServersList(currentProjectId(), { limit: 500 })
    return response.results
}

function errorDetail(error: unknown): string | null {
    if (typeof error !== 'object' || error === null || !('detail' in error)) {
        return null
    }
    return typeof error.detail === 'string' ? error.detail : null
}

export function agentServerAccessKey(accountId: string, serverId: string): string {
    return `${accountId}:${serverId}`
}

export function memberServerAccessKey(userId: number, serverId: string): string {
    return `${userId}:${serverId}`
}

/** Who backs an agent's access to one server. A grant delegates one person's own
 * connection, so the same agent and server can carry one grant per member. */
export interface AgentServerShare {
    sharedByYou: boolean
    /** Scope of your own grant, and 'personal' when you have none, so the scope
     * control has a value to render before the first share exists. */
    yourScope: MCPAgentGrantScopeEnumApi
    sharedByOthers: UserBasicApi[]
    /** The subset of `sharedByOthers` whose grant is team-scoped, which is the
     * only teammate grant that also backs agent runs other than the sharer's. */
    teamSharedByOthers: UserBasicApi[]
}

export function agentServerShare(
    account: MCPServiceAccountApi | null,
    serverId: string,
    currentUserId: number | null
): AgentServerShare {
    // Until the user loads there is no way to tell your own grants from anyone
    // else's, and calling them all teammates' would misattribute your own.
    if (currentUserId === null) {
        return { sharedByYou: false, yourScope: 'personal', sharedByOthers: [], teamSharedByOthers: [] }
    }
    const grants = (account?.servers ?? []).filter((server) => server.id === serverId)
    const yours = grants.find((server) => server.shared_by.id === currentUserId)
    const others = grants.filter((server) => server.shared_by.id !== currentUserId)
    return {
        sharedByYou: yours !== undefined,
        yourScope: yours?.scope ?? 'personal',
        sharedByOthers: others.map((server) => server.shared_by),
        teamSharedByOthers: others.filter((server) => server.scope === 'team').map((server) => server.shared_by),
    }
}

export const GATEWAY_MEMBERS_PAGE_SIZE = 500
export const GATEWAY_CONNECTION_REFRESH_DELAYS_MS = [1500, 5000] as const

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface mcpGatewayLogicValues {
    user: UserType | null // userLogic
    accountStatusLoadingIds: Set<string>
    activeAgentCount: number
    addServerForm: GatewayAddServerValues
    addServerModalOpen: boolean
    addServerSubmitDisabledReason: string | null
    addingServer: boolean
    agentServerAccessLoadingKeys: Set<string>
    agentSharedServerCounts: Record<string, number>
    allServersEnabledLoading: boolean
    allServersEnabledTarget: boolean | null
    allowCustomServers: boolean
    allowCustomServersLoading: boolean
    allowMemberAgentAccess: boolean
    allowMemberAgentAccessLoading: boolean
    applyingPresetByAudience: Partial<Record<AudienceEnumApi, MCPPolicyPresetEnumApi>>
    canAddServers: boolean
    canManageAgentAccess: boolean
    categoryCounts: Record<string, number>
    categoryFilter: string | null
    config: TeamMCPGatewayConfigApi | null
    configLoading: boolean
    configMutationInProgress: boolean
    connectedServers: GatewayServerEntry[]
    connectingServerId: string | null
    connectionApiKey: string
    connectionAuthType: InstallCustomAuthTypeEnumApi
    connectionClientId: string
    connectionClientSecret: string
    connectionModalServer: GatewayServerEntry | null
    connectionModalServerId: string | null
    connectionSubmitDisabledReason: string | null
    currentUserId: number | null
    defaultServersEnabled: boolean
    disconnectingInstallationIds: Set<string>
    enabledServerCount: number
    filteredServers: GatewayServerEntry[]
    isAdmin: boolean
    memberCount: number
    memberServerAccessLoadingKeys: Set<string>
    members: GatewayMemberSummaryApi[]
    membersInitialized: boolean
    membersLoading: boolean
    membersOffset: number
    mergedServers: GatewayServerEntry[]
    recommendedTemplates: MCPServerTemplateApi[]
    refreshingInstallationIds: Set<string>
    removingServerIds: Set<string>
    ruleEnabledLoadingIds: Set<string>
    rules: MCPOrgRuleApi[]
    rulesLoading: boolean
    searchQuery: string
    serverEnabledLoadingIds: Set<string>
    servers: MCPGatewayServerApi[]
    serversInitialized: boolean
    serversLoadFailed: boolean
    serversLoading: boolean
    serviceAccounts: MCPServiceAccountApi[]
    serviceAccountsInitialized: boolean
    serviceAccountsLoading: boolean
    templateEnabledLoadingIds: Set<string>
    templateOnlyServers: GatewayServerEntry[]
    templates: MCPServerTemplateApi[]
    templatesLoading: boolean
    updatingInstallationIds: Set<string>
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface mcpGatewayLogicActions {
    applyPreset: (
        audience: AudienceEnumApi,
        preset: MCPPolicyPresetEnumApi
    ) => {
        audience: AudienceEnumApi
        preset: MCPPolicyPresetEnumApi
    }
    applyPresetComplete: (audience: AudienceEnumApi) => {
        audience: AudienceEnumApi
    }
    applyPresetStarted: (
        audience: AudienceEnumApi,
        preset: MCPPolicyPresetEnumApi
    ) => {
        audience: AudienceEnumApi
        preset: MCPPolicyPresetEnumApi
    }
    closeAddServerModal: () => {
        value: true
    }
    closeConnectionModal: () => {
        value: true
    }
    connectServer: (serverId: string) => {
        serverId: string
    }
    disconnectServer: (
        serverId: string,
        installationId: string,
        navigateToServers?: any
    ) => {
        installationId: string
        navigateToServers: any
        serverId: string
    }
    disconnectServerComplete: (installationId: string) => {
        installationId: string
    }
    disconnectServerSuccess: (
        serverId: string,
        navigateToServers: boolean
    ) => {
        navigateToServers: boolean
        serverId: string
    }
    loadConfig: () => any
    loadConfigFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadConfigSuccess: (
        config: TeamMCPGatewayConfigApi,
        payload?: any
    ) => {
        config: TeamMCPGatewayConfigApi
        payload?: any
    }
    loadMembers: (_: void) => void
    loadMembersFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadMembersSuccess: (
        members: GatewayMemberSummaryApi[],
        payload?: void
    ) => {
        members: GatewayMemberSummaryApi[]
        payload?: void
    }
    loadRules: () => any
    loadRulesFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadRulesSuccess: (
        rules: MCPOrgRuleApi[],
        payload?: any
    ) => {
        rules: MCPOrgRuleApi[]
        payload?: any
    }
    loadServers: () => any
    loadServersFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadServersSuccess: (
        servers: MCPGatewayServerApi[],
        payload?: any
    ) => {
        servers: MCPGatewayServerApi[]
        payload?: any
    }
    loadServiceAccounts: () => any
    loadServiceAccountsFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadServiceAccountsSuccess: (
        serviceAccounts: MCPServiceAccountApi[],
        payload?: any
    ) => {
        serviceAccounts: MCPServiceAccountApi[]
        payload?: any
    }
    loadTemplates: () => any
    loadTemplatesFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadTemplatesSuccess: (
        templates: MCPServerTemplateApi[],
        payload?: any
    ) => {
        templates: MCPServerTemplateApi[]
        payload?: any
    }
    openAddServerModal: () => {
        value: true
    }
    openConnectionModal: (
        serverId: string,
        authType: InstallCustomAuthTypeEnumApi
    ) => {
        authType: InstallCustomAuthTypeEnumApi
        serverId: string
    }
    performConnection: (
        serverId: string,
        authType: InstallCustomAuthTypeEnumApi,
        apiKey: string,
        clientId: string,
        clientSecret: string
    ) => {
        apiKey: string
        authType: InstallCustomAuthTypeEnumApi
        clientId: string
        clientSecret: string
        serverId: string
    }
    performConnectionComplete: () => {
        value: true
    }
    reconnectServer: (installationId: string) => {
        installationId: string
    }
    refreshServerTools: (installationId: string) => {
        installationId: string
    }
    refreshServerToolsComplete: (installationId: string) => {
        installationId: string
    }
    refreshServerToolsSuccess: (installationId: string) => {
        installationId: string
    }
    refreshServersAfterConnection: () => {
        value: true
    }
    removeAllAgentServerShares: (
        accountId: string,
        serverId: string
    ) => {
        accountId: string
        serverId: string
    }
    removeServer: (serverId: string) => {
        serverId: string
    }
    removeServerComplete: (serverId: string) => {
        serverId: string
    }
    removeServerSuccess: (serverId: string) => {
        serverId: string
    }
    setAddServerFormValue: (
        field: keyof GatewayAddServerValues,
        value: GatewayAddServerValues[keyof GatewayAddServerValues]
    ) => {
        field: keyof GatewayAddServerValues
        value: boolean | string
    }
    setAgentServerAccess: (
        accountId: string,
        serverId: string,
        enabled: boolean,
        scope?: MCPAgentGrantScopeEnumApi,
        policies?: ToolPolicyEntryApi[]
    ) => {
        accountId: string
        enabled: boolean
        policies: ToolPolicyEntryApi[] | undefined
        scope: MCPAgentGrantScopeEnumApi
        serverId: string
    }
    setAgentServerAccessComplete: (
        accountId: string,
        serverId: string
    ) => {
        accountId: string
        serverId: string
    }
    setAgentServerAccessSuccess: (
        accountId: string,
        serverId: string
    ) => {
        accountId: string
        serverId: string
    }
    setAllServersEnabled: (enabled: boolean) => {
        enabled: boolean
    }
    setAllServersEnabledComplete: () => {
        value: true
    }
    setAllowCustomServers: (allowed: boolean) => {
        allowed: boolean
    }
    setAllowCustomServersComplete: () => {
        value: true
    }
    setAllowMemberAgentAccess: (allowed: boolean) => {
        allowed: boolean
    }
    setAllowMemberAgentAccessComplete: () => {
        value: true
    }
    setCategoryFilter: (category: string | null) => {
        category: string | null
    }
    setConnectionApiKey: (apiKey: string) => {
        apiKey: string
    }
    setConnectionAuthType: (authType: InstallCustomAuthTypeEnumApi) => {
        authType: InstallCustomAuthTypeEnumApi
    }
    setConnectionClientId: (clientId: string) => {
        clientId: string
    }
    setConnectionClientSecret: (clientSecret: string) => {
        clientSecret: string
    }
    setMemberCount: (memberCount: number) => {
        memberCount: number
    }
    setMemberServerAccess: (
        userId: number,
        serverId: string,
        enabled: boolean
    ) => {
        enabled: boolean
        serverId: string
        userId: number
    }
    setMemberServerAccessComplete: (
        userId: number,
        serverId: string
    ) => {
        serverId: string
        userId: number
    }
    setMembersOffset: (membersOffset: number) => {
        membersOffset: number
    }
    setSearchQuery: (query: string) => {
        query: string
    }
    setTemplateEnabled: (
        templateId: string,
        enabled: boolean
    ) => {
        enabled: boolean
        templateId: string
    }
    setTemplateEnabledComplete: (templateId: string) => {
        templateId: string
    }
    submitAddServer: () => {
        value: true
    }
    submitAddServerComplete: () => {
        value: true
    }
    submitAddServerStarted: () => {
        value: true
    }
    submitConnection: () => {
        value: true
    }
    toggleAccountStatus: (
        accountId: string,
        paused: boolean
    ) => {
        accountId: string
        paused: boolean
    }
    toggleAccountStatusComplete: (accountId: string) => {
        accountId: string
    }
    toggleRuleEnabled: (
        ruleId: string,
        enabled: boolean
    ) => {
        enabled: boolean
        ruleId: string
    }
    toggleRuleEnabledComplete: (ruleId: string) => {
        ruleId: string
    }
    toggleServerEnabled: (
        serverId: string,
        enabled: boolean
    ) => {
        enabled: boolean
        serverId: string
    }
    toggleServerEnabledComplete: (serverId: string) => {
        serverId: string
    }
    toggleYourConnectionEnabled: (
        installationId: string,
        enabled: boolean
    ) => {
        enabled: boolean
        installationId: string
    }
    toggleYourConnectionEnabledComplete: (installationId: string) => {
        installationId: string
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface mcpGatewayLogicMeta {
    __keaTypeGenInternalSelectorTypes: {
        currentUserId: (user: UserType | null) => number | null
        addServerSubmitDisabledReason: (addServerForm: GatewayAddServerValues, addingServer: boolean) => string | null
        isAdmin: (config: TeamMCPGatewayConfigApi | null) => boolean
        allowCustomServers: (config: TeamMCPGatewayConfigApi | null) => boolean
        allowMemberAgentAccess: (config: TeamMCPGatewayConfigApi | null) => boolean
        canAddServers: (isAdmin: boolean, allowCustomServers: boolean) => boolean
        canManageAgentAccess: (isAdmin: boolean, allowMemberAgentAccess: boolean) => boolean
        defaultServersEnabled: (config: TeamMCPGatewayConfigApi | null) => boolean
        configMutationInProgress: (
            allowCustomServersLoading: boolean,
            allowMemberAgentAccessLoading: boolean,
            allServersEnabledLoading: boolean,
            applyingPresetByAudience: Partial<Record<AudienceEnumApi, MCPPolicyPresetEnumApi>>
        ) => boolean
        recommendedTemplates: (
            templates: MCPServerTemplateApi[],
            servers: MCPGatewayServerApi[],
            config: TeamMCPGatewayConfigApi | null
        ) => MCPServerTemplateApi[]
        templateOnlyServers: (
            recommendedTemplates: MCPServerTemplateApi[],
            defaultServersEnabled: boolean,
            isAdmin: boolean
        ) => GatewayServerEntry[]
        mergedServers: (
            servers: MCPGatewayServerApi[],
            templateOnlyServers: MCPGatewayServerApi[]
        ) => GatewayServerEntry[]
        connectionModalServer: (
            mergedServers: MCPGatewayServerApi[],
            connectionModalServerId: string | null
        ) => GatewayServerEntry | null
        connectionSubmitDisabledReason: (
            connectionModalServer: MCPGatewayServerApi | null,
            connectionAuthType: InstallCustomAuthTypeEnumApi,
            connectionApiKey: string
        ) => string | null
        categoryCounts: (mergedServers: MCPGatewayServerApi[]) => Record<string, number>
        connectedServers: (mergedServers: MCPGatewayServerApi[]) => GatewayServerEntry[]
        filteredServers: (
            mergedServers: MCPGatewayServerApi[],
            searchQuery: string,
            categoryFilter: string | null
        ) => GatewayServerEntry[]
        activeAgentCount: (serviceAccounts: MCPServiceAccountApi[]) => number
        agentSharedServerCounts: (serviceAccounts: MCPServiceAccountApi[]) => Record<string, number>
        enabledServerCount: (mergedServers: MCPGatewayServerApi[]) => number
    }
}

export type mcpGatewayLogicType = MakeLogicType<
    mcpGatewayLogicValues,
    mcpGatewayLogicActions,
    Record<string, any>,
    mcpGatewayLogicMeta
>

export const mcpGatewayLogic = kea<mcpGatewayLogicType>([
    path(['products', 'mcp_store', 'frontend', 'gateway', 'mcpGatewayLogic']),

    connect(() => ({
        values: [userLogic, ['user']],
    })),

    actions({
        openAddServerModal: true,
        closeAddServerModal: true,
        setAddServerFormValue: (
            field: keyof GatewayAddServerValues,
            value: GatewayAddServerValues[keyof GatewayAddServerValues]
        ) => ({ field, value }),
        submitAddServer: true,
        submitAddServerStarted: true,
        submitAddServerComplete: true,
        setSearchQuery: (query: string) => ({ query }),
        setCategoryFilter: (category: string | null) => ({ category }),
        toggleServerEnabled: (serverId: string, enabled: boolean) => ({ serverId, enabled }),
        toggleServerEnabledComplete: (serverId: string) => ({ serverId }),
        removeServer: (serverId: string) => ({ serverId }),
        removeServerSuccess: (serverId: string) => ({ serverId }),
        removeServerComplete: (serverId: string) => ({ serverId }),
        connectServer: (serverId: string) => ({ serverId }),
        reconnectServer: (installationId: string) => ({ installationId }),
        refreshServersAfterConnection: true,
        refreshServerTools: (installationId: string) => ({ installationId }),
        refreshServerToolsSuccess: (installationId: string) => ({ installationId }),
        refreshServerToolsComplete: (installationId: string) => ({ installationId }),
        openConnectionModal: (serverId: string, authType: InstallCustomAuthTypeEnumApi) => ({
            serverId,
            authType,
        }),
        closeConnectionModal: true,
        setConnectionAuthType: (authType: InstallCustomAuthTypeEnumApi) => ({ authType }),
        setConnectionApiKey: (apiKey: string) => ({ apiKey }),
        setConnectionClientId: (clientId: string) => ({ clientId }),
        setConnectionClientSecret: (clientSecret: string) => ({ clientSecret }),
        submitConnection: true,
        performConnection: (
            serverId: string,
            authType: InstallCustomAuthTypeEnumApi,
            apiKey: string,
            clientId: string,
            clientSecret: string
        ) => ({ serverId, authType, apiKey, clientId, clientSecret }),
        performConnectionComplete: true,
        disconnectServer: (serverId: string, installationId: string, navigateToServers = false) => ({
            serverId,
            installationId,
            navigateToServers,
        }),
        disconnectServerSuccess: (serverId: string, navigateToServers: boolean) => ({ serverId, navigateToServers }),
        disconnectServerComplete: (installationId: string) => ({ installationId }),
        toggleYourConnectionEnabled: (installationId: string, enabled: boolean) => ({ installationId, enabled }),
        toggleYourConnectionEnabledComplete: (installationId: string) => ({ installationId }),
        toggleAccountStatus: (accountId: string, paused: boolean) => ({ accountId, paused }),
        toggleAccountStatusComplete: (accountId: string) => ({ accountId }),
        toggleRuleEnabled: (ruleId: string, enabled: boolean) => ({ ruleId, enabled }),
        toggleRuleEnabledComplete: (ruleId: string) => ({ ruleId }),
        setAllowCustomServers: (allowed: boolean) => ({ allowed }),
        setAllowCustomServersComplete: true,
        setAllowMemberAgentAccess: (allowed: boolean) => ({ allowed }),
        setAllowMemberAgentAccessComplete: true,
        applyPreset: (audience: AudienceEnumApi, preset: MCPPolicyPresetEnumApi) => ({ audience, preset }),
        applyPresetComplete: (audience: AudienceEnumApi) => ({ audience }),
        applyPresetStarted: (audience: AudienceEnumApi, preset: MCPPolicyPresetEnumApi) => ({ audience, preset }),
        setMemberServerAccess: (userId: number, serverId: string, enabled: boolean) => ({
            userId,
            serverId,
            enabled,
        }),
        setMemberServerAccessComplete: (userId: number, serverId: string) => ({ userId, serverId }),
        setMemberCount: (memberCount: number) => ({ memberCount }),
        setMembersOffset: (membersOffset: number) => ({ membersOffset: Math.max(0, membersOffset) }),
        setAgentServerAccess: (
            accountId: string,
            serverId: string,
            enabled: boolean,
            scope: MCPAgentGrantScopeEnumApi = 'team',
            policies?: ToolPolicyEntryApi[]
        ) => ({
            accountId,
            serverId,
            enabled,
            scope,
            policies,
        }),
        setAgentServerAccessSuccess: (accountId: string, serverId: string) => ({ accountId, serverId }),
        setAgentServerAccessComplete: (accountId: string, serverId: string) => ({ accountId, serverId }),
        removeAllAgentServerShares: (accountId: string, serverId: string) => ({ accountId, serverId }),
        setAllServersEnabled: (enabled: boolean) => ({ enabled }),
        setAllServersEnabledComplete: true,
        setTemplateEnabled: (templateId: string, enabled: boolean) => ({ templateId, enabled }),
        setTemplateEnabledComplete: (templateId: string) => ({ templateId }),
    }),

    loaders(({ actions, values }) => ({
        config: [
            null as TeamMCPGatewayConfigApi | null,
            {
                loadConfig: async () => await mcpGatewayConfigList(currentProjectId()),
            },
        ],
        servers: [
            [] as MCPGatewayServerApi[],
            {
                loadServers: async () => fetchGatewayServers(),
            },
        ],
        templates: [
            [] as MCPServerTemplateApi[],
            {
                loadTemplates: async () => {
                    const response = await mcpServersList(currentProjectId(), { limit: 500 })
                    return response.results
                },
            },
        ],
        serviceAccounts: [
            [] as MCPServiceAccountApi[],
            {
                loadServiceAccounts: async () => {
                    const response = await mcpGatewayServiceAccountsList(currentProjectId(), { limit: 500 })
                    return response.results
                },
            },
        ],
        rules: [
            [] as MCPOrgRuleApi[],
            {
                loadRules: async () => {
                    const response = await mcpGatewayRulesList(currentProjectId(), { limit: 500 })
                    return response.results
                },
            },
        ],
        members: [
            [] as GatewayMemberSummaryApi[],
            {
                loadMembers: async (_: void, breakpoint) => {
                    const response = await mcpGatewayMembersList(currentProjectId(), {
                        limit: GATEWAY_MEMBERS_PAGE_SIZE,
                        offset: values.membersOffset,
                    })
                    breakpoint()
                    actions.setMemberCount(response.count)
                    return response.results
                },
            },
        ],
    })),

    reducers({
        addServerModalOpen: [
            false,
            {
                openAddServerModal: () => true,
                closeAddServerModal: () => false,
            },
        ],
        addServerForm: [
            GATEWAY_ADD_SERVER_DEFAULTS,
            {
                openAddServerModal: () => GATEWAY_ADD_SERVER_DEFAULTS,
                closeAddServerModal: () => GATEWAY_ADD_SERVER_DEFAULTS,
                setAddServerFormValue: (state, { field, value }) => ({ ...state, [field]: value }),
            },
        ],
        addingServer: [
            false,
            {
                submitAddServerStarted: () => true,
                submitAddServerComplete: () => false,
            },
        ],
        refreshingInstallationIds: [
            new Set<string>(),
            {
                refreshServerTools: (state, { installationId }) => new Set(state).add(installationId),
                refreshServerToolsComplete: (state, { installationId }) => {
                    const next = new Set(state)
                    next.delete(installationId)
                    return next
                },
            },
        ],
        searchQuery: ['', { setSearchQuery: (_, { query }) => query }],
        categoryFilter: [null as string | null, { setCategoryFilter: (_, { category }) => category }],
        memberCount: [0, { setMemberCount: (_, { memberCount }) => memberCount }],
        membersOffset: [0, { setMembersOffset: (_, { membersOffset }) => membersOffset }],
        connectingServerId: [
            null as string | null,
            {
                performConnection: (_, { serverId }) => serverId,
                performConnectionComplete: () => null,
            },
        ],
        disconnectingInstallationIds: [
            new Set<string>(),
            {
                disconnectServer: (state, { installationId }) => new Set(state).add(installationId),
                disconnectServerComplete: (state, { installationId }) => {
                    const next = new Set(state)
                    next.delete(installationId)
                    return next
                },
            },
        ],
        updatingInstallationIds: [
            new Set<string>(),
            {
                toggleYourConnectionEnabled: (state, { installationId }) => new Set(state).add(installationId),
                toggleYourConnectionEnabledComplete: (state, { installationId }) => {
                    const next = new Set(state)
                    next.delete(installationId)
                    return next
                },
            },
        ],
        removingServerIds: [
            new Set<string>(),
            {
                removeServer: (state, { serverId }) => new Set(state).add(serverId),
                removeServerComplete: (state, { serverId }) => {
                    const next = new Set(state)
                    next.delete(serverId)
                    return next
                },
            },
        ],
        connectionModalServerId: [
            null as string | null,
            {
                openConnectionModal: (_, { serverId }) => serverId,
                closeConnectionModal: () => null,
            },
        ],
        connectionAuthType: [
            'oauth' as InstallCustomAuthTypeEnumApi,
            {
                openConnectionModal: (_, { authType }) => authType,
                setConnectionAuthType: (_, { authType }) => authType,
                closeConnectionModal: () => 'oauth',
            },
        ],
        connectionApiKey: [
            '',
            {
                setConnectionApiKey: (_, { apiKey }) => apiKey,
                setConnectionAuthType: () => '',
                openConnectionModal: () => '',
                closeConnectionModal: () => '',
            },
        ],
        connectionClientId: [
            '',
            {
                setConnectionClientId: (_, { clientId }) => clientId,
                setConnectionAuthType: () => '',
                openConnectionModal: () => '',
                closeConnectionModal: () => '',
            },
        ],
        connectionClientSecret: [
            '',
            {
                setConnectionClientSecret: (_, { clientSecret }) => clientSecret,
                setConnectionAuthType: () => '',
                openConnectionModal: () => '',
                closeConnectionModal: () => '',
            },
        ],
        serversInitialized: [
            false,
            {
                loadServersSuccess: () => true,
                loadServersFailure: () => true,
            },
        ],
        serversLoadFailed: [
            false,
            {
                loadServers: () => false,
                loadServersSuccess: () => false,
                loadServersFailure: () => true,
            },
        ],
        membersInitialized: [
            false,
            {
                loadMembersSuccess: () => true,
                loadMembersFailure: () => true,
            },
        ],
        serviceAccountsInitialized: [
            false,
            {
                loadServiceAccountsSuccess: () => true,
                loadServiceAccountsFailure: () => true,
            },
        ],
        accountStatusLoadingIds: [
            new Set<string>(),
            {
                toggleAccountStatus: (state, { accountId }) => new Set(state).add(accountId),
                toggleAccountStatusComplete: (state, { accountId }) => {
                    const next = new Set(state)
                    next.delete(accountId)
                    return next
                },
            },
        ],
        agentServerAccessLoadingKeys: [
            new Set<string>(),
            {
                setAgentServerAccess: (state, { accountId, serverId }) =>
                    new Set(state).add(agentServerAccessKey(accountId, serverId)),
                removeAllAgentServerShares: (state, { accountId, serverId }) =>
                    new Set(state).add(agentServerAccessKey(accountId, serverId)),
                setAgentServerAccessComplete: (state, { accountId, serverId }) => {
                    const next = new Set(state)
                    next.delete(agentServerAccessKey(accountId, serverId))
                    return next
                },
            },
        ],
        serverEnabledLoadingIds: [
            new Set<string>(),
            {
                toggleServerEnabled: (state, { serverId }) => new Set(state).add(serverId),
                toggleServerEnabledComplete: (state, { serverId }) => {
                    const next = new Set(state)
                    next.delete(serverId)
                    return next
                },
            },
        ],
        templateEnabledLoadingIds: [
            new Set<string>(),
            {
                setTemplateEnabled: (state, { templateId }) => new Set(state).add(templateId),
                setTemplateEnabledComplete: (state, { templateId }) => {
                    const next = new Set(state)
                    next.delete(templateId)
                    return next
                },
            },
        ],
        memberServerAccessLoadingKeys: [
            new Set<string>(),
            {
                setMemberServerAccess: (state, { userId, serverId }) =>
                    new Set(state).add(memberServerAccessKey(userId, serverId)),
                setMemberServerAccessComplete: (state, { userId, serverId }) => {
                    const next = new Set(state)
                    next.delete(memberServerAccessKey(userId, serverId))
                    return next
                },
            },
        ],
        ruleEnabledLoadingIds: [
            new Set<string>(),
            {
                toggleRuleEnabled: (state, { ruleId }) => new Set(state).add(ruleId),
                toggleRuleEnabledComplete: (state, { ruleId }) => {
                    const next = new Set(state)
                    next.delete(ruleId)
                    return next
                },
            },
        ],
        applyingPresetByAudience: [
            {} as Partial<Record<AudienceEnumApi, MCPPolicyPresetEnumApi>>,
            {
                applyPresetStarted: (state, { audience, preset }) => ({ ...state, [audience]: preset }),
                applyPresetComplete: (state, { audience }) => {
                    const next = { ...state }
                    delete next[audience]
                    return next
                },
            },
        ],
        allowCustomServersLoading: [
            false,
            {
                setAllowCustomServers: () => true,
                setAllowCustomServersComplete: () => false,
            },
        ],
        allowMemberAgentAccessLoading: [
            false,
            {
                setAllowMemberAgentAccess: () => true,
                setAllowMemberAgentAccessComplete: () => false,
            },
        ],
        allServersEnabledLoading: [
            false,
            {
                setAllServersEnabled: () => true,
                setAllServersEnabledComplete: () => false,
            },
        ],
        allServersEnabledTarget: [
            null as boolean | null,
            {
                setAllServersEnabled: (_, { enabled }) => enabled,
                setAllServersEnabledComplete: () => null,
            },
        ],
    }),

    selectors({
        currentUserId: [(s) => [s.user], (user: UserType | null): number | null => user?.id ?? null],
        addServerSubmitDisabledReason: [
            (s) => [s.addServerForm, s.addingServer],
            (addServerForm: GatewayAddServerValues, addingServer: boolean): string | null => {
                if (addingServer) {
                    return 'Adding server'
                }
                if (!addServerForm.name.trim()) {
                    return 'Enter a server name'
                }
                if (!canSubmitGatewayServer(addServerForm)) {
                    return 'Enter a full HTTP or HTTPS URL'
                }
                return null
            },
        ],
        isAdmin: [(s) => [s.config], (config: TeamMCPGatewayConfigApi | null): boolean => Boolean(config?.is_admin)],
        allowCustomServers: [
            (s) => [s.config],
            (config: TeamMCPGatewayConfigApi | null): boolean => config?.allow_custom_servers ?? false,
        ],
        allowMemberAgentAccess: [
            (s) => [s.config],
            (config: TeamMCPGatewayConfigApi | null): boolean => config?.allow_member_agent_access ?? false,
        ],
        canAddServers: [
            (s) => [s.isAdmin, s.allowCustomServers],
            (isAdmin: boolean, allowCustomServers: boolean): boolean => isAdmin || allowCustomServers,
        ],
        canManageAgentAccess: [
            (s) => [s.isAdmin, s.allowMemberAgentAccess],
            (isAdmin: boolean, allowMemberAgentAccess: boolean): boolean => isAdmin || allowMemberAgentAccess,
        ],
        defaultServersEnabled: [
            (s) => [s.config],
            (config: TeamMCPGatewayConfigApi | null): boolean => config?.default_servers_enabled ?? false,
        ],
        configMutationInProgress: [
            (s) => [
                s.allowCustomServersLoading,
                s.allowMemberAgentAccessLoading,
                s.allServersEnabledLoading,
                s.applyingPresetByAudience,
            ],
            (
                allowCustomServersLoading: boolean,
                allowMemberAgentAccessLoading: boolean,
                allServersEnabledLoading: boolean,
                applyingPresetByAudience: Partial<Record<AudienceEnumApi, MCPPolicyPresetEnumApi>>
            ): boolean =>
                allowCustomServersLoading ||
                allowMemberAgentAccessLoading ||
                allServersEnabledLoading ||
                Object.keys(applyingPresetByAudience).length > 0,
        ],
        recommendedTemplates: [
            (s) => [s.templates, s.servers, s.config],
            (
                templates: MCPServerTemplateApi[],
                servers: MCPGatewayServerApi[],
                config: TeamMCPGatewayConfigApi | null
            ): MCPServerTemplateApi[] => {
                const registeredTemplateIds = new Set([
                    ...(config?.registered_template_ids ?? []),
                    ...servers
                        .map((server) => server.template_id)
                        .filter((templateId): templateId is string => !!templateId),
                ])
                const registeredUrls = new Set(servers.map((server) => normalizeServerUrl(server.url)))
                return templates.filter(
                    (template) =>
                        !registeredTemplateIds.has(template.id) && !registeredUrls.has(normalizeServerUrl(template.url))
                )
            },
        ],
        templateOnlyServers: [
            (s) => [s.recommendedTemplates, s.defaultServersEnabled, s.isAdmin],
            (
                recommendedTemplates: MCPServerTemplateApi[],
                defaultServersEnabled: boolean,
                isAdmin: boolean
            ): GatewayServerEntry[] =>
                // Members only see catalog servers while the team default keeps them enabled.
                !isAdmin && !defaultServersEnabled
                    ? []
                    : recommendedTemplates.map((template) => templateAsGatewayServer(template, defaultServersEnabled)),
        ],
        mergedServers: [
            (s) => [s.servers, s.templateOnlyServers],
            (servers: MCPGatewayServerApi[], templateOnlyServers: GatewayServerEntry[]): GatewayServerEntry[] => [
                ...servers,
                ...templateOnlyServers,
            ],
        ],
        connectionModalServer: [
            (s) => [s.mergedServers, s.connectionModalServerId],
            (mergedServers: GatewayServerEntry[], serverId: string | null): GatewayServerEntry | null =>
                mergedServers.find((server) => server.id === serverId) ?? null,
        ],
        connectionSubmitDisabledReason: [
            (s) => [s.connectionModalServer, s.connectionAuthType, s.connectionApiKey],
            (
                server: GatewayServerEntry | null,
                authType: InstallCustomAuthTypeEnumApi,
                apiKey: string
            ): string | null =>
                server?.template_id && authType === 'api_key' && !apiKey.trim()
                    ? 'Enter an API key to connect this server.'
                    : null,
        ],
        categoryCounts: [
            (s) => [s.mergedServers],
            (mergedServers: GatewayServerEntry[]): Record<string, number> => {
                const counts: Record<string, number> = {}
                for (const server of mergedServers) {
                    counts[server.category ?? 'dev'] = (counts[server.category ?? 'dev'] || 0) + 1
                }
                return counts
            },
        ],
        connectedServers: [
            (s) => [s.mergedServers],
            (mergedServers: GatewayServerEntry[]): GatewayServerEntry[] =>
                mergedServers
                    .filter((server) => server.your_connection !== null)
                    .sort((a, b) => a.name.localeCompare(b.name)),
        ],
        filteredServers: [
            (s) => [s.mergedServers, s.searchQuery, s.categoryFilter],
            (
                mergedServers: GatewayServerEntry[],
                searchQuery: string,
                categoryFilter: string | null
            ): GatewayServerEntry[] => {
                const query = searchQuery.trim().toLowerCase()
                return mergedServers.filter((server) => {
                    if (categoryFilter && server.category !== categoryFilter) {
                        return false
                    }
                    if (!query) {
                        return true
                    }
                    return (
                        server.name.toLowerCase().includes(query) ||
                        (server.description || '').toLowerCase().includes(query) ||
                        server.url.toLowerCase().includes(query)
                    )
                })
            },
        ],
        activeAgentCount: [
            (s) => [s.serviceAccounts],
            (serviceAccounts: MCPServiceAccountApi[]): number =>
                serviceAccounts.filter((account) => account.status === 'active').length,
        ],
        agentSharedServerCounts: [
            (s) => [s.serviceAccounts],
            // `server_ids` carries one entry per member grant, so the same server repeats
            // once per member who shared it.
            (serviceAccounts: MCPServiceAccountApi[]): Record<string, number> =>
                Object.fromEntries(serviceAccounts.map((account) => [account.id, new Set(account.server_ids).size])),
        ],
        enabledServerCount: [
            (s) => [s.mergedServers],
            (mergedServers: GatewayServerEntry[]): number =>
                mergedServers.filter((server) => server.is_team_enabled).length,
        ],
    }),

    listeners(({ actions, cache, values }) => ({
        setAddServerFormValue: ({ field, value }) => {
            if (field !== 'authType') {
                return
            }
            if (value !== 'api_key' && values.addServerForm.apiKey) {
                actions.setAddServerFormValue('apiKey', '')
            }
            if (value !== 'oauth') {
                if (values.addServerForm.clientId) {
                    actions.setAddServerFormValue('clientId', '')
                }
                if (values.addServerForm.clientSecret) {
                    actions.setAddServerFormValue('clientSecret', '')
                }
            }
        },
        submitAddServer: async () => {
            if (values.addingServer || !canSubmitGatewayServer(values.addServerForm)) {
                return
            }
            actions.submitAddServerStarted()
            try {
                const result = await mcpServerInstallationsInstallCustomCreate(currentProjectId(), {
                    ...buildGatewayInstallRequest(values.addServerForm, {
                        isAdmin: values.isAdmin,
                        canManageAgentAccess: values.canManageAgentAccess,
                    }),
                    scope: 'personal',
                    return_path: currentReturnPath(),
                })
                if ('redirect_url' in result) {
                    window.location.href = result.redirect_url
                    return
                }
                lemonToast.success(`${values.addServerForm.name.trim()} added`)
                actions.closeAddServerModal()
                actions.refreshServersAfterConnection()
                actions.loadServiceAccounts()
            } catch (error: unknown) {
                lemonToast.error(errorDetail(error) ?? 'Could not add this server')
            } finally {
                actions.submitAddServerComplete()
            }
        },
        refreshServerTools: async ({ installationId }) => {
            try {
                await mcpServerInstallationsToolsRefreshCreate(currentProjectId(), installationId)
                actions.refreshServerToolsSuccess(installationId)
                actions.loadServers()
                lemonToast.success('Tools refreshed')
            } catch (error: unknown) {
                lemonToast.error(errorDetail(error) ?? 'Could not refresh tools')
            } finally {
                actions.refreshServerToolsComplete(installationId)
            }
        },
        refreshServersAfterConnection: () => {
            actions.loadServers()
            cache.disposables.add(() => {
                const timeoutIds = GATEWAY_CONNECTION_REFRESH_DELAYS_MS.map((delayMs) =>
                    window.setTimeout(() => actions.loadServers(), delayMs)
                )
                return () => timeoutIds.forEach((timeoutId) => window.clearTimeout(timeoutId))
            }, 'gatewayPostConnectionRefresh')
        },
        toggleServerEnabled: async ({ serverId, enabled }) => {
            const server = values.servers.find((candidate) => candidate.id === serverId)
            try {
                await mcpGatewayServersPartialUpdate(currentProjectId(), serverId, { is_team_enabled: enabled })
                actions.loadServersSuccess(
                    values.servers.map((candidate) =>
                        candidate.id === serverId ? { ...candidate, is_team_enabled: enabled } : candidate
                    )
                )
                actions.loadServers()
                lemonToast[enabled ? 'success' : 'info'](
                    `${server?.name ?? 'Server'} ${enabled ? 'enabled for the team' : 'disabled'}`
                )
            } catch (error: unknown) {
                lemonToast.error(
                    errorDetail(error) ?? `Could not ${enabled ? 'enable' : 'disable'} ${server?.name ?? 'this server'}`
                )
            } finally {
                actions.toggleServerEnabledComplete(serverId)
            }
        },
        setAllServersEnabled: async ({ enabled }) => {
            try {
                const config = await mcpGatewayConfigSetAllServersEnabledCreate(currentProjectId(), { enabled })
                actions.loadConfigSuccess(config)
                actions.loadServersSuccess(await fetchGatewayServers())
                lemonToast[enabled ? 'success' : 'info'](
                    enabled
                        ? 'Every server is enabled for the team'
                        : 'All servers disabled, including catalog servers added later. Enable them one by one.'
                )
            } catch (error: unknown) {
                lemonToast.error(errorDetail(error) ?? 'Could not update all servers')
            } finally {
                actions.setAllServersEnabledComplete()
            }
        },
        setTemplateEnabled: async ({ templateId, enabled }) => {
            const template = values.templates.find((candidate) => candidate.id === templateId)
            try {
                const server = await mcpGatewayServersSetTemplateEnabledCreate(currentProjectId(), {
                    template_id: templateId,
                    enabled,
                })
                const exists = values.servers.some((candidate) => candidate.id === server.id)
                actions.loadServersSuccess(
                    exists
                        ? values.servers.map((candidate) => (candidate.id === server.id ? server : candidate))
                        : [...values.servers, server]
                )
                lemonToast[enabled ? 'success' : 'info'](
                    `${server.name} ${enabled ? 'enabled for the team' : 'disabled'}`
                )
            } catch (error: unknown) {
                lemonToast.error(
                    errorDetail(error) ??
                        `Could not ${enabled ? 'enable' : 'disable'} ${template?.name ?? 'this server'}`
                )
            } finally {
                actions.setTemplateEnabledComplete(templateId)
            }
        },
        removeServer: async ({ serverId }) => {
            const server = values.servers.find((candidate) => candidate.id === serverId)
            try {
                await mcpGatewayServersDestroy(currentProjectId(), serverId)
                actions.removeServerSuccess(serverId)
                actions.loadServers()
                lemonToast.info(
                    server?.template_id
                        ? `${server.name} removed. Everyone is disconnected and the server follows the team default again.`
                        : `${server?.name ?? 'Server'} removed from the gateway. Everyone is disconnected.`
                )
            } catch (error: unknown) {
                lemonToast.error(errorDetail(error) ?? `Could not remove ${server?.name ?? 'this server'}`)
            } finally {
                actions.removeServerComplete(serverId)
            }
        },
        connectServer: ({ serverId }) => {
            if (values.connectingServerId) {
                return
            }

            const server = values.mergedServers.find((candidate) => candidate.id === serverId)
            if (!server) {
                return
            }

            if (server.template_id && server.template_auth_type === 'oauth') {
                actions.performConnection(serverId, 'oauth', '', '', '')
                return
            }

            actions.openConnectionModal(serverId, server.template_auth_type ?? 'oauth')
        },
        reconnectServer: ({ installationId }) => {
            window.location.href = getMcpServerInstallationsAuthorizeRetrieveUrl(currentProjectId(), {
                installation_id: installationId,
                return_path: currentReturnPath(),
            })
        },
        submitConnection: () => {
            if (!values.connectionModalServerId || values.connectingServerId || values.connectionSubmitDisabledReason) {
                return
            }
            actions.performConnection(
                values.connectionModalServerId,
                values.connectionAuthType,
                values.connectionApiKey,
                values.connectionClientId,
                values.connectionClientSecret
            )
        },
        performConnection: async ({ serverId, authType, apiKey, clientId, clientSecret }) => {
            const server = values.mergedServers.find((candidate) => candidate.id === serverId)
            if (!server) {
                actions.performConnectionComplete()
                return
            }

            const returnPath = currentReturnPath()
            const projectId = currentProjectId()
            try {
                const response = server.template_id
                    ? await mcpServerInstallationsInstallTemplateCreate(projectId, {
                          template_id: server.template_id,
                          api_key: authType === 'api_key' ? apiKey || undefined : undefined,
                          scope: 'personal',
                          return_path: returnPath,
                      })
                    : await mcpServerInstallationsInstallCustomCreate(projectId, {
                          name: server.name,
                          url: server.url,
                          auth_type: authType,
                          api_key: authType === 'api_key' ? apiKey || undefined : undefined,
                          description: server.description || '',
                          client_id: authType === 'oauth' ? clientId || undefined : undefined,
                          client_secret: authType === 'oauth' ? clientSecret || undefined : undefined,
                          scope: 'personal',
                          return_path: returnPath,
                      })
                if ('redirect_url' in response) {
                    window.location.href = response.redirect_url
                    return
                }
                actions.closeConnectionModal()
                actions.refreshServersAfterConnection()
                actions.loadServiceAccounts()
                lemonToast.success(`Connected to ${server.name}`)
            } catch (error: unknown) {
                actions.loadServers()
                lemonToast.error(errorDetail(error) ?? `Could not connect to ${server.name}`)
            } finally {
                actions.performConnectionComplete()
            }
        },
        disconnectServer: async ({ serverId, installationId, navigateToServers }) => {
            const server = values.servers.find((candidate) => candidate.id === serverId)
            try {
                await mcpServerInstallationsDestroy(currentProjectId(), installationId)
                actions.disconnectServerSuccess(serverId, navigateToServers)
                actions.loadServers()
                lemonToast.info(`Disconnected from ${server?.name ?? 'server'}`)
            } catch (error: unknown) {
                lemonToast.error(errorDetail(error) ?? `Could not disconnect from ${server?.name ?? 'this server'}`)
            } finally {
                actions.disconnectServerComplete(installationId)
            }
        },
        toggleYourConnectionEnabled: async ({ installationId, enabled }) => {
            try {
                await mcpServerInstallationsPartialUpdate(currentProjectId(), installationId, { is_enabled: enabled })
                actions.loadServers()
            } catch (error: unknown) {
                lemonToast.error(errorDetail(error) ?? 'Could not update this connection')
            } finally {
                actions.toggleYourConnectionEnabledComplete(installationId)
            }
        },
        toggleAccountStatus: async ({ accountId, paused }) => {
            const account = values.serviceAccounts.find((candidate) => candidate.id === accountId)
            try {
                await mcpGatewayServiceAccountsPartialUpdate(currentProjectId(), accountId, {
                    status: paused ? 'paused' : 'active',
                })
                const status: MCPServiceAccountApi['status'] = paused ? 'paused' : 'active'
                actions.loadServiceAccountsSuccess(
                    values.serviceAccounts.map((candidate) =>
                        candidate.id === accountId ? { ...candidate, status } : candidate
                    )
                )
                lemonToast[paused ? 'info' : 'success'](
                    paused
                        ? `${account?.name ?? 'Agent'} paused. All MCP access is off.`
                        : `${account?.name ?? 'Agent'} is active again`
                )
            } catch (error: unknown) {
                lemonToast.error(
                    errorDetail(error) ?? `Could not ${paused ? 'pause' : 'resume'} ${account?.name ?? 'this agent'}`
                )
            } finally {
                actions.toggleAccountStatusComplete(accountId)
            }
        },
        setAgentServerAccess: async ({ accountId, serverId, enabled, scope, policies }) => {
            const account = values.serviceAccounts.find((candidate) => candidate.id === accountId)
            const server = values.servers.find((candidate) => candidate.id === serverId)
            const accountName = account?.name ?? 'agent'
            try {
                // The response carries the account's grants after the change, including who
                // backs each one, which a local merge cannot reconstruct. `scope` goes on
                // every call because the endpoint defaults an omitted scope back to
                // personal, which would silently demote a team share on any re-share.
                const updatedAccount = await mcpGatewayServiceAccountsAccessCreate(currentProjectId(), accountId, {
                    gateway_server_id: serverId,
                    enabled,
                    scope,
                    policies,
                })
                actions.loadServiceAccountsSuccess(
                    values.serviceAccounts.map((candidate) => (candidate.id === accountId ? updatedAccount : candidate))
                )
                // The access section renders one server.agents row per member grant, so
                // patch the caller's own row immediately. The background reload fills in
                // granted_by for newly shared agents.
                const yourGrant = updatedAccount.servers.find(
                    (grant) => grant.id === serverId && grant.shared_by.id === values.currentUserId
                )
                actions.loadServersSuccess(
                    values.servers.map((candidate) => {
                        if (candidate.id !== serverId) {
                            return candidate
                        }
                        const yourRowListed = candidate.agents.some(
                            (agent) => agent.service_account_id === accountId && agent.user.id === values.currentUserId
                        )
                        if (enabled) {
                            return !yourGrant || yourRowListed
                                ? candidate
                                : {
                                      ...candidate,
                                      agents: [
                                          ...candidate.agents,
                                          {
                                              service_account_id: updatedAccount.id,
                                              user: yourGrant.shared_by,
                                              scope: yourGrant.scope,
                                              name: updatedAccount.name,
                                              handle: updatedAccount.handle,
                                              status: updatedAccount.status,
                                              last_active_at: updatedAccount.last_active_at,
                                              granted_by: null,
                                          },
                                      ],
                                  }
                        }
                        // Shares are personal, so withdrawing yours removes only your own
                        // row and leaves teammates' grants listed.
                        return {
                            ...candidate,
                            agents: candidate.agents.filter(
                                (agent) =>
                                    !(agent.service_account_id === accountId && agent.user.id === values.currentUserId)
                            ),
                        }
                    })
                )
                actions.loadServers()
                actions.setAgentServerAccessSuccess(accountId, serverId)
                lemonToast[enabled ? 'success' : 'info'](
                    enabled
                        ? scope === 'team'
                            ? `${server?.name ?? 'Server'} shared with ${accountName}. Every ${accountName} run in this project can use your connection.`
                            : `${server?.name ?? 'Server'} shared with ${accountName}. Only your own ${accountName} runs use your connection.`
                        : `Your ${server?.name ?? 'server'} connection is no longer shared with ${account?.name ?? 'this agent'}. Your teammates' shares are unchanged.`
                )
            } catch (error: unknown) {
                lemonToast.error(
                    errorDetail(error) ?? `Could not update server access for ${account?.name ?? 'this agent'}`
                )
            } finally {
                actions.setAgentServerAccessComplete(accountId, serverId)
            }
        },
        removeAllAgentServerShares: async ({ accountId, serverId }) => {
            const account = values.serviceAccounts.find((candidate) => candidate.id === accountId)
            const server = values.servers.find((candidate) => candidate.id === serverId)
            try {
                const updatedAccount = await mcpGatewayServiceAccountsAccessCreate(currentProjectId(), accountId, {
                    gateway_server_id: serverId,
                    enabled: false,
                    all: true,
                })
                actions.loadServiceAccountsSuccess(
                    values.serviceAccounts.map((candidate) => (candidate.id === accountId ? updatedAccount : candidate))
                )
                actions.loadServers()
                lemonToast.info(
                    `${account?.name ?? 'This agent'} can no longer use anyone's ${server?.name ?? 'server'} connection`
                )
            } catch (error: unknown) {
                lemonToast.error(
                    errorDetail(error) ?? `Could not remove the shares of ${server?.name ?? 'this server'}`
                )
            } finally {
                actions.setAgentServerAccessComplete(accountId, serverId)
            }
        },
        toggleRuleEnabled: async ({ ruleId, enabled }) => {
            const rule = values.rules.find((candidate) => candidate.id === ruleId)
            try {
                const updatedRule = await mcpGatewayRulesPartialUpdate(currentProjectId(), ruleId, { enabled })
                actions.loadRulesSuccess(
                    values.rules.map((candidate) => (candidate.id === ruleId ? updatedRule : candidate))
                )
                lemonToast[enabled ? 'success' : 'info'](`${rule?.name ?? 'Rule'} ${enabled ? 'enabled' : 'disabled'}`)
            } catch (error: unknown) {
                lemonToast.error(errorDetail(error) ?? `Could not update ${rule?.name ?? 'this rule'}`)
            } finally {
                actions.toggleRuleEnabledComplete(ruleId)
            }
        },
        setAllowCustomServers: async ({ allowed }) => {
            try {
                const config = await mcpGatewayConfigUpdateSettingsCreate(currentProjectId(), {
                    allow_custom_servers: allowed,
                })
                actions.loadConfigSuccess(config)
                lemonToast[allowed ? 'success' : 'info'](
                    allowed ? 'Members can add custom servers' : 'Custom servers are now admin-only'
                )
            } catch (error: unknown) {
                lemonToast.error(errorDetail(error) ?? 'Could not update custom server access')
            } finally {
                actions.setAllowCustomServersComplete()
            }
        },
        setAllowMemberAgentAccess: async ({ allowed }) => {
            try {
                const config = await mcpGatewayConfigUpdateSettingsCreate(currentProjectId(), {
                    allow_member_agent_access: allowed,
                })
                actions.loadConfigSuccess(config)
                lemonToast[allowed ? 'success' : 'info'](
                    allowed ? 'Members can now manage agent access' : 'Only admins can manage agent access now'
                )
            } catch (error: unknown) {
                lemonToast.error(errorDetail(error) ?? 'Could not update member-managed agent access')
            } finally {
                actions.setAllowMemberAgentAccessComplete()
            }
        },
        applyPreset: async ({ audience, preset }) => {
            if (Object.keys(values.applyingPresetByAudience).length > 0) {
                return
            }
            actions.applyPresetStarted(audience, preset)
            try {
                const config = await mcpGatewayConfigApplyPresetCreate(currentProjectId(), { audience, preset })
                actions.loadConfigSuccess(config)
                lemonToast.success(`Baseline applied to ${audience}`)
            } catch (error: unknown) {
                lemonToast.error(errorDetail(error) ?? `Could not apply the baseline to ${audience}`)
            } finally {
                actions.applyPresetComplete(audience)
            }
        },
        setMemberServerAccess: async ({ userId, serverId, enabled }) => {
            const server = values.servers.find((candidate) => candidate.id === serverId)
            try {
                await mcpGatewayMembersSetAccessCreate(currentProjectId(), String(userId), {
                    gateway_server_id: serverId,
                    enabled,
                })
                actions.loadMembersSuccess(
                    values.members.map((member) => {
                        if (member.user.id !== userId) {
                            return member
                        }
                        const revokedServerIds = enabled
                            ? member.revoked_server_ids.filter((revokedServerId) => revokedServerId !== serverId)
                            : Array.from(new Set([...member.revoked_server_ids, serverId]))
                        return { ...member, revoked_server_ids: revokedServerIds }
                    })
                )
                actions.loadServersSuccess(await fetchGatewayServers())
                lemonToast[enabled ? 'success' : 'info'](
                    `${enabled ? 'Restored' : 'Turned off'} access to ${server?.name ?? 'server'}`
                )
            } catch (error: unknown) {
                lemonToast.error(errorDetail(error) ?? `Could not update access to ${server?.name ?? 'this server'}`)
            } finally {
                actions.setMemberServerAccessComplete(userId, serverId)
            }
        },
        setMembersOffset: () => {
            actions.loadMembers()
        },
        loadConfigSuccess: () => {
            if (values.isAdmin) {
                actions.loadMembers()
            }
        },
    })),

    afterMount(({ actions }) => {
        actions.loadConfig()
        actions.loadServers()
        actions.loadTemplates()
        actions.loadServiceAccounts()
        actions.loadRules()
    }),
])
