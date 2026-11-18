import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { Provider } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'

import { mcpAnalyticsIntentClustersRetrieve } from '../generated/api'
import type { MCPIntentClusterSnapshotApi } from '../generated/api.schemas'
import { MCPAnalyticsClustering } from './MCPAnalyticsClustering'
import { mcpClusteringLogic } from './mcpClusteringLogic'

jest.mock('lib/api')
jest.mock('../generated/api', () => ({
    mcpAnalyticsIntentClustersRetrieve: jest.fn(),
    mcpAnalyticsIntentClustersRecompute: jest.fn(),
}))

const COMPUTING_SNAPSHOT: MCPIntentClusterSnapshotApi = {
    status: 'computing',
    error_message: '',
    last_computed_at: null,
    last_computed_by_email: '',
    clusters: [],
    tools: [],
    tool_overlaps: [],
    long_tail: null,
    recurring: [],
    intent_text_redacted: false,
    computed_with: null,
}

describe('<MCPAnalyticsClustering />', () => {
    let logic: ReturnType<typeof mcpClusteringLogic.build>

    beforeEach(() => {
        initKeaTests()
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.MCP_ANALYTICS_INTENT_ROUTING], {
            [FEATURE_FLAGS.MCP_ANALYTICS_INTENT_ROUTING]: true,
        })
    })

    afterEach(() => {
        cleanup()
        logic.unmount()
    })

    it.each([
        { state: 'the first snapshot is loading', retrieve: () => new Promise(() => {}) },
        { state: 'clusters are computing', retrieve: () => Promise.resolve(COMPUTING_SNAPSHOT) },
    ])('shows the scorecard labels and descriptions while $state', async ({ retrieve }) => {
        jest.mocked(mcpAnalyticsIntentClustersRetrieve).mockImplementation(retrieve as any)
        logic = mcpClusteringLogic()
        logic.mount()

        render(
            <Provider>
                <MCPAnalyticsClustering />
            </Provider>
        )

        await waitFor(() => expect(screen.getByText('Concentrated')).toBeInTheDocument())
        expect(screen.getByText('One tool handles at least 80% of the calls.')).toBeInTheDocument()
        expect(screen.getByText('With errors')).toBeInTheDocument()
        expect(screen.queryByText(/^of \d+$/)).not.toBeInTheDocument()
    })
})
