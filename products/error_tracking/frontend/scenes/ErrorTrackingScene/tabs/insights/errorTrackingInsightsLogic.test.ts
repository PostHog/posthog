import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import {
    ErrorTrackingIssueFilter,
    EventPropertyFilter,
    FilterLogicalOperator,
    PropertyFilterType,
    PropertyOperator,
    UniversalFiltersGroup,
} from '~/types'

import { issueFiltersLogic } from '../../../../components/IssueFilters/issueFiltersLogic'
import { ERROR_TRACKING_SCENE_LOGIC_KEY } from '../../errorTrackingSceneLogic'
import { errorTrackingInsightsLogic } from './errorTrackingInsightsLogic'

describe('errorTrackingInsightsLogic', () => {
    let issueFilters: ReturnType<typeof issueFiltersLogic.build>
    let insights: ReturnType<typeof errorTrackingInsightsLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/environments/:team_id/quick_filters/': { results: [] },
            },
        })
        initKeaTests()
        jest.spyOn(api, 'query').mockResolvedValue({ results: [[0, 0, 0, 0]] } as any)
        issueFilters = issueFiltersLogic({ logicKey: ERROR_TRACKING_SCENE_LOGIC_KEY })
        issueFilters.mount()
        insights = errorTrackingInsightsLogic()
        insights.mount()
    })

    afterEach(() => {
        insights.unmount()
        issueFilters.unmount()
        jest.restoreAllMocks()
    })

    it('strips issue filters from nested groups before building insights queries', async () => {
        const firefoxFilter: EventPropertyFilter = {
            type: PropertyFilterType.Event,
            key: '$browser',
            operator: PropertyOperator.Exact,
            value: ['Firefox'],
        }
        const chromeFilter: EventPropertyFilter = {
            type: PropertyFilterType.Event,
            key: '$browser',
            operator: PropertyOperator.Exact,
            value: ['Chrome'],
        }
        const issueFilter: ErrorTrackingIssueFilter = {
            type: PropertyFilterType.ErrorTrackingIssue,
            key: 'name',
            operator: PropertyOperator.Exact,
            value: ['TypeError'],
        }
        const quickFilter: EventPropertyFilter = {
            type: PropertyFilterType.Event,
            key: '$lib',
            operator: PropertyOperator.Exact,
            value: ['posthog-js'],
        }

        await expectLogic(insights, () => {
            issueFilters.actions.setFilterGroup({
                type: FilterLogicalOperator.And,
                values: [
                    {
                        type: FilterLogicalOperator.And,
                        values: [
                            {
                                type: FilterLogicalOperator.Or,
                                values: [firefoxFilter, issueFilter, chromeFilter],
                            },
                            quickFilter,
                        ],
                    },
                ],
            })
        }).toFinishAllListeners()

        const inner = insights.values.insightsFilterGroup.values[0] as UniversalFiltersGroup
        expect(inner.values).toEqual([
            {
                type: FilterLogicalOperator.Or,
                values: [firefoxFilter, chromeFilter],
            },
            quickFilter,
        ])
        expect(JSON.stringify(insights.values.exceptionVolumeQuery)).not.toContain(
            PropertyFilterType.ErrorTrackingIssue
        )

        const lastSummaryStatsQuery = jest.mocked(api.query).mock.calls.at(-1)?.[0] as any
        expect(lastSummaryStatsQuery.filters.properties).toEqual(inner.values)
        expect(JSON.stringify(lastSummaryStatsQuery.filters.properties)).not.toContain(
            PropertyFilterType.ErrorTrackingIssue
        )
    })
})
