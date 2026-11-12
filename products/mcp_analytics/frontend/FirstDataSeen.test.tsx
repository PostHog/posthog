import { cleanup, render } from '@testing-library/react'
import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { sceneLogic } from 'scenes/sceneLogic'
import { urls } from 'scenes/urls'

import { initKeaTests } from '~/test/init'

import { FirstDataSeen } from './FirstDataSeen'
import { type FirstDataSurface, mcpAnalyticsOnboardingLogic } from './mcpAnalyticsOnboardingLogic'
import { MCPAnalyticsScene } from './MCPAnalyticsScene'
import { mcpAnalyticsSceneLogic } from './mcpAnalyticsSceneLogic'
import { mcpSetupModeLogic } from './setupMode/mcpSetupModeLogic'

jest.mock('lib/api')
jest.mock('lib/utils/product-intents', () => ({ addProductIntent: jest.fn() }))

const mockApi = api as jest.Mocked<typeof api>

// Signal row shape: [has_initialize, tool_calls_total, tool_calls_7d, first_call_at]
const CONNECTED = [1, 0, 0, '1970-01-01T00:00:00Z']
const ONE_CALL = [1, 1, 1, '2026-07-01T00:00:00Z']

/** `mountHost` runs after the signal mocks are in place, because the logics it mounts query the signals too. */
async function arriveLive(
    mountHost: () => void = () => {}
): Promise<ReturnType<typeof mcpAnalyticsOnboardingLogic.build>> {
    jest.spyOn(mockApi, 'query')
        .mockReset()
        .mockResolvedValueOnce({ results: [CONNECTED] } as any)
        .mockResolvedValue({ results: [ONE_CALL] } as any)
    mountHost()
    const logic = mcpAnalyticsOnboardingLogic()
    logic.mount()
    await expectLogic(logic).toFinishAllListeners()
    logic.actions.loadSignals()
    await expectLogic(logic).toFinishAllListeners()
    expect(logic.values.firstDataWatch).toBe('arrived')
    return logic
}

describe('FirstDataSeen', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
        jest.restoreAllMocks()
    })

    it.each<[string, boolean, FirstDataSurface]>([
        ['the dashboard', false, 'dashboard'],
        ['setup mode', true, 'setup_mode'],
    ])('settles an arrival seen in %s and captures where', async (_label, inSetupMode, surface) => {
        const capture = jest.spyOn(posthog, 'capture').mockImplementation(() => undefined)
        const logic = await arriveLive(() => {
            if (inSetupMode) {
                featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.MCP_ANALYTICS_SETUP_MODE]: true })
                router.actions.push(urls.mcpAnalyticsDashboard(), { setup: 'open' })
                mcpSetupModeLogic.mount()
            }
        })

        render(<FirstDataSeen />)

        expect(logic.values.firstDataWatch).toBe('settled')
        expect(capture).toHaveBeenCalledWith(
            'mcp analytics first data seen live',
            expect.objectContaining({ surface }),
            undefined
        )
    })

    it('settles an arrival on a tab the scene renders as not found', async () => {
        jest.spyOn(posthog, 'capture').mockImplementation(() => undefined)
        const logic = await arriveLive(() => {
            sceneLogic.mount()
            sceneLogic.actions.setExportedScene({} as any, 'MCPAnalytics', 'mcpAnalyticsIntentClustering', {
                params: {},
                searchParams: {},
                hashParams: {},
            })
            mcpAnalyticsSceneLogic().mount()
        })

        const { getByText } = render(<MCPAnalyticsScene />)

        expect(getByText('Page not found')).toBeTruthy()
        expect(logic.values.firstDataWatch).toBe('settled')
    })
})
