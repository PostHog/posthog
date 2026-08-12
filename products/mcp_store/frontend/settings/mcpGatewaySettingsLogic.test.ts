import { router } from 'kea-router'

import { lemonToast } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { initKeaTests } from '~/test/init'
import { expectLogic } from '~/test/keaTestUtils'

import { mcpGatewayLogic } from '../gateway/mcpGatewayLogic'
import {
    mcpGatewayConfigList,
    mcpGatewayMembersList,
    mcpGatewayRulesList,
    mcpGatewayServersList,
    mcpGatewayServiceAccountsList,
    mcpServersList,
} from '../generated/api'
import { mcpGatewaySettingsLogic } from './mcpGatewaySettingsLogic'

jest.mock('../generated/api', () => ({
    ...jest.requireActual('../generated/api'),
    mcpGatewayConfigList: jest.fn(),
    mcpGatewayMembersList: jest.fn(),
    mcpGatewayRulesList: jest.fn(),
    mcpGatewayServersList: jest.fn(),
    mcpGatewayServiceAccountsList: jest.fn(),
    mcpServersList: jest.fn(),
}))

const mockConfigList = jest.mocked(mcpGatewayConfigList)
const mockMembersList = jest.mocked(mcpGatewayMembersList)
const mockRulesList = jest.mocked(mcpGatewayRulesList)
const mockServersList = jest.mocked(mcpGatewayServersList)
const mockServiceAccountsList = jest.mocked(mcpGatewayServiceAccountsList)
const mockTemplatesList = jest.mocked(mcpServersList)

describe('mcpGatewaySettingsLogic', () => {
    let gatewayLogic: ReturnType<typeof mcpGatewayLogic.build> | undefined
    let settingsLogic: ReturnType<typeof mcpGatewaySettingsLogic.build> | undefined

    beforeEach(() => {
        initKeaTests()
        jest.resetAllMocks()
        mockMembersList.mockResolvedValue({ count: 0, results: [] })
        mockRulesList.mockResolvedValue({ count: 0, results: [] })
        mockServersList.mockResolvedValue({ count: 0, results: [] })
        mockServiceAccountsList.mockResolvedValue({ count: 0, results: [] })
        mockTemplatesList.mockResolvedValue({ count: 0, results: [] })
    })

    afterEach(() => {
        settingsLogic?.unmount()
        jest.restoreAllMocks()
    })

    async function mountSettings(isAdmin: boolean, expectedConfigRequests = 1): Promise<void> {
        mockConfigList.mockResolvedValue({ is_admin: isAdmin, registered_template_ids: [] })
        settingsLogic = mcpGatewaySettingsLogic()
        settingsLogic.mount()
        gatewayLogic = mcpGatewayLogic()
        await expectLogic(gatewayLogic).toFinishAllListeners()
        expect(mockConfigList).toHaveBeenCalledTimes(expectedConfigRequests)
    }

    it('syncs admin tabs to the Settings URL while preserving unrelated URL state', async () => {
        await mountSettings(true)

        router.actions.push(urls.settings('mcp-servers'), { tab: 'audit', keep: 'value' }, { panel: 'open' })

        expect(settingsLogic?.values.activeTab).toBe('audit')
        settingsLogic?.actions.setTab('team')
        expect(router.values.location.pathname).toBe('/project/997/settings/mcp-servers')
        expect(router.values.searchParams).toEqual({ keep: 'value', tab: 'team' })
        expect(router.values.hashParams).toEqual({ panel: 'open' })

        settingsLogic?.actions.setTab('servers')
        expect(router.values.searchParams).toEqual({ keep: 'value' })
    })

    it('shows the audit tab to members and keeps admin-only tabs unavailable', async () => {
        await mountSettings(false)

        router.actions.push(urls.settings('mcp-servers'), { tab: 'audit', keep: 'value' })

        expect(settingsLogic?.values.availableTabs).toEqual(['servers', 'audit'])
        expect(settingsLogic?.values.activeTab).toBe('audit')
        expect(router.values.searchParams).toEqual({ tab: 'audit', keep: 'value' })

        router.actions.push(urls.settings('mcp-servers'), { tab: 'team', keep: 'value' })

        expect(settingsLogic?.values.activeTab).toBe('servers')
        expect(router.values.searchParams).toEqual({ keep: 'value' })
    })

    it('keeps server, agent, and member details inside the Settings route', async () => {
        await mountSettings(true)
        router.actions.push(urls.settings('mcp-servers'), { keep: 'value' })

        settingsLogic?.actions.openAgent('scout-id')
        expect(router.values.location.pathname).toBe('/project/997/settings/mcp-servers')
        expect(router.values.searchParams).toEqual({ keep: 'value', tab: 'team', view: 'agent', id: 'scout-id' })
        expect(settingsLogic?.values.detailView).toBe('agent')
        expect(settingsLogic?.values.detailId).toBe('scout-id')

        settingsLogic?.actions.openServer('linear-id', 'agent:scout-id')
        expect(router.values.searchParams).toEqual({
            keep: 'value',
            view: 'server',
            id: 'linear-id',
            scope: 'agent:scout-id',
        })
        expect(settingsLogic?.values.activeTab).toBe('servers')
        expect(settingsLogic?.values.detailScope).toBe('agent:scout-id')

        settingsLogic?.actions.closeDetail('servers')
        expect(router.values.searchParams).toEqual({ keep: 'value' })
        expect(settingsLogic?.values.detailView).toBeNull()

        settingsLogic?.actions.openMember(12)
        expect(settingsLogic?.values.activeTab).toBe('team')
        expect(settingsLogic?.values.detailView).toBe('member')
        expect(settingsLogic?.values.detailId).toBe('12')
    })

    it('hydrates a member detail from the Settings URL when the logic mounts', async () => {
        router.actions.push(urls.settings('mcp-servers'), {
            tab: 'team',
            view: 'member',
            id: '12',
            keep: 'value',
        })

        await mountSettings(true)

        expect(settingsLogic?.values.activeTab).toBe('team')
        expect(settingsLogic?.values.detailView).toBe('member')
        expect(settingsLogic?.values.detailId).toBe('12')
        expect(router.values.searchParams).toEqual({ tab: 'team', view: 'member', id: '12', keep: 'value' })
    })

    it.each([
        ['oauth_complete', 'success', 'Server connected'],
        ['oauth_error', 'error', 'OAuth authorization failed. Try connecting the server again.'],
    ] as const)(
        'handles %s returns without losing the selected Settings tab',
        async (parameter, toastType, message) => {
            await mountSettings(true)
            const toast = jest.spyOn(lemonToast, toastType)
            const initialRequestCounts = [
                mockConfigList.mock.calls.length,
                mockServersList.mock.calls.length,
                mockTemplatesList.mock.calls.length,
                mockServiceAccountsList.mock.calls.length,
                mockRulesList.mock.calls.length,
            ]

            router.actions.push(`${urls.settings('mcp-servers')}?tab=audit&keep=value&${parameter}=true#panel=open`)
            await expectLogic(gatewayLogic!).toFinishAllListeners()

            expect(toast).toHaveBeenCalledWith(message)
            expect(settingsLogic?.values.activeTab).toBe('audit')
            expect(router.values.searchParams).toEqual({ tab: 'audit', keep: 'value' })
            expect(router.values.hashParams).toEqual({ panel: 'open' })
            expect([
                mockConfigList.mock.calls.length,
                mockServersList.mock.calls.length,
                mockTemplatesList.mock.calls.length,
                mockServiceAccountsList.mock.calls.length,
                mockRulesList.mock.calls.length,
            ]).toEqual(initialRequestCounts.map((count) => count + 1))
        }
    )

    it('handles an OAuth callback that is already present when the Settings logic mounts', async () => {
        router.actions.push(`${urls.settings('mcp-servers')}?tab=audit&keep=value&oauth_complete=true#panel=open`)
        const toast = jest.spyOn(lemonToast, 'success')

        await mountSettings(true, 2)

        expect(toast).toHaveBeenCalledWith('Server connected')
        expect(toast).toHaveBeenCalledTimes(1)
        expect(settingsLogic?.values.activeTab).toBe('audit')
        expect(router.values.searchParams).toEqual({ tab: 'audit', keep: 'value' })
        expect(router.values.hashParams).toEqual({ panel: 'open' })
    })

    it('refreshes gateway data once per return to the tab, then removes the listeners on unmount', async () => {
        await mountSettings(true)
        jest.spyOn(document, 'visibilityState', 'get').mockReturnValue('visible')
        const nowSpy = jest.spyOn(Date, 'now').mockReturnValue(1_000_000)
        const initialRequestCounts = [
            mockConfigList.mock.calls.length,
            mockServersList.mock.calls.length,
            mockTemplatesList.mock.calls.length,
            mockServiceAccountsList.mock.calls.length,
            mockRulesList.mock.calls.length,
        ]

        // Returning to the tab fires both events back-to-back, so only one refresh should go out
        window.dispatchEvent(new Event('focus'))
        document.dispatchEvent(new Event('visibilitychange'))
        await expectLogic(gatewayLogic!).toFinishAllListeners()

        expect([
            mockConfigList.mock.calls.length,
            mockServersList.mock.calls.length,
            mockTemplatesList.mock.calls.length,
            mockServiceAccountsList.mock.calls.length,
            mockRulesList.mock.calls.length,
        ]).toEqual(initialRequestCounts.map((count) => count + 1))

        nowSpy.mockReturnValue(1_005_000)
        document.dispatchEvent(new Event('visibilitychange'))
        await expectLogic(gatewayLogic!).toFinishAllListeners()

        expect([
            mockConfigList.mock.calls.length,
            mockServersList.mock.calls.length,
            mockTemplatesList.mock.calls.length,
            mockServiceAccountsList.mock.calls.length,
            mockRulesList.mock.calls.length,
        ]).toEqual(initialRequestCounts.map((count) => count + 2))

        settingsLogic?.unmount()
        settingsLogic = undefined
        nowSpy.mockReturnValue(1_010_000)
        window.dispatchEvent(new Event('focus'))
        document.dispatchEvent(new Event('visibilitychange'))

        expect([
            mockConfigList.mock.calls.length,
            mockServersList.mock.calls.length,
            mockTemplatesList.mock.calls.length,
            mockServiceAccountsList.mock.calls.length,
            mockRulesList.mock.calls.length,
        ]).toEqual(initialRequestCounts.map((count) => count + 2))
    })
})
