import { waitFor } from '@testing-library/dom'
import { expectLogic } from 'kea-test-utils'

import { performQuery } from '~/queries/query'
import {
    MarketingAnalyticsSearchQuery,
    MarketingAnalyticsSearchQueryResponse,
    MarketingAnalyticsSearchRow,
    NodeKind,
} from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { searchPerformanceTableLogic } from './searchPerformanceTableLogic'

jest.mock('~/queries/query', () => ({
    ...jest.requireActual('~/queries/query'),
    performQuery: jest.fn(),
}))

const mockedQuery = jest.mocked(performQuery)
const query: MarketingAnalyticsSearchQuery = {
    kind: NodeKind.MarketingAnalyticsSearchQuery,
    sources: [{ sourceType: 'GoogleAds', statsTable: 'example.landing_pages' }],
    breakdown: 'page',
    includePostHogConversions: true,
    dateRange: { date_from: '-7d' },
    compareFilter: { compare: true },
}
const row: MarketingAnalyticsSearchRow = {
    keyword: null,
    matchType: null,
    page: 'https://example.com/pricing',
    platform: 'GoogleAds',
    currency: 'USD',
    clicks: 100,
    impressions: 1000,
    cost: 200,
    conversions: 10,
    ctr: 0.1,
    cpc: 2,
    cpa: 20,
}
const baseResponse: MarketingAnalyticsSearchQueryResponse = { results: [row, { ...row, currency: 'EUR', cost: 100 }] }
const conversionsResponse: MarketingAnalyticsSearchQueryResponse = {
    posthogConversionGoals: [{ id: 'signup', name: 'Signups' }],
    results: [
        {
            ...row,
            currency: 'EUR',
            clicks: 999,
            posthogConversions: [{ id: 'signup', name: 'Signups', conversions: 5, costPerConversion: 20 }],
        },
        {
            ...row,
            clicks: 999,
            posthogConversions: [
                {
                    id: 'signup',
                    name: 'Signups',
                    conversions: 4,
                    costPerConversion: 50,
                    previousConversions: 2,
                    previousCostPerConversion: 80,
                },
            ],
        },
    ],
}

function deferred<T>(): { promise: Promise<T>; resolve: (value: T) => void; reject: (error: Error) => void } {
    let resolve!: (value: T) => void
    let reject!: (error: Error) => void
    const promise = new Promise<T>((resolvePromise, rejectPromise) => {
        resolve = resolvePromise
        reject = rejectPromise
    })
    return { promise, resolve, reject }
}

function conversionRequests(): MarketingAnalyticsSearchQuery[] {
    return mockedQuery.mock.calls
        .map(([query]) => query as MarketingAnalyticsSearchQuery)
        .filter((query) => query.includePostHogConversions)
}

describe('searchPerformanceTableLogic', () => {
    let logic: ReturnType<typeof searchPerformanceTableLogic.build>

    beforeEach(() => {
        initKeaTests()
        mockedQuery.mockReset()
    })
    afterEach(() => logic?.unmount())

    it.each(['success', 'failure'] as const)(
        'keeps search data visible during conversion loading and %s, with an independent retry',
        async (outcome) => {
            const pending = deferred<MarketingAnalyticsSearchQueryResponse>()
            mockedQuery.mockImplementation(async (query) =>
                (query as MarketingAnalyticsSearchQuery).includePostHogConversions ? pending.promise : baseResponse
            )
            logic = searchPerformanceTableLogic({ query, queryKey: 'search-test' })
            logic.mount()

            await waitFor(() => expect(logic.values.responseLoading).toBe(false))
            expect(logic.values.rows).toMatchObject(baseResponse.results)
            expect(logic.values.conversionsLoading).toBe(true)
            expect(logic.values.conversionsResponse).toBeNull()
            expect(
                mockedQuery.mock.calls.find(
                    ([query]) => !(query as MarketingAnalyticsSearchQuery).includePostHogConversions
                )?.[0]
            ).toMatchObject({
                includePostHogConversions: false,
                normalizePageUrls: true,
                compareFilter: { compare: true },
            })
            expect(conversionRequests()).toHaveLength(1)

            if (outcome === 'failure') {
                pending.reject(Object.assign(new Error('Conversion query failed'), { queryId: 'example-query-id' }))
                await waitFor(() => expect(logic.values.conversionsError).toBeTruthy())
                expect(logic.values.responseError).toBeNull()
                expect(logic.values.rows).toMatchObject(baseResponse.results)
                expect(logic.values.rows[0].posthogConversions).toBeUndefined()
                const baseRequests = mockedQuery.mock.calls.length - conversionRequests().length
                mockedQuery.mockResolvedValue(conversionsResponse)
                logic.actions.loadConversions('force_async')
                await waitFor(() => expect(logic.values.conversionsResponse).toEqual(conversionsResponse))
                expect(mockedQuery.mock.calls.length - conversionRequests().length).toBe(baseRequests)
                expect(conversionRequests()).toHaveLength(2)
            } else {
                pending.resolve(conversionsResponse)
                await waitFor(() => expect(logic.values.conversionsResponse).toEqual(conversionsResponse))
            }
            expect(logic.values.rows[0]).toMatchObject({
                clicks: 100,
                currency: 'USD',
                posthogConversions: [{ conversions: 4, previousConversions: 2 }],
            })
            expect(logic.values.rows[1]).toMatchObject({
                clicks: 100,
                currency: 'EUR',
                posthogConversions: [{ conversions: 5 }],
            })
            expect(logic.values.goals).toEqual(conversionsResponse.posthogConversionGoals)
        }
    )

    it('ignores an old conversion response after the date range changes', async () => {
        const old = deferred<MarketingAnalyticsSearchQueryResponse>()
        const current = deferred<MarketingAnalyticsSearchQueryResponse>()
        mockedQuery.mockImplementation(async (input) => {
            const request = input as MarketingAnalyticsSearchQuery
            return request.includePostHogConversions
                ? request.dateRange?.date_from === '-7d'
                    ? old.promise
                    : current.promise
                : baseResponse
        })
        logic = searchPerformanceTableLogic({ query, queryKey: 'search-test' })
        logic.mount()
        await waitFor(() => expect(logic.values.responseLoading).toBe(false))
        searchPerformanceTableLogic({ query: { ...query, dateRange: { date_from: '-30d' } }, queryKey: 'search-test' })
        await waitFor(() => expect(conversionRequests()).toHaveLength(2))
        await waitFor(() => expect(logic.values.responseLoading).toBe(false))
        expect(logic.values.rows).toMatchObject(baseResponse.results)
        current.resolve(conversionsResponse)
        await waitFor(() => expect(logic.values.conversionsResponse).toEqual(conversionsResponse))
        old.resolve({ results: [], posthogConversionGoals: [] })
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.conversionsResponse).toEqual(conversionsResponse)
        expect(logic.values.rows[0].posthogConversions?.[0].conversions).toBe(4)
    })

    it('removes goal columns when disabled and refreshes both requests on reload', async () => {
        mockedQuery.mockImplementation(async (query) =>
            (query as MarketingAnalyticsSearchQuery).includePostHogConversions ? conversionsResponse : baseResponse
        )
        logic = searchPerformanceTableLogic({ query, queryKey: 'search-test' })
        logic.mount()
        await waitFor(() => expect(logic.values.conversionsResponse).toEqual(conversionsResponse))
        logic.actions.loadData('force_async')
        await waitFor(() => expect(conversionRequests()).toHaveLength(2))
        await waitFor(() => expect(logic.values.conversionsLoading).toBe(false))
        searchPerformanceTableLogic({ query: { ...query, includePostHogConversions: false }, queryKey: 'search-test' })
        await waitFor(() => expect(logic.values.responseLoading).toBe(false))
        expect(logic.values.goals).toEqual([])
        expect(logic.values.conversionsResponse).toBeNull()
        expect(logic.values.conversionsLoading).toBe(false)
        expect(conversionRequests()).toHaveLength(2)
        expect(logic.values.rows[0].posthogConversions).toBeUndefined()
    })
    it('cancels pending conversions when goals are disabled so the search request can finish', async () => {
        const pending = deferred<MarketingAnalyticsSearchQueryResponse>()
        mockedQuery.mockImplementation(async (query) =>
            (query as MarketingAnalyticsSearchQuery).includePostHogConversions ? pending.promise : baseResponse
        )
        logic = searchPerformanceTableLogic({ query, queryKey: 'search-test' })
        logic.mount()
        await waitFor(() => expect(conversionRequests()).toHaveLength(1))
        searchPerformanceTableLogic({ query: { ...query, includePostHogConversions: false }, queryKey: 'search-test' })
        await waitFor(() => expect(logic.values.responseLoading).toBe(false))
        expect(logic.values.rows).toMatchObject(baseResponse.results)
        expect(logic.values.goals).toEqual([])
        expect(logic.values.conversionsLoading).toBe(false)
        pending.resolve(conversionsResponse)
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.conversionsResponse).toBeNull()
    })
})
