import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { MarketingAnalyticsSearchQuery, NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { SearchRecommendationsRequestApi } from '../generated/api.schemas'
import { searchRecommendationsLogic } from './searchRecommendationsLogic'

describe('searchRecommendationsLogic', () => {
    let logic: ReturnType<typeof searchRecommendationsLogic.build>
    let requests: SearchRecommendationsRequestApi[]
    let fail: boolean
    const query: MarketingAnalyticsSearchQuery = {
        kind: NodeKind.MarketingAnalyticsSearchQuery,
        sources: [],
        compareFilter: { compare: true },
    }

    beforeEach(() => {
        initKeaTests()
        requests = []
        fail = false
        useMocks({
            post: {
                '/api/projects/:team_id/marketing_analytics/search_recommendations/': async ({ request }) => {
                    requests.push((await request.json()) as SearchRecommendationsRequestApi)
                    return fail
                        ? [500, { detail: 'Request failed' }]
                        : { result: { recommendations: [], goal_id: 'purchase', warning: 'Incomplete attribution' } }
                },
            },
        })
    })
    afterEach(() => logic?.unmount())

    it('does not request suggestions while disabled and preserves the selected goal and server warning', async () => {
        logic = searchRecommendationsLogic({ teamId: 2, query, goalId: 'purchase', enabled: false, refreshKey: null })
        await expectLogic(logic, () => {
            logic.mount()
        }).toFinishAllListeners()
        expect(requests).toEqual([])
        logic.unmount()
        logic = searchRecommendationsLogic({ teamId: 2, query, goalId: 'purchase', enabled: true, refreshKey: null })
        await expectLogic(logic, () => {
            logic.mount()
        }).toFinishAllListeners()
        expect(requests).toEqual([{ query, goal_id: 'purchase' }])
        expect(logic.values.result?.warning).toBe('Incomplete attribution')
        expect(logic.values.result?.goal_id).toBe('purchase')
    })

    it('shows a retryable error instead of claiming there are no suggestions', async () => {
        fail = true
        logic = searchRecommendationsLogic({ teamId: 2, query, goalId: 'purchase', enabled: true, refreshKey: null })
        await expectLogic(logic, () => {
            logic.mount()
        }).toFinishAllListeners()
        expect(logic.values.result?.warning).toBe('Could not load suggestions. Try again.')
        expect(logic.values.resultLoading).toBe(false)
        fail = false
        await expectLogic(logic, () => logic.actions.loadRecommendations()).toFinishAllListeners()
        expect(logic.values.result?.warning).toBe('Incomplete attribution')
        expect(requests).toHaveLength(2)
    })
})
