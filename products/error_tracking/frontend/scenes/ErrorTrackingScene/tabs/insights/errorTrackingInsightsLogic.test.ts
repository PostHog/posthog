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
        expect(JSON.stringify(insights.values.issuesCreatedQuery)).not.toContain(PropertyFilterType.ErrorTrackingIssue)

        // Every HogQL query behind the tab has to see the same stripped properties as the charts, or a
        // metric tile disagrees with the chart under it about which events matched.
        const hogQLQueries = jest.mocked(api.query).mock.calls.map(([query]) => query as any)
        expect(hogQLQueries.length).toBeGreaterThan(0)
        for (const query of hogQLQueries) {
            expect(query.filters.properties).toEqual(inner.values)
            expect(JSON.stringify(query.filters.properties)).not.toContain(PropertyFilterType.ErrorTrackingIssue)
        }
    })

    it('applies a band as filters, marking a value it has none of as not set', async () => {
        await expectLogic(insights, () => {
            insights.actions.filterByBand([
                { key: '$app_namespace', value: 'web' },
                { key: '$app_version', value: '1.2.0' },
                { key: '$app_build', value: null },
            ])
        }).toFinishAllListeners()

        const inner = insights.values.insightsFilterGroup.values[0] as UniversalFiltersGroup
        expect(inner.values).toEqual([
            { type: PropertyFilterType.Event, key: '$app_namespace', operator: PropertyOperator.Exact, value: ['web'] },
            { type: PropertyFilterType.Event, key: '$app_version', operator: PropertyOperator.Exact, value: ['1.2.0'] },
            { type: PropertyFilterType.Event, key: '$app_build', operator: PropertyOperator.IsNotSet },
        ])
        // Every chip the click added has to be counted, or the filter bar opens the value editor on
        // all but the last of them.
        expect(issueFilters.values.filterAddedFromPreview).toBe(3)
    })

    // A band is one value spread over several properties. Left in an "Any" group its chips match
    // anything carrying any one of them, which is the opposite of filtering down to the band.
    it('makes the filter group conjunctive so a band cannot be applied as an OR', async () => {
        issueFilters.actions.setFilterGroup({
            type: FilterLogicalOperator.And,
            values: [
                {
                    type: FilterLogicalOperator.Or,
                    values: [
                        {
                            type: PropertyFilterType.Event,
                            key: '$browser',
                            operator: PropertyOperator.Exact,
                            value: ['Firefox'],
                        },
                    ],
                },
            ],
        })

        await expectLogic(insights, () => {
            insights.actions.filterByBand([{ key: '$app_namespace', value: 'web' }])
        }).toFinishAllListeners()

        const inner = issueFilters.values.filterGroup.values[0] as UniversalFiltersGroup
        expect(inner.type).toBe(FilterLogicalOperator.And)
    })
})
