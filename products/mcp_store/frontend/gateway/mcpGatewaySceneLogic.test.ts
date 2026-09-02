import { router } from 'kea-router'

import { lemonToast } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { initKeaTests } from '~/test/init'
import { expectLogic } from '~/test/keaTestUtils'

import {
    mcpGatewayConfigList,
    mcpGatewayRulesList,
    mcpGatewayServersList,
    mcpGatewayServiceAccountsList,
    mcpServersList,
} from '../generated/api'
import type { TeamMCPGatewayConfigApi } from '../generated/api.schemas'
import { mcpGatewayLogic } from './mcpGatewayLogic'
import { mcpGatewaySceneLogic } from './mcpGatewaySceneLogic'

jest.mock('../generated/api', () => ({
    ...jest.requireActual('../generated/api'),
    mcpGatewayConfigList: jest.fn(),
    mcpGatewayRulesList: jest.fn(),
    mcpGatewayServersList: jest.fn(),
    mcpGatewayServiceAccountsList: jest.fn(),
    mcpServersList: jest.fn(),
}))

const mockConfigList = jest.mocked(mcpGatewayConfigList)
const mockRulesList = jest.mocked(mcpGatewayRulesList)
const mockServersList = jest.mocked(mcpGatewayServersList)
const mockServiceAccountsList = jest.mocked(mcpGatewayServiceAccountsList)
const mockTemplatesList = jest.mocked(mcpServersList)

describe('mcpGatewaySceneLogic', () => {
    let gatewayLogic: ReturnType<typeof mcpGatewayLogic.build>
    let sceneLogic: ReturnType<typeof mcpGatewaySceneLogic.build>

    const mountLogics = (): void => {
        gatewayLogic = mcpGatewayLogic()
        gatewayLogic.mount()
        sceneLogic = mcpGatewaySceneLogic()
        sceneLogic.mount()
    }

    beforeEach(() => {
        initKeaTests()
        jest.resetAllMocks()
        mockConfigList.mockResolvedValue({
            is_admin: false,
            registered_template_ids: [],
            allow_custom_servers: true,
            allow_member_agent_access: true,
        })
        mockRulesList.mockResolvedValue({ count: 0, results: [] })
        mockServersList.mockResolvedValue({ count: 0, results: [] })
        mockServiceAccountsList.mockResolvedValue({ count: 0, results: [] })
        mockTemplatesList.mockResolvedValue({ count: 0, results: [] })
    })

    afterEach(() => {
        sceneLogic.unmount()
        gatewayLogic.unmount()
        jest.restoreAllMocks()
    })

    it.each([
        ['oauth_complete', 'success', 'Server connected'],
        ['oauth_error', 'error', 'OAuth authorization failed. Try connecting the server again.'],
    ] as const)(
        'handles the %s callback while preserving unrelated URL state',
        async (queryParameter, toastType, message) => {
            mountLogics()
            await expectLogic(gatewayLogic).toFinishAllListeners()
            const toast = jest.spyOn(lemonToast, toastType)

            router.actions.push(`${urls.mcpGateway()}?keep=value&${queryParameter}=true#panel=open`)

            expect(toast).toHaveBeenCalledWith(message)
            expect(router.values.location.pathname).toBe('/project/997/mcp-servers')
            expect(router.values.searchParams).toEqual({ keep: 'value' })
            expect(router.values.hashParams).toEqual({ panel: 'open' })
        }
    )

    it.each(['team', 'settings'] as const)(
        'redirects a non-admin from a direct %s tab URL to the servers tab',
        async (tab) => {
            let resolveConfig!: (config: TeamMCPGatewayConfigApi) => void
            mockConfigList.mockReturnValueOnce(
                new Promise((resolve) => {
                    resolveConfig = resolve
                })
            )
            router.actions.push(urls.mcpGatewayTab(tab))
            mountLogics()

            expect(sceneLogic.values.activeTab).toBe(tab)

            resolveConfig({
                is_admin: false,
                registered_template_ids: [],
                allow_custom_servers: true,
                allow_member_agent_access: true,
            })
            await expectLogic(gatewayLogic).toFinishAllListeners()

            expect(router.values.location.pathname).toBe('/project/997/mcp-servers')
            expect(sceneLogic.values.activeTab).toBe('servers')
        }
    )

    it('allows a member to open the audit tab directly', async () => {
        router.actions.push(urls.mcpGatewayTab('audit'))
        mountLogics()

        await expectLogic(gatewayLogic).toFinishAllListeners()

        expect(sceneLogic.values.availableTabs).toEqual(['servers', 'audit'])
        expect(sceneLogic.values.activeTab).toBe('audit')
        expect(router.values.location.pathname).toBe('/project/997/mcp-servers/audit')
    })
})
