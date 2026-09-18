import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import type { ErrorEventType } from 'lib/components/Errors/types'
import { BREAKDOWN_NULL_STRING_LABEL } from 'scenes/insights/utils'

import { useMocks } from '~/mocks/jest'
import type {
    ErrorTrackingBreakdownsQuery,
    ErrorTrackingBreakdownsQueryResponse,
} from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { errorTrackingIssueSceneLogic } from '../../scenes/ErrorTrackingIssueScene/errorTrackingIssueSceneLogic'
import { ERROR_TRACKING_ISSUE_SCENE_LOGIC_KEY, issueFiltersLogic } from '../IssueFilters/issueFiltersLogic'
import { BREAKDOWN_DETAILS_LIMIT, BREAKDOWN_PRESETS, MAX_SELECTED_EVENT_BREAKDOWN_PROPERTIES } from './consts'
import {
    buildBreakdownProperties,
    getSelectedEventBreakdownProperties,
    miniBreakdownsLogic,
} from './miniBreakdownsLogic'

describe('miniBreakdownsLogic', () => {
    let filters: ReturnType<typeof issueFiltersLogic.build>
    let breakdowns: ReturnType<typeof miniBreakdownsLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/environments/:team_id/quick_filters/': { results: [] },
                '/api/environments/:team_id/error_tracking/issues/:id/': {},
                '/api/environments/:team_id/error_tracking/fingerprints': { results: [] },
                '/api/environments/:team_id/error_tracking/spike_events': { results: [] },
                '/api/projects/:team_id/signals/reports/': { results: [] },
            },
        })
        initKeaTests()
        jest.spyOn(api, 'query').mockResolvedValue({ results: {} } as ErrorTrackingBreakdownsQueryResponse)
        filters = issueFiltersLogic({ logicKey: ERROR_TRACKING_ISSUE_SCENE_LOGIC_KEY })
        filters.mount()
        breakdowns = miniBreakdownsLogic({ issueId: 'issue-id' })
        breakdowns.mount()
    })

    afterEach(() => {
        breakdowns.unmount()
        filters.unmount()
        jest.restoreAllMocks()
    })

    it('surfaces and clears a response load failure', () => {
        breakdowns.actions.loadResponseFailure('Failed to load breakdowns')
        expect(breakdowns.values.responseError).toBe('Failed to load breakdowns')

        breakdowns.actions.loadResponse()
        expect(breakdowns.values.responseError).toBeNull()
    })

    it('limits the default breakdown query to the configured presets', async () => {
        await expectLogic(breakdowns).toFinishAllListeners()

        const query = jest.mocked(api.query).mock.calls.at(-1)?.[0] as ErrorTrackingBreakdownsQuery
        expect(query.breakdownProperties).toEqual([
            '$browser',
            '$device_type',
            '$os',
            '$pathname',
            '$user_id',
            '$ip',
            '$geoip_country_name',
            '$geoip_city_name',
        ])
    })

    it('adds primitive properties from the selected event without duplicating configured breakdowns', async () => {
        const properties = {
            $browser: 'Chrome',
            account_tier: 'paid',
            attempt: 2,
            enabled: true,
            nested: { source: 'checkout' },
            tags: ['web'],
        }
        const selectedEventProperties = getSelectedEventBreakdownProperties(properties, false)

        expect(buildBreakdownProperties(selectedEventProperties)).toEqual([
            ...BREAKDOWN_PRESETS,
            { property: 'account_tier', title: 'account_tier' },
            { property: 'attempt', title: 'attempt' },
            { property: 'enabled', title: 'enabled' },
        ])

        const issueScene = errorTrackingIssueSceneLogic({ id: 'issue-id' })
        await expectLogic(breakdowns, () => {
            issueScene.actions.selectEvent({
                event: '$exception',
                uuid: 'event-id',
                timestamp: '2026-08-13T12:00:00Z',
                distinct_id: 'person-id',
                properties,
                person: { id: 'person-id', distinct_ids: ['person-id'], properties: {} },
            } as ErrorEventType)
        }).toFinishAllListeners()

        expect(breakdowns.values.breakdownProperties).toEqual([
            ...BREAKDOWN_PRESETS,
            { property: 'account_tier', title: 'account_tier' },
            { property: 'attempt', title: 'attempt' },
            { property: 'enabled', title: 'enabled' },
        ])
    })

    it('caps the breakdown properties auto-derived from the selected event', () => {
        const properties = Object.fromEntries(
            Array.from({ length: MAX_SELECTED_EVENT_BREAKDOWN_PROPERTIES + 5 }, (_, index) => [
                `custom_prop_${String(index).padStart(2, '0')}`,
                'value',
            ])
        )

        expect(getSelectedEventBreakdownProperties(properties, false)).toHaveLength(
            MAX_SELECTED_EVENT_BREAKDOWN_PROPERTIES
        )
    })

    it('hides breakdown properties without values after loading', () => {
        expect(breakdowns.values.visibleBreakdownProperties).toEqual(BREAKDOWN_PRESETS)

        breakdowns.actions.loadResponseSuccess({
            results: {
                $browser: { values: [{ value: 'Chrome', count: 2 }], total_count: 2 },
                $os: { values: [{ value: BREAKDOWN_NULL_STRING_LABEL, count: 2 }], total_count: 2 },
            },
        })

        expect(breakdowns.values.visibleBreakdownProperties).toEqual([
            BREAKDOWN_PRESETS.find(({ property }) => property === '$browser'),
        ])
    })

    it('loads the expanded value set when opening breakdown details', async () => {
        await expectLogic(breakdowns).toFinishAllListeners()
        const breakdown = BREAKDOWN_PRESETS[0]

        await expectLogic(breakdowns, () => {
            breakdowns.actions.openBreakdownDetails(breakdown)
        })
            .toDispatchActions(['openBreakdownDetails', 'loadBreakdownDetails', 'loadBreakdownDetailsSuccess'])
            .toFinishAllListeners()

        expect(breakdowns.values.selectedBreakdownProperty).toEqual(breakdown)
        const detailsQuery = jest.mocked(api.query).mock.calls.at(-1)?.[0] as ErrorTrackingBreakdownsQuery
        expect(detailsQuery.breakdownProperties).toEqual([breakdown.property])
        expect(detailsQuery.maxValuesPerProperty).toBe(BREAKDOWN_DETAILS_LIMIT)

        breakdowns.actions.closeBreakdownDetails()
        expect(breakdowns.values.selectedBreakdownProperty).toBeNull()
    })

    it('reloads breakdowns and details with the active property filters', async () => {
        await expectLogic(breakdowns).toFinishAllListeners()
        const queryMock = jest.mocked(api.query)
        const previousBreakdownQueryCount = queryMock.mock.calls.filter(
            ([query]) => query.kind === 'ErrorTrackingBreakdownsQuery'
        ).length

        await expectLogic(breakdowns, () => {
            filters.actions.addPropertyFilter('$browser', 'Chrome')
        }).toFinishAllListeners()

        const breakdownQueries = queryMock.mock.calls
            .map(([query]) => query)
            .filter((query): query is ErrorTrackingBreakdownsQuery => query.kind === 'ErrorTrackingBreakdownsQuery')
        expect(breakdownQueries).toHaveLength(previousBreakdownQueryCount + 1)
        expect(breakdownQueries.at(-1)?.filterGroup).toEqual(filters.values.filterGroup)

        await expectLogic(breakdowns, () => {
            breakdowns.actions.openBreakdownDetails(BREAKDOWN_PRESETS[0])
        }).toFinishAllListeners()
        const detailsQuery = queryMock.mock.calls.at(-1)?.[0] as ErrorTrackingBreakdownsQuery
        expect(detailsQuery.filterGroup).toEqual(filters.values.filterGroup)
    })

    it('discards details returned for a property that was superseded', async () => {
        await expectLogic(breakdowns).toFinishAllListeners()
        let resolveFirstRequest: (response: ErrorTrackingBreakdownsQueryResponse) => void = () => {}
        let markFirstRequestStarted: () => void = () => {}
        const firstRequestStarted = new Promise<void>((resolve) => {
            markFirstRequestStarted = resolve
        })
        const firstResponse: ErrorTrackingBreakdownsQueryResponse = {
            results: { $browser: { values: [], total_count: 0 } },
        }
        const secondResponse: ErrorTrackingBreakdownsQueryResponse = {
            results: { $device_type: { values: [], total_count: 0 } },
        }
        const queryMock = jest.mocked(api.query)
        const existingCallCount = queryMock.mock.calls.length
        queryMock
            .mockImplementationOnce(
                () =>
                    new Promise((resolve) => {
                        resolveFirstRequest = resolve
                        markFirstRequestStarted()
                    })
            )
            .mockResolvedValueOnce(secondResponse)

        breakdowns.actions.openBreakdownDetails(BREAKDOWN_PRESETS[0])
        await firstRequestStarted
        expect(queryMock.mock.calls).toHaveLength(existingCallCount + 1)
        await expectLogic(breakdowns, () => {
            breakdowns.actions.openBreakdownDetails(BREAKDOWN_PRESETS[1])
        }).toDispatchActions(['loadBreakdownDetailsSuccess'])
        expect(breakdowns.values.breakdownDetails).toEqual(secondResponse)

        resolveFirstRequest(firstResponse)
        await expectLogic(breakdowns).toFinishAllListeners()
        expect(breakdowns.values.breakdownDetails).toEqual(secondResponse)
    })
})
