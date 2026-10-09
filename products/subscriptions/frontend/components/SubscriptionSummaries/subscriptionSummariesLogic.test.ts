import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'

import { subscriptionsSummariesList } from 'products/subscriptions/frontend/generated/api'

import { subscriptionSummariesLogic } from './subscriptionSummariesLogic'

jest.mock('products/subscriptions/frontend/generated/api', () => ({
    subscriptionsSummariesList: jest.fn(),
}))

const mockSummariesList = subscriptionsSummariesList as jest.Mock

const summary = (id: string): Record<string, unknown> => ({
    id,
    subscription: 1,
    subscription_title: 'Weekly',
    target_type: 'email',
    change_summary: `Summary ${id}`,
    period_start: null,
    created_at: '2026-01-01T00:00:00Z',
})

describe('subscriptionSummariesLogic', () => {
    let logic: ReturnType<typeof subscriptionSummariesLogic.build>

    beforeEach(() => {
        initKeaTests()
        mockSummariesList.mockReset()
        mockSummariesList.mockResolvedValue({ next: null, previous: null, results: [summary('b'), summary('a')] })
    })

    afterEach(() => {
        logic?.unmount()
    })

    it.each([
        { flagEnabled: false, expectedSummaries: null, expectedCalls: 0 },
        { flagEnabled: true, expectedSummaries: [summary('b'), summary('a')], expectedCalls: 1 },
    ])(
        'loads summaries for the source only when the flag is enabled ($flagEnabled)',
        async ({ flagEnabled, expectedSummaries, expectedCalls }) => {
            featureFlagLogic.actions.setFeatureFlags([], {
                [FEATURE_FLAGS.SUBSCRIPTION_SOURCE_SUMMARIES]: flagEnabled,
            })
            logic = subscriptionSummariesLogic({ dashboardId: 7 })
            logic.mount()

            await expectLogic(logic).toFinishAllListeners().toMatchValues({ summaries: expectedSummaries })
            expect(mockSummariesList).toHaveBeenCalledTimes(expectedCalls)
            if (expectedCalls) {
                expect(mockSummariesList).toHaveBeenCalledWith(expect.any(String), { dashboard: 7 })
                expect(logic.values.latestSummary).toEqual(summary('b'))
                expect(logic.values.earlierSummaries).toEqual([summary('a')])
            }
        }
    )
})
