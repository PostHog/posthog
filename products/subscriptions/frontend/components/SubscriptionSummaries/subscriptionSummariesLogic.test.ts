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
        { flagEnabled: false, expectedSummaries: null, expectedLatest: null, expectedCalls: [] },
        {
            flagEnabled: true,
            expectedSummaries: [summary('b'), summary('a')],
            expectedLatest: summary('b'),
            expectedCalls: [[expect.any(String), { dashboard: 7 }]],
        },
    ])(
        'loads summaries for the source only when the flag is enabled ($flagEnabled)',
        async ({ flagEnabled, expectedSummaries, expectedLatest, expectedCalls }) => {
            featureFlagLogic.actions.setFeatureFlags([], {
                [FEATURE_FLAGS.SUBSCRIPTION_SOURCE_SUMMARIES]: flagEnabled,
            })
            logic = subscriptionSummariesLogic({ dashboardId: 7 })
            logic.mount()

            await expectLogic(logic)
                .toFinishAllListeners()
                .toMatchValues({ summaries: expectedSummaries, latestSummary: expectedLatest })
            expect(mockSummariesList.mock.calls).toEqual(expectedCalls)
        }
    )

    it('loads summaries when the flag turns on after the component is already mounted', async () => {
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.SUBSCRIPTION_SOURCE_SUMMARIES]: false })
        logic = subscriptionSummariesLogic({ dashboardId: 7 })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(mockSummariesList).not.toHaveBeenCalled()

        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.SUBSCRIPTION_SOURCE_SUMMARIES]: true })

        await expectLogic(logic)
            .toFinishAllListeners()
            .toMatchValues({ latestSummary: summary('b') })
        expect(mockSummariesList).toHaveBeenCalledTimes(1)
    })

    it('hides the latest summary once the flag turns off, so it also acts as a kill switch', async () => {
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.SUBSCRIPTION_SOURCE_SUMMARIES]: true })
        logic = subscriptionSummariesLogic({ dashboardId: 7 })
        logic.mount()
        await expectLogic(logic)
            .toFinishAllListeners()
            .toMatchValues({ latestSummary: summary('b') })

        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.SUBSCRIPTION_SOURCE_SUMMARIES]: false })

        expectLogic(logic).toMatchValues({ latestSummary: null })
        expect(mockSummariesList).toHaveBeenCalledTimes(1)
    })
})
