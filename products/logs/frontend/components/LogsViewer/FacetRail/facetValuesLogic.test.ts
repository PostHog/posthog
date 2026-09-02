import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { logsAttributesRetrieve, logsFacetValuesCreate } from 'products/logs/frontend/generated/api'

import { logsViewerFiltersLogic } from '../Filters/logsViewerFiltersLogic'
import { facetRailLogic } from './facetRailLogic'
import { FACETS, FacetConfig, buildCustomFacet } from './facets'
import { facetValuesLogic } from './facetValuesLogic'

jest.mock('products/logs/frontend/generated/api', () => ({
    __esModule: true,
    logsFacetValuesCreate: jest.fn(),
    logsAttributesRetrieve: jest.fn(),
}))

const mockFacetValues = logsFacetValuesCreate as jest.MockedFunction<typeof logsFacetValuesCreate>
const mockAttributes = logsAttributesRetrieve as jest.MockedFunction<typeof logsAttributesRetrieve>

const ID = 'test-viewer'

const facetConfig = (key: string): FacetConfig => FACETS.find((f) => f.key === key)!
const LEVEL = facetConfig('level')
const SERVICE = facetConfig('service')

describe('facetValuesLogic', () => {
    let filtersLogic: ReturnType<typeof logsViewerFiltersLogic.build>
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
        mockAttributes.mockResolvedValue({ results: [], count: 0 })
        mockFacetValues.mockResolvedValue({ results: [{ value: 'api', count: 10 }] })
        filtersLogic = logsViewerFiltersLogic({ id: ID })
        filtersLogic.mount()
        railLogic = facetRailLogic({ id: ID })
        railLogic.mount()
    })

    afterEach(() => {
        mounted.splice(0).forEach((logic) => logic.unmount())
        railLogic.unmount()
        filtersLogic.unmount()
    })

    // Selecting a value re-scopes the *other* facets: the backend strips a facet's own filter from
    // its own query, so refetching it burns a request on a response that cannot have changed.
    it.each<[string, FacetConfig, FacetConfig, () => void]>([
        ['a level selection', LEVEL, SERVICE, () => filtersLogic.actions.setFilters({ severityLevels: ['error'] })],
        ['a service selection', SERVICE, LEVEL, () => filtersLogic.actions.setFilters({ serviceNames: ['api'] })],
    ])('%s reloads the other facets but not itself', async (_, selected, other, select) => {
        const selectedLogic = mountFacet(selected)
        const otherLogic = mountFacet(other)
        await expectLogic(selectedLogic).toDispatchActions(['loadFacetValuesSuccess'])
        await expectLogic(otherLogic).toDispatchActions(['loadFacetValuesSuccess'])
        mockFacetValues.mockClear()

        select()
        await expectLogic(otherLogic).toDispatchActions(['loadFacetValues', 'loadFacetValuesSuccess'])

        expect(mockFacetValues).toHaveBeenCalledTimes(1)
        expect(selectedLogic.values.facetValuesLoading).toBe(false)
    })

    it('a type-ahead search refetches this facet with the search term', async () => {
        const logic = mountFacet(SERVICE)
        await expectLogic(logic).toDispatchActions(['loadFacetValuesSuccess'])
        mockFacetValues.mockClear()

        logic.actions.setFacetSearch('kaf')
        await expectLogic(logic).toDispatchActions(['loadFacetValuesSuccess'])

        expect(mockFacetValues).toHaveBeenCalledTimes(1)
        expect(mockFacetValues).toHaveBeenCalledWith(
            expect.any(String),
            expect.objectContaining({
                query: expect.objectContaining({ facetField: 'service_name', facetSearch: 'kaf' }),
            })
        )
    })

    // Each source type must route to its own facet* body field — a binary-to-ternary slip (e.g. a
    // plain attribute silently querying as a resource attribute) would misreport values with no
    // type error, since _LogsFacetValuesBodyApi accepts any of the three.
    it.each<[string, FacetConfig, Record<string, string>]>([
        ['a column facet', SERVICE, { facetField: 'service_name' }],
        ['a resource-attribute facet', facetConfig('namespace'), { facetResourceAttribute: 'k8s.namespace.name' }],
        [
            'a custom plain-attribute facet',
            buildCustomFacet('log.iostream', 'attribute'),
            { facetAttribute: 'log.iostream' },
        ],
    ])('%s requests the matching facet* body field', async (_, facet, expectedFields) => {
        const logic = mountFacet(facet)
        await expectLogic(logic).toDispatchActions(['loadFacetValuesSuccess'])
        expect(mockFacetValues).toHaveBeenCalledWith(
            expect.any(String),
            expect.objectContaining({ query: expect.objectContaining(expectedFields) })
        )
    })

    it('a collapsed facet defers its fetch until it is expanded, then only if the scope moved', async () => {
        railLogic.actions.toggleFacetCollapsed(SERVICE.key)
        const logic = mountFacet(SERVICE)
        const other = mountFacet(LEVEL)
        await expectLogic(other).toDispatchActions(['loadFacetValuesSuccess'])
        expect(mockFacetValues).toHaveBeenCalledTimes(1)

        filtersLogic.actions.setSearchTerm('timeout')
        await expectLogic(other).toDispatchActions(['loadFacetValuesSuccess'])
        expect(logic.values.facetValues).toEqual([])

        mockFacetValues.mockClear()
        railLogic.actions.toggleFacetCollapsed(SERVICE.key)
        await expectLogic(logic).toDispatchActions(['loadFacetValuesSuccess'])
        expect(mockFacetValues).toHaveBeenCalledTimes(1)

        // Collapsing and expanding again with nothing else changed has nothing to fetch.
        mockFacetValues.mockClear()
        railLogic.actions.toggleFacetCollapsed(SERVICE.key)
        railLogic.actions.toggleFacetCollapsed(SERVICE.key)
        await expectLogic(logic).toNotHaveDispatchedActions(['loadFacetValues'])
        expect(mockFacetValues).not.toHaveBeenCalled()
    })

    it('a manual refresh refetches an expanded facet even when the scope is unchanged', async () => {
        const logic = mountFacet(SERVICE)
        await expectLogic(logic).toDispatchActions(['loadFacetValuesSuccess'])
        mockFacetValues.mockClear()

        filtersLogic.actions.bumpFacetRefresh()
        await expectLogic(logic).toDispatchActions(['loadFacetValues', 'loadFacetValuesSuccess'])
        expect(mockFacetValues).toHaveBeenCalledTimes(1)
    })

    it('a manual refresh leaves a collapsed facet unfetched until it is expanded', async () => {
        railLogic.actions.toggleFacetCollapsed(SERVICE.key)
        const logic = mountFacet(SERVICE)
        const other = mountFacet(LEVEL)
        await expectLogic(other).toDispatchActions(['loadFacetValuesSuccess'])
        mockFacetValues.mockClear()

        filtersLogic.actions.bumpFacetRefresh()
        await expectLogic(other).toDispatchActions(['loadFacetValuesSuccess'])
        expect(logic.values.facetValues).toEqual([])

        railLogic.actions.toggleFacetCollapsed(SERVICE.key)
        await expectLogic(logic).toDispatchActions(['loadFacetValuesSuccess'])
        expect(mockFacetValues).toHaveBeenCalledTimes(2)
    })

    it('collapsing while a fetch is still debouncing drops it, and expanding fetches again', async () => {
        // The request is debounced, so a facet collapsed within that window would otherwise still
        // hit the endpoint — and, having recorded the signature, look fresh enough to skip the
        // refetch on expand, leaving the stale list it was showing before.
        const logic = mountFacet(SERVICE)
        await expectLogic(logic).toDispatchActions(['loadFacetValuesSuccess'])
        mockFacetValues.mockClear()

        filtersLogic.actions.setSearchTerm('timeout')
        await expectLogic(logic).toDispatchActions(['loadFacetValues'])
        railLogic.actions.toggleFacetCollapsed(SERVICE.key)
        await expectLogic(logic).toDispatchActions(['loadFacetValuesSuccess'])
        expect(mockFacetValues).not.toHaveBeenCalled()

        railLogic.actions.toggleFacetCollapsed(SERVICE.key)
        await expectLogic(logic).toDispatchActions(['loadFacetValuesSuccess'])
        expect(mockFacetValues).toHaveBeenCalledTimes(1)
    })
})
