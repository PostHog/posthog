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

    beforeEach(async () => {
        initKeaTests()
        jest.resetAllMocks()
        mockConfigList.mockResolvedValue({
            is_admin: false,
            allow_custom_servers: true,
            allow_member_agent_access: true,
        })
        mockRulesList.mockResolvedValue({ count: 0, results: [] })
        mockServersList.mockResolvedValue({ count: 0, results: [] })
        mockServiceAccountsList.mockResolvedValue({ count: 0, results: [] })
        mockTemplatesList.mockResolvedValue({ count: 0, results: [] })

        gatewayLogic = mcpGatewayLogic()
        gatewayLogic.mount()
        sceneLogic = mcpGatewaySceneLogic()
        sceneLogic.mount()
        await expectLogic(gatewayLogic).toFinishAllListeners()
    })

    afterEach(() => {
        sceneLogic.unmount()
        gatewayLogic.unmount()
        jest.restoreAllMocks()
    })

    it.each([
        ['oauth_complete', 'success', 'Server connected'],
        ['oauth_error', 'error', 'OAuth authorization failed'],
    ] as const)('handles the %s callback and clears it from the URL', (queryParameter, toastType, message) => {
        const toast = jest.spyOn(lemonToast, toastType)

        router.actions.push(urls.mcpGateway(), { [queryParameter]: 'true' })

        expect(toast).toHaveBeenCalledWith(message)
        expect(router.values.location.pathname).toBe('/project/997/mcp-servers')
        expect(router.values.searchParams).toEqual({})
    })
})
