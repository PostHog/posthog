import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'
import { FilterLogicalOperator, PropertyFilterType, PropertyOperator, UniversalFiltersGroup } from '~/types'

import { tracingSpansAttributeBreakdownCreate } from 'products/tracing/frontend/generated/api'
import type { _TracingAttributeBreakdownRowApi } from 'products/tracing/frontend/generated/api.schemas'
import { tracingFiltersLogic } from 'products/tracing/frontend/tracingFiltersLogic'

import { facetRailLogic } from './facetRailLogic'
import { FACETS, FacetConfig } from './facets'
import { facetValuesLogic } from './facetValuesLogic'

jest.mock('products/tracing/frontend/generated/api', () => ({
    __esModule: true,
    tracingSpansAttributeBreakdownCreate: jest.fn(),
    tracingSpansAttributesRetrieve: jest.fn(),
}))

const mockBreakdown = tracingSpansAttributeBreakdownCreate as jest.MockedFunction<
    typeof tracingSpansAttributeBreakdownCreate
>

const ID = 'test-viewer'

const facetConfig = (key: string): FacetConfig => FACETS.find((f) => f.key === key)!
const SERVICE = facetConfig('service')
const STATUS = facetConfig('status')

function row(value: string, count: number): _TracingAttributeBreakdownRowApi {
    return { value, count, error_count: 0, p50_duration_nano: 0, p95_duration_nano: 0 }
}

const statusFilterGroup: UniversalFiltersGroup = {
    type: FilterLogicalOperator.And,
    values: [
        {
            type: FilterLogicalOperator.And,
            values: [
                {
                    type: PropertyFilterType.Span,
                    key: 'status_code',
                    operator: PropertyOperator.Exact,
                    value: ['2'],
                },
            ] as UniversalFiltersGroup['values'],
        },
    ],
}

describe('facetValuesLogic', () => {
    let filtersLogic: ReturnType<typeof tracingFiltersLogic.build>
    let railLogic: ReturnType<typeof facetRailLogic.build>
    const mounted: ReturnType<typeof facetValuesLogic.build>[] = []

    const mountFacet = (facet: FacetConfig): ReturnType<typeof facetValuesLogic.build> => {
        const logic = facetValuesLogic({ id: ID, facet })
        logic.mount()
        mounted.push(logic)
        return logic
    }

    beforeEach(() => {
        initKeaTests()
        jest.clearAllMocks()
        mockBreakdown.mockResolvedValue({ results: [row('api', 10)], compare: null })
        filtersLogic = tracingFiltersLogic({ id: ID })
        filtersLogic.mount()
        railLogic = facetRailLogic({ id: ID })
        railLogic.mount()
    })

    afterEach(() => {
        mounted.splice(0).forEach((logic) => logic.unmount())
        railLogic.unmount()
        filtersLogic.unmount()
    })

    // Selecting a value re-scopes the *other* facets: excludeBreakdownFilter strips a facet's own
    // filter from its own breakdown, so refetching it burns a request on an unchanged response.
    it.each<[string, FacetConfig, FacetConfig, () => void]>([
        ['a service selection', SERVICE, STATUS, () => filtersLogic.actions.setServiceNames(['api'])],
        ['a status selection', STATUS, SERVICE, () => filtersLogic.actions.setFilterGroup(statusFilterGroup)],
    ])('%s reloads the other facets but not itself', async (_, selected, other, select) => {
        const selectedLogic = mountFacet(selected)
        const otherLogic = mountFacet(other)
        await expectLogic(selectedLogic).toDispatchActions(['loadFacetValuesSuccess'])
        await expectLogic(otherLogic).toDispatchActions(['loadFacetValuesSuccess'])
        mockBreakdown.mockClear()

        select()
        await expectLogic(otherLogic).toDispatchActions(['loadFacetValues', 'loadFacetValuesSuccess'])

        expect(mockBreakdown).toHaveBeenCalledTimes(1)
        expect(selectedLogic.values.facetValuesLoading).toBe(false)
    })

    it('a type-ahead search refetches this facet with the search term', async () => {
        const logic = mountFacet(SERVICE)
        await expectLogic(logic).toDispatchActions(['loadFacetValuesSuccess'])
        mockBreakdown.mockClear()

        logic.actions.setFacetSearch('kaf')
        await expectLogic(logic).toDispatchActions(['loadFacetValuesSuccess'])

        expect(mockBreakdown).toHaveBeenCalledTimes(1)
        expect(mockBreakdown).toHaveBeenCalledWith(
            expect.any(String),
            expect.objectContaining({
                query: expect.objectContaining({ breakdownKey: 'service_name', facetSearch: 'kaf' }),
            })
        )
    })

    it('a failed breakdown shows in place and clears on the next fetch', async () => {
        // One broken breakdown must show on its own facet, not blank the rail.
        mockBreakdown.mockRejectedValueOnce(new Error('breakdown failed'))
        const logic = mountFacet(SERVICE)
        await expectLogic(logic).toDispatchActions(['loadFacetValuesFailure'])
        expect(logic.values.fetchFailed).toBe(true)

        logic.actions.setFacetSearch('api')
        await expectLogic(logic).toDispatchActions(['loadFacetValuesSuccess'])
        expect(logic.values.fetchFailed).toBe(false)
        expect(logic.values.facetValues).toEqual([row('api', 10)])
    })

    it('a collapsed facet defers its fetch until it is expanded, then only if the scope moved', async () => {
        railLogic.actions.toggleFacetCollapsed(SERVICE.key)
        const logic = mountFacet(SERVICE)
        const other = mountFacet(STATUS)
        await expectLogic(other).toDispatchActions(['loadFacetValuesSuccess'])
        expect(mockBreakdown).toHaveBeenCalledTimes(1)

        filtersLogic.actions.setDateRange({ date_from: '-7d' })
        await expectLogic(other).toDispatchActions(['loadFacetValuesSuccess'])
        expect(logic.values.facetValues).toEqual([])

        mockBreakdown.mockClear()
        railLogic.actions.toggleFacetCollapsed(SERVICE.key)
        await expectLogic(logic).toDispatchActions(['loadFacetValuesSuccess'])
        expect(mockBreakdown).toHaveBeenCalledTimes(1)

        // Collapsing and expanding again with nothing else changed has nothing to fetch.
        mockBreakdown.mockClear()
        railLogic.actions.toggleFacetCollapsed(SERVICE.key)
        railLogic.actions.toggleFacetCollapsed(SERVICE.key)
        await expectLogic(logic).toNotHaveDispatchedActions(['loadFacetValues'])
        expect(mockBreakdown).not.toHaveBeenCalled()
    })

    it('collapsing while a fetch is still debouncing drops it, and expanding fetches again', async () => {
        // The request is debounced, so a facet collapsed within that window would otherwise still
        // hit the endpoint — and, having recorded the signature, look fresh enough to skip the
        // refetch on expand, leaving the stale list it was showing before.
        const logic = mountFacet(SERVICE)
        await expectLogic(logic).toDispatchActions(['loadFacetValuesSuccess'])
        mockBreakdown.mockClear()

        filtersLogic.actions.setDateRange({ date_from: '-7d' })
        await expectLogic(logic).toDispatchActions(['loadFacetValues'])
        railLogic.actions.toggleFacetCollapsed(SERVICE.key)
        await expectLogic(logic).toDispatchActions(['loadFacetValuesSuccess'])
        expect(mockBreakdown).not.toHaveBeenCalled()

        railLogic.actions.toggleFacetCollapsed(SERVICE.key)
        await expectLogic(logic).toDispatchActions(['loadFacetValuesSuccess'])
        expect(mockBreakdown).toHaveBeenCalledTimes(1)
    })
})
