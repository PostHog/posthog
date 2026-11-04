import { MOCK_TEAM_ID } from 'lib/api.mock'

import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import posthog from 'lib/posthog-typed'
import { removeProjectIdIfPresent } from 'lib/utils/kea-router'
import { urls } from 'scenes/urls'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { initKeaTests } from '~/test/init'
import { SidePanelTab } from '~/types'

import { mcpAnalyticsSessionsActivityOverview } from '../generated/api'
import { mcpSetupModeLogic, resetSetupModeTrackingForTests } from './mcpSetupModeLogic'

jest.mock('lib/api')
jest.mock('../generated/api', () => ({
    ...jest.requireActual('../generated/api'),
    mcpAnalyticsSessionsActivityOverview: jest.fn(),
}))
jest.mock('lib/posthog-typed', () => ({ __esModule: true, default: { capture: jest.fn(), captureRaw: jest.fn() } }))

const captureRawMock = posthog.captureRaw as jest.Mock

// Signal row shape: [has_initialize, tool_calls_total, tool_calls_7d, first_call_at]
const NOT_INSTRUMENTED = [0, 0, 0, '1970-01-01T00:00:00Z']
const CONNECTED = [1, 0, 0, '1970-01-01T00:00:00Z']
const ONE_CALL = [1, 1, 1, '2026-07-01T00:00:00Z']

describe('mcpSetupModeLogic', () => {
    let logic: ReturnType<typeof mcpSetupModeLogic.build>

    function enableSetupMode(enabled: boolean): void {
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.MCP_ANALYTICS_SETUP_MODE]: enabled })
    }

    beforeEach(() => {
        jest.clearAllMocks()
        initKeaTests()
        resetSetupModeTrackingForTests()
        jest.spyOn(api, 'query').mockResolvedValue({ results: [NOT_INSTRUMENTED] } as any)
        router.actions.push(urls.mcpAnalyticsDashboard(), { landing: 'auto' })
        logic = mcpSetupModeLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    it.each([
        { name: 'opens with the flag on', enabled: true, expectedParams: { landing: 'auto', setup: 'open' } },
        { name: 'stays closed with the flag off', enabled: false, expectedParams: { landing: 'auto' } },
    ])('Start setup $name', async ({ enabled, expectedParams }) => {
        enableSetupMode(enabled)

        logic.actions.openSetupMode('start_button')
        await expectLogic(logic).toFinishAllListeners()

        expect(router.values.searchParams).toEqual(expectedParams)
        expect(logic.values.isOpen).toBe(enabled)
        expect(captureRawMock).toHaveBeenCalledTimes(enabled ? 2 : 0)
    })

    it.each([
        { reason: 'back', expectedPath: urls.mcpAnalyticsDashboard() },
        { reason: 'escape', expectedPath: urls.mcpAnalyticsDashboard() },
        { reason: 'finished', expectedPath: urls.mcpAnalyticsActivity() },
    ] as const)('exit with $reason removes the setup params and lands on $expectedPath', async (testCase) => {
        enableSetupMode(true)
        router.actions.push(urls.mcpAnalyticsDashboard(), { landing: 'auto', setup: 'open', setup_step: 'useful' })
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.exitSetupMode(testCase.reason)
        await expectLogic(logic).toFinishAllListeners()

        expect(router.values.location.pathname).toBe(`/project/${MOCK_TEAM_ID}${testCase.expectedPath}`)
        expect(router.values.searchParams).toEqual({ landing: 'auto' })
        expect(logic.values.isOpen).toBe(false)
        expect(captureRawMock).toHaveBeenCalledWith('mcp analytics setup mode exited', {
            step: 'connect',
            reason: testCase.reason,
        })
    })

    it('asking PostHog AI closes setup mode before opening the side panel with the question', async () => {
        enableSetupMode(true)
        sidePanelStateLogic.mount()
        router.actions.push(urls.mcpAnalyticsDashboard(), { setup: 'open', setup_step: 'useful' })
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.askPostHogAI('What can MCP analytics tell me?')
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.isOpen).toBe(false)
        expect(router.values.location.pathname).toBe(`/project/${MOCK_TEAM_ID}${urls.mcpAnalyticsActivity()}`)
        expect(sidePanelStateLogic.values.selectedTab).toBe(SidePanelTab.Max)
        expect(sidePanelStateLogic.values.selectedTabOptions).toBe('!What can MCP analytics tell me?')
        expect(captureRawMock).toHaveBeenCalledWith('mcp analytics setup mode exited', {
            step: 'connect',
            reason: 'ask_ai',
        })
    })

    it.each([
        { page: 'the welcome page', path: urls.onboardingWelcome(), expectedPath: urls.mcpAnalytics() },
        // The onboarding step completes onboarding and redirects itself.
        {
            page: 'the onboarding install step',
            path: '/onboarding/mcp_analytics',
            expectedPath: '/onboarding/mcp_analytics',
        },
        { page: 'the scene', path: urls.mcpAnalyticsDashboard(), expectedPath: urls.mcpAnalyticsDashboard() },
    ])('keeps the first-call reveal open when the first call lands on $page', async (testCase) => {
        enableSetupMode(true)
        router.actions.push(testCase.path, { setup: 'open' })
        await expectLogic(logic).toFinishAllListeners()
        jest.spyOn(api, 'query').mockResolvedValue({ results: [ONE_CALL] } as any)

        logic.actions.loadSignals()
        await expectLogic(logic).toFinishAllListeners()

        expect(removeProjectIdIfPresent(router.values.location.pathname)).toBe(testCase.expectedPath)
        expect(router.values.searchParams).toMatchObject({ setup: 'open' })
    })

    it('reports a close by navigation as an exit and tracks the next open in full', async () => {
        enableSetupMode(true)
        logic.actions.openSetupMode('start_button')
        await expectLogic(logic).toFinishAllListeners()

        router.actions.push(urls.mcpAnalyticsDashboard())
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.openSetupMode('start_button')
        await expectLogic(logic).toFinishAllListeners()

        const events = captureRawMock.mock.calls.map(([event, properties]) => [event, properties])
        expect(events).toEqual([
            ['mcp analytics setup mode opened', { trigger: 'start_button' }],
            ['mcp analytics setup mode step viewed', { step: 'connect' }],
            ['mcp analytics setup mode exited', { step: 'connect', reason: 'navigated' }],
            ['mcp analytics setup mode opened', { trigger: 'start_button' }],
            ['mcp analytics setup mode step viewed', { step: 'connect' }],
        ])
    })

    describe('polling while setup mode connects', () => {
        beforeEach(() => {
            jest.useFakeTimers({ doNotFake: ['nextTick', 'queueMicrotask', 'setImmediate'] })
            // Mounted again under fake timers, so the onboarding logic's own poll runs here too.
            logic.unmount()
            logic = mcpSetupModeLogic()
            logic.mount()
        })
        afterEach(() => {
            jest.useRealTimers()
        })

        async function openAgentSetup(setupStep?: 'useful'): Promise<void> {
            enableSetupMode(true)
            router.actions.push(urls.mcpAnalyticsDashboard(), { setup: 'open', setup_step: setupStep })
            await jest.advanceTimersByTimeAsync(0)
        }

        it.each([
            { poll: 'signals', signals: CONNECTED, step: 'connect' },
            { poll: 'recent calls', signals: ONE_CALL, step: 'first-call' },
            { poll: 'recent calls on the last step', signals: ONE_CALL, step: 'useful' },
        ])(
            'waits for a slow $poll query instead of cancelling it with the next poll',
            async ({ poll, signals, step }) => {
                const query = jest
                    .spyOn(api, 'query')
                    .mockReset()
                    .mockResolvedValueOnce({ results: [signals] } as any)
                const overview = jest.mocked(mcpAnalyticsSessionsActivityOverview).mockReset()
                logic.actions.loadSignals()
                await jest.advanceTimersByTimeAsync(0)
                await openAgentSetup(step === 'useful' ? 'useful' : undefined)
                expect(logic.values.step).toBe(step)
                const slowRequest = poll === 'signals' ? query : overview
                slowRequest.mockReturnValue(new Promise(() => {}))
                const sentBefore = slowRequest.mock.calls.length

                await jest.advanceTimersByTimeAsync(31000)

                expect(slowRequest.mock.calls.length - sentBefore).toBe(1)
            }
        )

        it('retries soon when the first signals query fails, instead of spinning until the slow poll', async () => {
            logic.unmount()
            initKeaTests()
            const query = jest.spyOn(api, 'query').mockRejectedValueOnce(new Error('query failed'))
            logic = mcpSetupModeLogic()
            logic.mount()
            await jest.advanceTimersByTimeAsync(0)
            await openAgentSetup()
            expect(logic.values.step).toBeNull()
            query.mockResolvedValue({ results: [CONNECTED] } as any)

            await jest.advanceTimersByTimeAsync(6000)

            expect(logic.values.step).toBe('connect')
        })
    })

    it('exits on Escape wherever focus is', async () => {
        enableSetupMode(true)
        router.actions.push(urls.mcpAnalyticsDashboard(), { setup: 'open' })
        await expectLogic(logic).toFinishAllListeners()

        window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
        await expectLogic(logic).toFinishAllListeners()

        expect(router.values.searchParams).toEqual({})
        expect(captureRawMock).toHaveBeenCalledWith('mcp analytics setup mode exited', {
            step: 'connect',
            reason: 'escape',
        })
    })
})
