import { initKeaTests } from '~/test/init'

import { mcpLeaderboardHomeLogic } from './mcpLeaderboardHomeLogic'

jest.mock('lib/api')
jest.mock('posthog-js')
jest.mock('../generated/api', () => ({
    mcpAnalyticsIntentClustersRetrieve: jest.fn().mockResolvedValue({ status: 'idle', clusters: [] }),
    mcpAnalyticsIntentClustersRecompute: jest.fn(),
}))

describe('mcpLeaderboardHomeLogic', () => {
    beforeEach(() => {
        localStorage.clear()
        initKeaTests()
    })

    it('shows the metric the viewer picked after the scoreboard remounts', () => {
        const first = mcpLeaderboardHomeLogic()
        first.mount()
        expect(first.values.scoreboardMetric).toBe('calls')
        first.actions.setScoreboardMetric('users')
        first.unmount()

        const second = mcpLeaderboardHomeLogic()
        second.mount()

        expect(second.values.scoreboardMetric).toBe('users')
    })
})
