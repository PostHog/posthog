import { render, screen, waitFor } from '@testing-library/react'

import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'

import { mcpAnalyticsOnboardingLogic } from './mcpAnalyticsOnboardingLogic'
import { MCPAnalyticsScene } from './MCPAnalyticsScene'

jest.mock('lib/api')

const mockApi = api as jest.Mocked<typeof api>

describe('MCPAnalyticsScene', () => {
    beforeEach(() => {
        localStorage.clear()
        jest.clearAllMocks()
        initKeaTests()
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.MCP_ANALYTICS], {
            [FEATURE_FLAGS.MCP_ANALYTICS]: true,
        })
    })

    // The denied user used to get the full scene with every panel blank and nothing saying why.
    it('replaces the tabs with an access-denied state when the project is denied', async () => {
        jest.spyOn(mockApi, 'query').mockRejectedValue(Object.assign(new Error('Non-OK response'), { status: 403 }))
        const logic = mcpAnalyticsOnboardingLogic()
        logic.mount()
        await waitFor(() => expect(logic.values.accessDenied).toBe(true))

        render(<MCPAnalyticsScene />)

        expect(screen.getByText('Access denied')).not.toBeNull()
        expect(screen.queryByTestId('mcp-analytics-tabs')).toBeNull()
    })
})
