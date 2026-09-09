import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'

import {
    logsAttributesRetrieve,
    logsFacetValuesBatchCreate,
    logsFacetValuesCreate,
} from 'products/logs/frontend/generated/api'
import { userFacetSettingsRetrieve } from 'products/platform_features/frontend/generated/api'

import { logsViewerFiltersLogic } from '../Filters/logsViewerFiltersLogic'
import { facetPresenceLogic } from './facetPresenceLogic'
import { facetRailLogic } from './facetRailLogic'
import { FACETS, FacetConfig, MAX_KEYS_PER_BATCH, buildCustomFacet } from './facets'
import { facetValuesBatchLogic } from './facetValuesBatchLogic'
import { facetValuesLogic } from './facetValuesLogic'

jest.mock('products/logs/frontend/generated/api', () => ({
    __esModule: true,
    logsFacetValuesCreate: jest.fn(),
    logsFacetValuesBatchCreate: jest.fn(),
    logsAttributesRetrieve: jest.fn(),
}))

jest.mock('products/platform_features/frontend/generated/api', () => ({
    __esModule: true,
    userFacetSettingsRetrieve: jest.fn(),
    userFacetSettingsPartialUpdate: jest.fn(),
}))

const mockFacetValues = logsFacetValuesCreate as jest.MockedFunction<typeof logsFacetValuesCreate>
const mockBatch = logsFacetValuesBatchCreate as jest.MockedFunction<typeof logsFacetValuesBatchCreate>
const mockAttributes = logsAttributesRetrieve as jest.MockedFunction<typeof logsAttributesRetrieve>
const mockUserFacetSettings = userFacetSettingsRetrieve as jest.MockedFunction<typeof userFacetSettingsRetrieve>

const ID = 'test-viewer'

const facetConfig = (key: string): FacetConfig => FACETS.find((f) => f.key === key)!
const LEVEL = facetConfig('level')
const SERVICE = facetConfig('service')
const NAMESPACE = facetConfig('namespace')
const IOSTREAM = buildCustomFacet('log.iostream', 'attribute')

const NAMESPACE_KEY = 'k8s.namespace.name'

describe('facetValuesLogic', () => {
    let filtersLogic: ReturnType<typeof logsViewerFiltersLogic.build>
    let railLogic: ReturnType<typeof facetRailLogic.build>
    let presenceLogic: ReturnType<typeof facetPresenceLogic.build>
    let batchLogic: ReturnType<typeof facetValuesBatchLogic.build>
    const mounted: ReturnType<typeof facetValuesLogic.build>[] = []

    const mountFacet = (facet: FacetConfig): ReturnType<typeof facetValuesLogic.build> => {
        const logic = facetValuesLogic({ id: ID, facet })
        logic.mount()
        mounted.push(logic)
        return logic
    }

    // The batch answers for the facets facetPresenceLogic says are visible, so mount that rather
    // than the facets alone — a facet the coordinator can't see falls back to its own fetch, which
    // would quietly pass a test the real rail would fail.
    const mountRail = (): void => {
        presenceLogic = facetPresenceLogic({ id: ID })
        presenceLogic.mount()
        batchLogic = facetValuesBatchLogic({ id: ID })
        batchLogic.mount()
    }

    const batchedQuery = (): Record<string, any> => mockBatch.mock.calls[0][1].query as Record<string, any>

    beforeEach(() => {
        initKeaTests()
        jest.clearAllMocks()
        // Custom facets are gated, and the batch has to cover them, so turn the gate on.
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.CUSTOM_FACET_PINNING]: true })
        mockUserFacetSettings.mockResolvedValue({
            custom_facets: [{ key: 'log.iostream', source_type: 'attribute' }],
        })
        mockAttributes.mockResolvedValue({
            results: [{ name: NAMESPACE_KEY, propertyFilterType: 'log_resource_attribute', matchedOn: 'key' }],
            count: 1,
        } as any)
        mockFacetValues.mockResolvedValue({ results: [{ value: 'api', count: 10 }] })
        mockBatch.mockResolvedValue({
            results: {
                facetResourceAttributes: [{ key: NAMESPACE_KEY, values: [{ value: 'argo', count: 4 }] }],
                facetAttributes: [{ key: 'log.iostream', values: [{ value: 'stdout', count: 7 }] }],
            },
        })
        filtersLogic = logsViewerFiltersLogic({ id: ID })
        filtersLogic.mount()
        railLogic = facetRailLogic({ id: ID })
        railLogic.mount()
    })

    afterEach(() => {
        mounted.splice(0).forEach((logic) => logic.unmount())
        batchLogic?.unmount()
        presenceLogic?.unmount()
        railLogic.unmount()
        filtersLogic.unmount()
    })

    // The rail's whole point: N attribute facets cost one query, not N. Column facets read a
    // different table with a different WHERE, so they stay on their own request.
    it('answers every attribute facet from one batched request, and column facets separately', async () => {
        mountRail()
        const namespace = mountFacet(NAMESPACE)
        const iostream = mountFacet(IOSTREAM)
        mountFacet(SERVICE)

        await expectLogic(mounted[2]).toDispatchActions(['loadFacetValuesSuccess'])
        await expectLogic(batchLogic).toDispatchActions(['loadBatchSuccess'])

        expect(mockBatch).toHaveBeenCalledTimes(1)
        expect(batchedQuery()).toMatchObject({
            facetResourceAttributes: [NAMESPACE_KEY],
            facetAttributes: ['log.iostream'],
        })
        // Each attribute facet reads its own slice, keyed by type and key.
        expect(namespace.values.displayedValues).toEqual([{ value: 'argo', count: 4 }])
        expect(iostream.values.displayedValues).toEqual([{ value: 'stdout', count: 7 }])
        // Only the column facet went the single-facet route.
        expect(mockFacetValues).toHaveBeenCalledTimes(1)
        expect(mockFacetValues).toHaveBeenCalledWith(
            expect.any(String),
            expect.objectContaining({ query: expect.objectContaining({ facetField: 'service_name' }) })
        )
    })

    // The batch runs one WHERE for everyone, so it can't exclude a facet's own filter. A facet
    // carrying one has to leave the batch or its counts would collapse to the value just picked.
    it('drops a facet with a filter on its own key out of the batch and onto its own request', async () => {
        mountRail()
        const namespace = mountFacet(NAMESPACE)
        await expectLogic(batchLogic).toDispatchActions(['loadBatchSuccess'])
        expect(namespace.values.isBatched).toBe(true)
        mockBatch.mockClear()
        mockFacetValues.mockClear()

        railLogic.actions.toggleFacetValue(NAMESPACE.source, 'argo')
        await expectLogic(namespace).toDispatchActions(['loadFacetValuesSuccess'])

        expect(namespace.values.isBatched).toBe(false)
        expect(mockFacetValues).toHaveBeenCalledWith(
            expect.any(String),
            expect.objectContaining({
                query: expect.objectContaining({ facetResourceAttribute: NAMESPACE_KEY }),
            })
        )
        // And the batch no longer asks for it, since it can't answer for it.
        expect(mockBatch.mock.calls.every((call) => !(call[1].query.facetResourceAttributes ?? []).length)).toBe(true)
    })

    // Values stay on screen while the facet fetches for itself, rather than blanking to a skeleton.
    it('keeps showing the batch values while a facet that just left the batch reloads', async () => {
        mountRail()
        const namespace = mountFacet(NAMESPACE)
        await expectLogic(batchLogic).toDispatchActions(['loadBatchSuccess'])

        railLogic.actions.toggleFacetValue(NAMESPACE.source, 'argo')
        expect(namespace.values.isBatched).toBe(false)
        expect(namespace.values.displayedValues).toEqual([{ value: 'argo', count: 4 }])
    })

    // A searching facet stays in the batch's demand set, so clearing the search reads the slice
    // that's already there instead of costing another round trip.
    it('moves a searched facet onto its own request, and back with no refetch when cleared', async () => {
        mountRail()
        const namespace = mountFacet(NAMESPACE)
        await expectLogic(batchLogic).toDispatchActions(['loadBatchSuccess'])
        mockBatch.mockClear()
        mockFacetValues.mockClear()

        namespace.actions.setFacetSearch('arg')
        await expectLogic(namespace).toDispatchActions(['loadFacetValuesSuccess'])
        expect(namespace.values.isBatched).toBe(false)
        expect(mockFacetValues).toHaveBeenCalledWith(
            expect.any(String),
            expect.objectContaining({
                query: expect.objectContaining({ facetResourceAttribute: NAMESPACE_KEY, facetSearch: 'arg' }),
            })
        )

        mockFacetValues.mockClear()
        namespace.actions.setFacetSearch('')
        await expectLogic(namespace).toNotHaveDispatchedActions(['loadFacetValues'])
        expect(namespace.values.isBatched).toBe(true)
        expect(namespace.values.displayedValues).toEqual([{ value: 'argo', count: 4 }])
        expect(mockFacetValues).not.toHaveBeenCalled()
        expect(mockBatch).not.toHaveBeenCalled()
    })

    // A search with no matches must show "no values", not fall back to the batch's unfiltered list.
    it('shows an empty result from its own request rather than the batch slice', async () => {
        mountRail()
        const namespace = mountFacet(NAMESPACE)
        await expectLogic(batchLogic).toDispatchActions(['loadBatchSuccess'])

        mockFacetValues.mockResolvedValue({ results: [] })
        namespace.actions.setFacetSearch('no-such-value')
        await expectLogic(namespace).toDispatchActions(['loadFacetValuesSuccess'])

        expect(namespace.values.displayedValues).toEqual([])
    })

    it('leaves a collapsed facet out of the batch until it is expanded', async () => {
        railLogic.actions.toggleFacetCollapsed(NAMESPACE.key)
        mountRail()
        mountFacet(NAMESPACE)
        const iostream = mountFacet(IOSTREAM)

        await expectLogic(batchLogic).toDispatchActions(['loadBatchSuccess'])
        expect(batchedQuery().facetResourceAttributes).toEqual([])
        expect(iostream.values.displayedValues).toEqual([{ value: 'stdout', count: 7 }])

        mockBatch.mockClear()
        railLogic.actions.toggleFacetCollapsed(NAMESPACE.key)
        await expectLogic(batchLogic).toDispatchActions(['loadBatchSuccess'])
        expect(mockBatch).toHaveBeenCalledTimes(1)

        // Collapsing and expanding again with nothing else changed has nothing to fetch.
        mockBatch.mockClear()
        railLogic.actions.toggleFacetCollapsed(NAMESPACE.key)
        railLogic.actions.toggleFacetCollapsed(NAMESPACE.key)
        await expectLogic(batchLogic).toNotHaveDispatchedActions(['loadBatch'])
        expect(mockBatch).not.toHaveBeenCalled()
    })

    // Every batched facet waits on one request, so a failure that left them "loading" would hang
    // the whole rail on a skeleton until the user happened to change a filter.
    it('shows the empty state rather than an endless skeleton when the batch fails', async () => {
        mockBatch.mockRejectedValue(new Error('boom'))
        mountRail()
        const namespace = mountFacet(NAMESPACE)

        await expectLogic(batchLogic).toDispatchActions(['loadBatchFailure'])

        expect(namespace.values.valuesLoading).toBe(false)
        expect(namespace.values.displayedValues).toEqual([])
    })

    // A user can pin more custom facets than the endpoint accepts in one request. Truncating would
    // leave the overflow with no values; sending them all would have every request rejected.
    it('splits a demand set larger than the endpoint cap across requests', async () => {
        const keys = Array.from({ length: MAX_KEYS_PER_BATCH + 5 }, (_, i) => `attr.${i}`)
        mockUserFacetSettings.mockResolvedValue({
            custom_facets: keys.map((key) => ({ key, source_type: 'attribute' })),
        })
        mountRail()
        mountFacet(buildCustomFacet(keys[keys.length - 1], 'attribute'))

        await expectLogic(batchLogic).toDispatchActions(['loadBatchSuccess'])

        expect(mockBatch).toHaveBeenCalledTimes(2)
        const requested = mockBatch.mock.calls.flatMap((call) => call[1].query.facetAttributes ?? [])
        expect(requested).toEqual(expect.arrayContaining(keys))
        mockBatch.mock.calls.forEach((call) => {
            const query = call[1].query
            expect(
                (query.facetResourceAttributes ?? []).length + (query.facetAttributes ?? []).length
            ).toBeLessThanOrEqual(MAX_KEYS_PER_BATCH)
        })
    })

    // The batch slice is unfiltered, so showing it under an active search would present the wrong
    // values as if they matched.
    it('does not fall back to the batch slice when a searched fetch fails', async () => {
        mountRail()
        const namespace = mountFacet(NAMESPACE)
        await expectLogic(batchLogic).toDispatchActions(['loadBatchSuccess'])

        mockFacetValues.mockRejectedValue(new Error('boom'))
        namespace.actions.setFacetSearch('arg')
        await expectLogic(namespace).toDispatchActions(['loadFacetValuesFailure'])

        expect(namespace.values.displayedValues).toEqual([])
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
        expect(selectedLogic.values.valuesLoading).toBe(false)
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
        ['a resource-attribute facet', NAMESPACE, { facetResourceAttribute: NAMESPACE_KEY }],
        ['a custom plain-attribute facet', IOSTREAM, { facetAttribute: 'log.iostream' }],
    ])('%s requests the matching facet* body field', async (_, facet, expectedFields) => {
        // A search takes any facet off the batch, which is what puts every source type through the
        // single-facet path where the body field is chosen.
        const logic = mountFacet(facet)
        logic.actions.setFacetSearch('any')
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

    // Most of the rail reads the batch, so a re-run that only refetched the single-facet path would
    // leave the values a user asked to refresh exactly as they were.
    it('a manual refresh refetches the batch too', async () => {
        mountRail()
        mountFacet(NAMESPACE)
        await expectLogic(batchLogic).toDispatchActions(['loadBatchSuccess'])
        mockBatch.mockClear()

        filtersLogic.actions.bumpFacetRefresh()
        await expectLogic(batchLogic).toDispatchActions(['loadBatch', 'loadBatchSuccess'])
        expect(mockBatch).toHaveBeenCalledTimes(1)
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
