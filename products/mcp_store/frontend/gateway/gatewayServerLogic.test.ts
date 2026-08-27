import { MOCK_DEFAULT_BASIC_USER, MOCK_DEFAULT_USER } from '~/lib/api.mock'

import { router } from 'kea-router'

import { lemonToast } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { initKeaTests } from '~/test/init'
import { expectLogic } from '~/test/keaTestUtils'

import {
    mcpGatewayConfigList,
    mcpGatewayMembersList,
    mcpGatewayMembersRetrieve,
    mcpGatewayRulesList,
    mcpGatewayServersPoliciesCreate,
    mcpGatewayServersList,
    mcpGatewayServersToolsRetrieve,
    mcpGatewayServiceAccountsAccessCreate,
    mcpGatewayServiceAccountsList,
    mcpServersList,
} from '../generated/api'
import type {
    GatewayMemberSummaryApi,
    MCPAgentGrantScopeEnumApi,
    MCPGatewayServerApi,
    MCPServiceAccountApi,
    ResolvedToolPolicyApi,
    UserBasicApi,
} from '../generated/api.schemas'
import { gatewayServerLogic } from './gatewayServerLogic'
import { mcpGatewayLogic } from './mcpGatewayLogic'

jest.mock('../generated/api', () => ({
    ...jest.requireActual('../generated/api'),
    mcpGatewayConfigList: jest.fn(),
    mcpGatewayMembersList: jest.fn(),
    mcpGatewayMembersRetrieve: jest.fn(),
    mcpGatewayRulesList: jest.fn(),
    mcpGatewayServersPoliciesCreate: jest.fn(),
    mcpGatewayServersList: jest.fn(),
    mcpGatewayServersToolsRetrieve: jest.fn(),
    mcpGatewayServiceAccountsAccessCreate: jest.fn(),
    mcpGatewayServiceAccountsList: jest.fn(),
    mcpServersList: jest.fn(),
}))

const mockConfigList = jest.mocked(mcpGatewayConfigList)
const mockMembersList = jest.mocked(mcpGatewayMembersList)
const mockMemberRetrieve = jest.mocked(mcpGatewayMembersRetrieve)
const mockPoliciesCreate = jest.mocked(mcpGatewayServersPoliciesCreate)
const mockRulesList = jest.mocked(mcpGatewayRulesList)
const mockServersList = jest.mocked(mcpGatewayServersList)
const mockToolsRetrieve = jest.mocked(mcpGatewayServersToolsRetrieve)
const mockServiceAccountAccess = jest.mocked(mcpGatewayServiceAccountsAccessCreate)
const mockServiceAccountsList = jest.mocked(mcpGatewayServiceAccountsList)
const mockTemplatesList = jest.mocked(mcpServersList)

function gatewayConnection(
    overrides: Partial<NonNullable<MCPGatewayServerApi['your_connection']>> = {}
): NonNullable<MCPGatewayServerApi['your_connection']> {
    return {
        installation_id: 'installation-id',
        is_enabled: true,
        pending_oauth: false,
        needs_reauth: false,
        last_used_at: null,
        ...overrides,
    }
}

function gatewayServer(overrides: Partial<MCPGatewayServerApi> = {}): MCPGatewayServerApi {
    return {
        id: 'server-id',
        name: 'Test server',
        url: 'https://mcp.example.com/mcp',
        description: '',
        category: 'dev',
        template_auth_type: null,
        is_team_enabled: true,
        icon_key: '',
        icon_domain: '',
        docs_url: '',
        template_id: null,
        tool_count: 2,
        connections: [],
        your_connection: gatewayConnection(),
        agents: [],
        revoked_user_ids: [],
        is_revoked_for_you: false,
        created_by: {
            id: MOCK_DEFAULT_BASIC_USER.id,
            uuid: MOCK_DEFAULT_BASIC_USER.uuid,
            distinct_id: MOCK_DEFAULT_BASIC_USER.distinct_id,
            first_name: MOCK_DEFAULT_BASIC_USER.first_name,
            email: MOCK_DEFAULT_BASIC_USER.email,
            hedgehog_config: null,
        },
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
        ...overrides,
    }
}

const YOU: UserBasicApi = {
    id: MOCK_DEFAULT_USER.id,
    uuid: MOCK_DEFAULT_USER.uuid,
    email: MOCK_DEFAULT_USER.email,
    hedgehog_config: null,
}

const TEAMMATE: UserBasicApi = {
    id: MOCK_DEFAULT_USER.id + 1,
    uuid: 'teammate-uuid',
    first_name: 'Ada',
    last_name: 'Lovelace',
    email: 'ada@example.com',
    hedgehog_config: null,
}

type Grant = { user: UserBasicApi; scope: MCPAgentGrantScopeEnumApi }

function serviceAccount(id: string = 'scout-id', grants: Grant[] = []): MCPServiceAccountApi {
    return {
        id,
        name: `Agent ${id}`,
        description: '',
        handle: `svc-${id}`,
        agent_key: 'scout',
        status: 'active',
        server_ids: grants.map(() => 'server-id'),
        servers: grants.map(({ user, scope }) => ({
            id: 'server-id',
            shared_by: user,
            scope,
            name: 'Test server',
            description: '',
            icon_key: '',
            icon_domain: '',
            connection_state: 'ready' as const,
        })),
        last_active_at: null,
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
    }
}

function toolPolicy(toolName: string, overrides: Partial<ResolvedToolPolicyApi> = {}): ResolvedToolPolicyApi {
    return {
        tool_name: toolName,
        description: '',
        input_schema: {},
        is_destructive: false,
        policy_state: 'approved',
        team_state: null,
        locked: false,
        decided_by: 'default',
        rule_name: '',
        rule_description: '',
        ...overrides,
    }
}

function gatewayMember(userId: number): GatewayMemberSummaryApi {
    return {
        user: {
            id: userId,
            uuid: `user-${userId}`,
            first_name: 'Ada',
            last_name: 'Lovelace',
            email: 'ada@example.com',
            hedgehog_config: null,
        },
        is_org_admin: false,
        connected_server_ids: ['server-id'],
        revoked_server_ids: [],
    }
}

function deferred<T>(): { promise: Promise<T>; resolve: (value: T) => void } {
    let resolve!: (value: T) => void
    const promise = new Promise<T>((resolvePromise) => {
        resolve = resolvePromise
    })
    return { promise, resolve }
}

describe('gatewayServerLogic', () => {
    let parentLogic: ReturnType<typeof mcpGatewayLogic.build>
    let logic: ReturnType<typeof gatewayServerLogic.build>

    beforeEach(async () => {
        initKeaTests()
        jest.resetAllMocks()
        mockConfigList.mockResolvedValue({
            is_admin: true,
            registered_template_ids: [],
            allow_custom_servers: true,
            allow_member_agent_access: true,
        })
        mockMembersList.mockResolvedValue({ count: 0, results: [] })
        mockMemberRetrieve.mockResolvedValue(gatewayMember(42))
        mockRulesList.mockResolvedValue({ count: 0, results: [] })
        mockServersList.mockResolvedValue({ count: 1, results: [gatewayServer()] })
        mockServiceAccountsList.mockResolvedValue({ count: 0, results: [] })
        mockServiceAccountAccess.mockResolvedValue(serviceAccount())
        mockTemplatesList.mockResolvedValue({ count: 0, results: [] })
        mockToolsRetrieve.mockResolvedValue({ count: 0, results: [] })

        parentLogic = mcpGatewayLogic()
        parentLogic.mount()
        await expectLogic(parentLogic).toFinishAllListeners()

        logic = gatewayServerLogic({ id: 'server-id' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
    })

    afterEach(() => {
        logic.unmount()
        parentLogic.unmount()
        jest.restoreAllMocks()
    })

    it('attributes each agent grant to the member backing it, and separates team shares', () => {
        parentLogic.actions.loadServiceAccountsSuccess([
            serviceAccount('yours-team', [{ user: YOU, scope: 'team' }]),
            serviceAccount('teammate-personal', [{ user: TEAMMATE, scope: 'personal' }]),
            serviceAccount('teammate-team', [{ user: TEAMMATE, scope: 'team' }]),
            serviceAccount('both', [
                { user: YOU, scope: 'personal' },
                { user: TEAMMATE, scope: 'team' },
            ]),
            serviceAccount('unshared', []),
        ])

        expect(logic.values.agentSharesByAccountId).toEqual({
            'yours-team': { sharedByYou: true, yourScope: 'team', sharedByOthers: [], teamSharedByOthers: [] },
            'teammate-personal': {
                sharedByYou: false,
                yourScope: 'personal',
                sharedByOthers: [TEAMMATE],
                teamSharedByOthers: [],
            },
            'teammate-team': {
                sharedByYou: false,
                yourScope: 'personal',
                sharedByOthers: [TEAMMATE],
                teamSharedByOthers: [TEAMMATE],
            },
            both: {
                sharedByYou: true,
                yourScope: 'personal',
                sharedByOthers: [TEAMMATE],
                teamSharedByOthers: [TEAMMATE],
            },
            unshared: { sharedByYou: false, yourScope: 'personal', sharedByOthers: [], teamSharedByOthers: [] },
        })
    })

    it('attributes no grant while the current user is still loading', () => {
        userLogic.actions.loadUserSuccess(null)
        parentLogic.actions.loadServiceAccountsSuccess([
            serviceAccount('both', [
                { user: YOU, scope: 'team' },
                { user: TEAMMATE, scope: 'team' },
            ]),
        ])

        expect(logic.values.agentSharesByAccountId).toEqual({
            both: { sharedByYou: false, yourScope: 'personal', sharedByOthers: [], teamSharedByOthers: [] },
        })
    })

    it('uses the policy mutation response while keeping the loader in flight', async () => {
        const pendingResponse = deferred<Awaited<ReturnType<typeof mcpGatewayServersPoliciesCreate>>>()
        const updatedPolicy = toolPolicy('create_issue', { policy_state: 'needs_approval' })
        mockPoliciesCreate.mockReturnValue(pendingResponse.promise)

        logic.actions.setToolPolicy({ toolName: updatedPolicy.tool_name, state: updatedPolicy.policy_state })

        expect(logic.values.toolPoliciesLoading).toBe(true)
        expect(mockPoliciesCreate).toHaveBeenCalledTimes(1)

        pendingResponse.resolve({ count: 1, results: [updatedPolicy] })
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.toolPoliciesLoading).toBe(false)
        expect(logic.values.toolPolicies).toEqual([updatedPolicy])
        expect(mockToolsRetrieve).toHaveBeenCalledTimes(1)
    })

    it('discards a stale policy response after the scope changes', async () => {
        const staleResponse = deferred<Awaited<ReturnType<typeof mcpGatewayServersToolsRetrieve>>>()
        const latestResponse = deferred<Awaited<ReturnType<typeof mcpGatewayServersToolsRetrieve>>>()
        const stalePolicy = toolPolicy('create_issue', { policy_state: 'approved' })
        const latestPolicy = toolPolicy('create_issue', { policy_state: 'needs_approval' })
        mockToolsRetrieve.mockReset()
        mockToolsRetrieve.mockReturnValueOnce(staleResponse.promise).mockReturnValueOnce(latestResponse.promise)

        logic.actions.setScope({ scopeType: 'team', label: 'Team default' })
        logic.actions.setScope({ scopeType: 'member', label: 'You' })

        expect(mockToolsRetrieve).toHaveBeenCalledTimes(2)

        latestResponse.resolve({ count: 1, results: [latestPolicy] })
        staleResponse.resolve({ count: 1, results: [stalePolicy] })
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.scope.scopeType).toBe('member')
        expect(logic.values.toolPolicies).toEqual([latestPolicy])
    })

    it('reports the number of tools changed by a bulk update', async () => {
        const editablePolicy = toolPolicy('create_issue')
        const lockedPolicy = toolPolicy('delete_issue', { locked: true, policy_state: 'do_not_use' })
        logic.actions.loadToolPoliciesSuccess([editablePolicy, lockedPolicy])
        mockPoliciesCreate.mockResolvedValue({
            count: 2,
            results: [{ ...editablePolicy, policy_state: 'needs_approval' }, lockedPolicy],
        })
        const toast = jest.spyOn(lemonToast, 'success')

        await expectLogic(logic, () => {
            logic.actions.setAllTools({ state: 'needs_approval' })
        }).toFinishAllListeners()

        expect(mockPoliciesCreate).toHaveBeenCalledWith(
            expect.any(String),
            'server-id',
            expect.objectContaining({
                policies: [{ tool_name: editablePolicy.tool_name, policy_state: 'needs_approval' }],
            })
        )
        expect(toast).toHaveBeenCalledWith('Updated 1 tool')
    })

    it('applies a bulk policy change only to tools matching the active search', async () => {
        const createPolicy = toolPolicy('create_issue')
        const deletePolicy = toolPolicy('delete_issue')
        logic.actions.loadToolPoliciesSuccess([createPolicy, deletePolicy])
        logic.actions.setToolSearch('create')
        mockPoliciesCreate.mockResolvedValue({
            count: 2,
            results: [{ ...createPolicy, policy_state: 'do_not_use' }, deletePolicy],
        })

        await expectLogic(logic, () => {
            logic.actions.setAllTools({ state: 'do_not_use' })
        }).toFinishAllListeners()

        expect(mockPoliciesCreate).toHaveBeenCalledWith(
            expect.any(String),
            'server-id',
            expect.objectContaining({
                policies: [{ tool_name: 'create_issue', policy_state: 'do_not_use' }],
            })
        )
    })

    it('shares only editable tools with an agent and uses destructive-only defaults', async () => {
        const account = serviceAccount()
        const safePolicy = toolPolicy('list_issues')
        const destructivePolicy = toolPolicy('create_issue', { is_destructive: true })
        const rulePolicy = toolPolicy('delete_issue', {
            decided_by: 'rule',
            locked: true,
            policy_state: 'do_not_use',
        })
        parentLogic.actions.loadServiceAccountsSuccess([account])
        logic.actions.openAgentAccessModal()
        logic.actions.loadTeamToolPoliciesSuccess([safePolicy, destructivePolicy, rulePolicy])
        logic.actions.setAgentAccessSelectedId(account.id)

        await expectLogic(logic, () => {
            logic.actions.submitAgentAccess()
        }).toFinishAllListeners()

        expect(mockServiceAccountAccess).toHaveBeenCalledWith(expect.any(String), account.id, {
            gateway_server_id: 'server-id',
            enabled: true,
            scope: 'team',
            policies: [
                { tool_name: 'list_issues', policy_state: 'approved' },
                { tool_name: 'create_issue', policy_state: 'do_not_use' },
            ],
        })
        expect(logic.values.agentAccessModalOpen).toBe(false)
    })

    it('sends the scope picked in the share modal instead of the team default', async () => {
        const account = serviceAccount()
        parentLogic.actions.loadServiceAccountsSuccess([account])
        logic.actions.openAgentAccessModal()
        logic.actions.loadTeamToolPoliciesSuccess([toolPolicy('list_issues')])
        logic.actions.setAgentAccessSelectedId(account.id)
        logic.actions.setAgentAccessScope('personal')

        await expectLogic(logic, () => {
            logic.actions.submitAgentAccess()
        }).toFinishAllListeners()

        expect(mockServiceAccountAccess).toHaveBeenCalledWith(
            expect.any(String),
            account.id,
            expect.objectContaining({ scope: 'personal' })
        )
    })

    it.each([
        {
            condition: 'the team server is off',
            overrides: { is_team_enabled: false },
            reason: 'Turn this server on for the team before sharing it with an agent.',
        },
        {
            condition: 'the caller is revoked',
            overrides: { is_revoked_for_you: true },
            reason: 'Ask an admin to restore your access before sharing this server.',
        },
        {
            condition: 'the caller is not connected',
            overrides: { your_connection: null },
            reason: 'Connect this server before sharing it with an agent.',
        },
        {
            condition: 'OAuth is incomplete',
            overrides: { your_connection: gatewayConnection({ pending_oauth: true }) },
            reason: 'Finish connecting this server before sharing it with an agent.',
        },
        {
            condition: 'the connection needs reauthentication',
            overrides: { your_connection: gatewayConnection({ needs_reauth: true }) },
            reason: 'Reconnect this server before sharing it with an agent.',
        },
        {
            condition: 'the connection is disabled',
            overrides: { your_connection: gatewayConnection({ is_enabled: false }) },
            reason: 'Turn your connection on before sharing this server with an agent.',
        },
    ] as const)('blocks opening and submitting an agent grant when $condition', async ({ overrides, reason }) => {
        const account = serviceAccount()
        parentLogic.actions.loadServersSuccess([gatewayServer(overrides)])
        parentLogic.actions.loadServiceAccountsSuccess([account])
        logic.actions.loadTeamToolPoliciesSuccess([toolPolicy('list_issues')])
        logic.actions.setAgentAccessSelectedId(account.id)
        mockToolsRetrieve.mockClear()

        logic.actions.openAgentAccessModal()
        logic.actions.submitAgentAccess()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.agentShareDisabledReason).toBe(reason)
        expect(logic.values.agentAccessModalOpen).toBe(false)
        expect(mockToolsRetrieve).not.toHaveBeenCalled()
        expect(mockServiceAccountAccess).not.toHaveBeenCalled()
    })

    it.each([
        ['OAuth is incomplete', { pending_oauth: true }, null],
        ['the connection needs reauthentication', { needs_reauth: true }, null],
        ['the connection is off for the member', { is_enabled: false }, 'installation-id'],
    ] as const)(
        'resolves the refresh installation when %s',
        async (_condition, connectionOverrides, expectedInstallationId) => {
            parentLogic.actions.loadServersSuccess([
                gatewayServer({ your_connection: gatewayConnection(connectionOverrides) }),
            ])
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.refreshInstallationId).toBe(expectedInstallationId)
        }
    )

    it('resyncs the policy scope when Settings history changes scope on the same server', async () => {
        const account = { ...serviceAccount(), server_ids: ['server-id'] }
        const member = gatewayMember(42)
        parentLogic.actions.loadServiceAccountsSuccess([account])
        parentLogic.actions.loadMembersSuccess([member])

        gatewayServerLogic({ id: 'server-id', initialScope: `agent:${account.id}`, settingsMode: true })
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.scope.scopeServiceAccountId).toBe(account.id)

        gatewayServerLogic({ id: 'server-id', initialScope: `member:${member.user.id}`, settingsMode: true })
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.scope).toEqual({
            scopeType: 'member',
            scopeUserId: member.user.id,
            label: 'Ada Lovelace',
        })
    })

    it('keeps an explicit team scope in the Settings URL', async () => {
        logic.unmount()
        router.actions.push(urls.settings('mcp-servers'), { view: 'server', id: 'server-id', keep: 'value' })
        logic = gatewayServerLogic({ id: 'server-id', settingsMode: true })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.setScope({ scopeType: 'team', label: 'Team default' })

        expect(router.values.searchParams).toEqual({
            view: 'server',
            id: 'server-id',
            keep: 'value',
            scope: 'team',
        })
    })

    it('keeps an explicit team scope in the standalone server URL', async () => {
        logic.actions.setScope({ scopeType: 'team', label: 'Team default' })
        await expectLogic(logic).toFinishAllListeners()

        expect(router.values.location.pathname).toBe('/project/997/mcp-servers/server/server-id')
        expect(router.values.searchParams).toEqual({ scope: 'team' })
        expect(logic.values.scope).toEqual({ scopeType: 'team', label: 'Team default' })
    })

    it.each([
        ['oauth_complete', 'success', 'Server connected'],
        ['oauth_error', 'error', 'OAuth authorization failed. Try connecting the server again.'],
    ] as const)(
        'handles the %s callback on a standalone server detail while preserving URL state',
        async (queryParameter, toastType, message) => {
            const toast = jest.spyOn(lemonToast, toastType)

            router.actions.push(
                `${urls.mcpGatewayServer('server-id')}?scope=team&keep=value&${queryParameter}=true#panel=open`
            )
            await expectLogic(logic).toFinishAllListeners()

            expect(toast).toHaveBeenCalledWith(message)
            expect(router.values.location.pathname).toBe('/project/997/mcp-servers/server/server-id')
            expect(router.values.searchParams).toEqual({ scope: 'team', keep: 'value' })
            expect(router.values.hashParams).toEqual({ panel: 'open' })
            expect(logic.values.scope).toEqual({ scopeType: 'team', label: 'Team default' })
        }
    )

    it('handles a standalone callback that is already present when the detail logic mounts', async () => {
        logic.unmount()
        router.actions.push(
            `${urls.mcpGatewayServer('server-id')}?scope=team&keep=value&oauth_complete=true#panel=open`
        )
        const toast = jest.spyOn(lemonToast, 'success')
        logic = gatewayServerLogic({ id: 'server-id' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        expect(toast).toHaveBeenCalledWith('Server connected')
        expect(router.values.searchParams).toEqual({ scope: 'team', keep: 'value' })
        expect(router.values.hashParams).toEqual({ panel: 'open' })
        expect(logic.values.scope).toEqual({ scopeType: 'team', label: 'Team default' })
    })

    it('resolves an admin deep link to a member policy scope', async () => {
        const member = gatewayMember(42)
        parentLogic.actions.loadMembersSuccess([member])

        await expectLogic(logic, () => {
            logic.actions.setRequestedMemberScopeId(member.user.id)
        }).toFinishAllListeners()

        expect(logic.values.scope).toEqual({
            scopeType: 'member',
            scopeUserId: member.user.id,
            label: 'Ada Lovelace',
        })
        expect(mockToolsRetrieve).toHaveBeenLastCalledWith(expect.any(String), 'server-id', {
            scope_type: 'member',
            scope_user_id: member.user.id,
            scope_service_account_id: undefined,
        })
    })

    it('retrieves a directly linked member outside the loaded roster page', async () => {
        const member = gatewayMember(987)
        mockMemberRetrieve.mockResolvedValue(member)

        await expectLogic(logic, () => {
            logic.actions.setRequestedMemberScopeId(member.user.id)
        }).toFinishAllListeners()

        expect(mockMemberRetrieve).toHaveBeenCalledWith(expect.any(String), String(member.user.id))
        expect(logic.values.scope).toEqual({
            scopeType: 'member',
            scopeUserId: member.user.id,
            label: 'Ada Lovelace',
        })
    })
})
