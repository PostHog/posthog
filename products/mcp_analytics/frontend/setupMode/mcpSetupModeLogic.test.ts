import { MOCK_TEAM_ID } from 'lib/api.mock'

import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { productSetupStatusLogic } from 'lib/components/ProductEmptyState/productSetupStatusLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import posthog from 'lib/posthog-typed'
import { urls } from 'scenes/urls'

import { ProductKey } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { mcpSetupModeLogic, resetSetupModeTrackingForTests } from './mcpSetupModeLogic'

jest.mock('lib/api')
jest.mock('lib/posthog-typed', () => ({ __esModule: true, default: { capture: jest.fn(), captureRaw: jest.fn() } }))

const captureRawMock = posthog.captureRaw as jest.Mock

// Signal row shape: [has_initialize, tool_calls_total, tool_calls_7d, first_call_at]
const NOT_INSTRUMENTED = [0, 0, 0, '1970-01-01T00:00:00Z']

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
        { action: 'wizard command copied', route: 'wizard', expected: 'wizard', trigger: 'wizard_copy' },
        { action: 'agent prompt copied', route: 'agent', expected: 'agent', trigger: 'agent_copy' },
    ] as const)('opens the $expected path when the empty state reports "$action"', async (testCase) => {
        enableSetupMode(true)

        productSetupStatusLogic({ productKey: ProductKey.MCP_ANALYTICS }).actions.reportSetupInteraction(
            testCase.action,
            'needs-setup',
            testCase.route
        )
        await expectLogic(logic).toFinishAllListeners()

        expect(router.values.searchParams).toEqual({ landing: 'auto', setup: testCase.expected })
        expect(logic.values.setupPath).toBe(testCase.expected)
        expect(captureRawMock).toHaveBeenCalledWith('mcp analytics setup mode opened', {
            path: testCase.expected,
            trigger: testCase.trigger,
        })
    })

    it.each([
        { name: 'the flag is off', enabled: false, action: 'wizard command copied', preview: false },
        { name: 'the interaction is not a copy', enabled: true, action: 'docs clicked', preview: false },
        { name: 'the screen is a preview', enabled: true, action: 'wizard command copied', preview: true },
    ])('stays closed when $name', async (testCase) => {
        enableSetupMode(testCase.enabled)

        productSetupStatusLogic({ productKey: ProductKey.MCP_ANALYTICS }).actions.reportSetupInteraction(
            testCase.action,
            'needs-setup',
            'wizard',
            testCase.preview
        )
        await expectLogic(logic).toFinishAllListeners()

        expect(router.values.searchParams).toEqual({ landing: 'auto' })
        expect(logic.values.setupPath).toBe(null)
    })

    it.each([
        { reason: 'back', expectedPath: urls.mcpAnalyticsDashboard() },
        { reason: 'escape', expectedPath: urls.mcpAnalyticsDashboard() },
        { reason: 'finished', expectedPath: urls.mcpAnalyticsActivity() },
    ] as const)('exit with $reason removes the setup params and lands on $expectedPath', async (testCase) => {
        enableSetupMode(true)
        router.actions.push(urls.mcpAnalyticsDashboard(), { landing: 'auto', setup: 'agent', setup_step: 'useful' })
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.exitSetupMode(testCase.reason)
        await expectLogic(logic).toFinishAllListeners()

        expect(router.values.location.pathname).toBe(`/project/${MOCK_TEAM_ID}${testCase.expectedPath}`)
        expect(router.values.searchParams).toEqual({ landing: 'auto' })
        expect(logic.values.setupPath).toBe(null)
        expect(captureRawMock).toHaveBeenCalledWith('mcp analytics setup mode exited', {
            path: 'agent',
            step: 'connect',
            reason: testCase.reason,
        })
    })

    it('exits on Escape wherever focus is', async () => {
        enableSetupMode(true)
        router.actions.push(urls.mcpAnalyticsDashboard(), { setup: 'wizard' })
        await expectLogic(logic).toFinishAllListeners()

        window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
        await expectLogic(logic).toFinishAllListeners()

        expect(router.values.searchParams).toEqual({})
        expect(captureRawMock).toHaveBeenCalledWith('mcp analytics setup mode exited', {
            path: 'wizard',
            step: 'connect',
            reason: 'escape',
        })
    })
})
