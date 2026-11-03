import { act, cleanup, render } from '@testing-library/react'
import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'

import { mcpAnalyticsOnboardingLogic } from '../mcpAnalyticsOnboardingLogic'
import { resetSetupModeTrackingForTests } from '../setupMode/mcpSetupModeLogic'
import { mcpAnalyticsOnboarding } from './steps'

jest.mock('lib/api')
jest.mock('lib/utils/product-intents', () => ({ addProductIntent: jest.fn() }))
jest.mock('scenes/onboarding/OnboardingStep', () => ({
    OnboardingStep: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}))
// The animated sidebar is not what this test is about, and it needs layout APIs jsdom lacks.
jest.mock('../emptyState/MCPSetupSidebar', () => ({ MCPSetupSidebar: () => null }))

// Signal row shape: [has_initialize, tool_calls_total, tool_calls_7d, first_call_at]
const CONNECTED = [1, 0, 0, '1970-01-01T00:00:00Z']
const ONE_CALL = [1, 1, 1, '2026-07-01T00:00:00Z']

describe('mcpAnalyticsOnboarding install step', () => {
    beforeEach(() => {
        initKeaTests()
        resetSetupModeTrackingForTests()
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.MCP_ANALYTICS_SETUP_MODE]: true })
    })

    afterEach(() => {
        cleanup()
        jest.restoreAllMocks()
    })

    it('keeps setup mode on screen while onboarding completes after the first call', async () => {
        jest.spyOn(api, 'query').mockResolvedValue({ results: [CONNECTED] } as any)
        jest.spyOn(api, 'get').mockResolvedValue({ recent_calls: [] } as any)
        // Hold the completion request open, so the redirect to the scene never happens during the test.
        jest.spyOn(api, 'update').mockReturnValue(new Promise(() => {}))
        router.actions.push('/onboarding/mcp_analytics', { step: 'install', setup: 'agent' })
        const [installStep] = mcpAnalyticsOnboarding.steps({
            featureFlags: { [FEATURE_FLAGS.MCP_ANALYTICS_SETUP_MODE]: true },
        } as any)
        render(<>{installStep.render()}</>)
        await act(async () => {
            await expectLogic(mcpAnalyticsOnboardingLogic).toFinishAllListeners()
        })
        const overlayShown = (): boolean => !!document.querySelector('[data-attr="mcp-analytics-setup-mode"]')
        expect(overlayShown()).toBe(true)

        jest.spyOn(api, 'query').mockResolvedValue({ results: [ONE_CALL] } as any)
        await act(async () => {
            mcpAnalyticsOnboardingLogic.actions.loadSignals()
            await expectLogic(mcpAnalyticsOnboardingLogic).toFinishAllListeners()
        })

        expect(overlayShown()).toBe(true)
    })
})
