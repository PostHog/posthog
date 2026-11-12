import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import { FEATURE_FLAGS } from 'lib/constants'
import { now } from 'lib/dayjs'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { userLogic } from 'scenes/userLogic'
import {
    MarketingAnalyticsTab,
    marketingAnalyticsLogic,
} from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsLogic'

import { initKeaTests } from '~/test/init'
import { expectLogic } from '~/test/keaTestUtils'
import { ExternalDataSource } from '~/types'

import { searchTabLogic } from './searchTabLogic'

jest.mock('posthog-js')

const loadSources = (sourceTypes: readonly string[]): void => {
    const results = sourceTypes.map(
        (source_type, index): Partial<ExternalDataSource> => ({ id: `source-${index}`, source_type, schemas: [] })
    ) as ExternalDataSource[]
    marketingAnalyticsLogic.actions.loadSourcesSuccess({ count: results.length, next: null, previous: null, results })
}

describe('searchTabLogic', () => {
    let logic: ReturnType<typeof searchTabLogic.build>

    beforeEach(async () => {
        localStorage.clear()
        initKeaTests()
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.MARKETING_ANALYTICS_ORGANIC_KEYWORDS], {
            [FEATURE_FLAGS.MARKETING_ANALYTICS_ORGANIC_KEYWORDS]: true,
        })
        userLogic.mount()
        userLogic.actions.loadUserSuccess(MOCK_DEFAULT_USER)
        marketingAnalyticsLogic.mount()
        await expectLogic(marketingAnalyticsLogic).toFinishAllListeners()
    })

    afterEach(() => {
        logic.unmount()
        localStorage.clear()
    })

    it.each([
        ['before the first visit', ['GoogleSearchConsole'], null, true],
        ['three days after the first visit', ['GoogleAds'], 3, true],
        ['seven days after the first visit', ['GoogleAds'], 7, false],
        ['once Google Ads and Search Console are both connected', ['GoogleAds', 'GoogleSearchConsole'], null, false],
    ] as const)('shows the tag %s', async (_label, sourceTypes, daysSinceFirstSeen, expected) => {
        logic = searchTabLogic()
        logic.mount()
        if (daysSinceFirstSeen !== null) {
            logic.actions.markSeen(MOCK_DEFAULT_USER.id, now().subtract(daysSinceFirstSeen, 'day').toISOString())
        }
        loadSources(sourceTypes)
        expect(logic.values.showNewTag).toBe(expected)
        const exposure = expectLogic(marketingAnalyticsLogic)
        await (expected
            ? exposure.toDispatchActions(['reportSearchNewTagShown'])
            : exposure.toNotHaveDispatchedActions(['reportSearchNewTagShown']))
    })

    it.each([
        ['a tab switch', ['GoogleAds'], false, true],
        ['a link that opens the Search tab', ['GoogleAds'], true, true],
        ['a link to a Search tab that is not shown', ['MetaAds'], true, false],
    ] as const)('starts the clock on %s', (_label, sourceTypes, tabBeforeMount, recorded) => {
        loadSources(sourceTypes)
        if (tabBeforeMount) {
            marketingAnalyticsLogic.actions.setActiveTab(MarketingAnalyticsTab.SEARCH_PERFORMANCE)
        }
        logic = searchTabLogic()
        logic.mount()
        if (!tabBeforeMount) {
            marketingAnalyticsLogic.actions.setActiveTab(MarketingAnalyticsTab.SEARCH_PERFORMANCE)
        }
        const firstSeenAt = logic.values.firstSeenAtByUser[MOCK_DEFAULT_USER.id]
        expect(!!firstSeenAt).toBe(recorded)

        const laterVisit = now().add(1, 'day').toISOString()
        logic.actions.markSeen(MOCK_DEFAULT_USER.id, laterVisit)
        expect(logic.values.firstSeenAtByUser[MOCK_DEFAULT_USER.id]).toBe(recorded ? firstSeenAt : laterVisit)
    })
})
