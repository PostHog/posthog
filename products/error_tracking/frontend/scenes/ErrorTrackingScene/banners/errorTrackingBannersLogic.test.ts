import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { ErrorTrackingAIFeatureEnumApi } from '~/generated/core/api.schemas'
import { initKeaTests } from '~/test/init'

import { errorTrackingRecommendationsList } from '../../../generated/api'
import type { ErrorTrackingRecommendationApi } from '../../../generated/api.schemas'
import { ErrorTrackingBannerKey } from './bannerQueue'
import { errorTrackingBannersLogic } from './errorTrackingBannersLogic'
import { recommendationsLogic } from './recommendationsLogic'

jest.mock('../../../generated/api', () => ({
    errorTrackingRecommendationsList: jest.fn(),
}))

const mockList = jest.mocked(errorTrackingRecommendationsList)

const openRecommendation = (type: string, meta: Record<string, unknown>): ErrorTrackingRecommendationApi => ({
    id: type,
    type,
    meta,
    completed: false,
    status: 'ready',
    computed_at: '2024-07-08T00:00:00Z',
    dismissed_at: null,
    created_at: '2024-07-08T00:00:00Z',
    updated_at: '2024-07-08T00:00:00Z',
})

// Listed out of priority order, so the queue order comes from the logic and not from the API.
const OPEN_RECOMMENDATIONS = [
    openRecommendation('rate_limits', { rate_limits: [{ key: 'project', enabled: false }] }),
    openRecommendation('alerts', { alerts: [{ key: 'error-tracking-issue-created', enabled: false }] }),
    openRecommendation('issue_summaries', { enabled: false }),
    openRecommendation('source_maps', {}),
]

describe('errorTrackingBannersLogic', () => {
    let logic: ReturnType<typeof errorTrackingBannersLogic.build>

    afterEach(() => logic.unmount())

    it.each<[string, ErrorTrackingAIFeatureEnumApi[], ErrorTrackingBannerKey[]]>([
        [
            'puts issue summaries right after source maps',
            [ErrorTrackingAIFeatureEnumApi.IssueSummaries],
            ['source_maps', 'issue_summaries', 'alerts', 'rate_limits'],
        ],
        ['hides issue summaries from a team without the AI feature', [], ['source_maps', 'alerts', 'rate_limits']],
    ])('%s', async (_, features, expected) => {
        initKeaTests(true, { ...MOCK_DEFAULT_TEAM, available_error_tracking_ai_features: features })
        mockList.mockResolvedValue({ count: OPEN_RECOMMENDATIONS.length, results: OPEN_RECOMMENDATIONS })
        logic = errorTrackingBannersLogic()
        logic.mount()

        await expectLogic(recommendationsLogic).toDispatchActions(['setRecommendations'])

        expect(logic.values.activeBanners).toEqual(expected)
    })
})
