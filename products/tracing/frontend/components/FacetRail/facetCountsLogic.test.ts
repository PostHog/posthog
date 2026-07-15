import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import {
    tracingSpansAttributeBreakdownCreate,
    tracingSpansAttributesRetrieve,
} from 'products/tracing/frontend/generated/api'
import type { _TracingAttributeBreakdownRowApi } from 'products/tracing/frontend/generated/api.schemas'

import { facetCountsLogic } from './facetCountsLogic'

jest.mock('products/tracing/frontend/generated/api', () => ({
    __esModule: true,
    tracingSpansAttributeBreakdownCreate: jest.fn(),
    tracingSpansAttributesRetrieve: jest.fn(),
}))

const mockBreakdown = tracingSpansAttributeBreakdownCreate as jest.MockedFunction<
    typeof tracingSpansAttributeBreakdownCreate
>
const mockAttributes = tracingSpansAttributesRetrieve as jest.MockedFunction<typeof tracingSpansAttributesRetrieve>

const ID = 'test-viewer'

function row(value: string, count: number): _TracingAttributeBreakdownRowApi {
    return { value, count, error_count: 0, p50_duration_nano: 0, p95_duration_nano: 0 }
}

describe('facetCountsLogic', () => {
    let logic: ReturnType<typeof facetCountsLogic.build>

    beforeEach(() => {
        initKeaTests()
        jest.clearAllMocks()
        // No resource-attribute keys present, so only the column facets (service, status) are visible.
        mockAttributes.mockResolvedValue({ results: [], count: 0 })
        mockBreakdown.mockResolvedValue({ results: [row('api', 10)], compare: null })
        logic = facetCountsLogic({ id: ID })
    })

    afterEach(() => {
        logic.unmount()
    })

    it('a facet search refetches only that facet, passing facetSearch to the endpoint', async () => {
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadFacetValuesSuccess'])
        mockBreakdown.mockClear()

        logic.actions.setFacetSearch('service', 'kaf')
        await expectLogic(logic).toDispatchActions(['loadFacetValuesForKey', 'loadFacetValuesForKeySuccess'])

        expect(mockBreakdown).toHaveBeenCalledTimes(1)
        expect(mockBreakdown).toHaveBeenCalledWith(
            expect.any(String),
            expect.objectContaining({
                query: expect.objectContaining({ breakdownKey: 'service_name', facetSearch: 'kaf' }),
            })
        )
    })

    it('a failed facet is marked errored without wiping the others, and recovers on the next fetch', async () => {
        // One broken breakdown must show per-facet (erroredFacetKeys), not blank the whole rail.
        mockBreakdown.mockImplementation((_, request) =>
            request.query.breakdownKey === 'status_code'
                ? Promise.reject(new Error('breakdown failed'))
                : Promise.resolve({ results: [row('api', 10)], compare: null })
        )
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadFacetValuesSuccess'])

        expect(logic.values.erroredFacetKeys).toEqual(['status'])
        expect(logic.values.facetValues['service']).toEqual([row('api', 10)])
        expect(logic.values.facetValues['status']).toBeUndefined()

        mockBreakdown.mockResolvedValue({ results: [row('2', 3)], compare: null })
        logic.actions.loadFacetValues(null)
        await expectLogic(logic).toDispatchActions(['loadFacetValuesSuccess'])

        expect(logic.values.erroredFacetKeys).toEqual([])
        expect(logic.values.facetValues['status']).toEqual([row('2', 3)])
    })

    it('a full reload that raced a facet search does not overwrite the narrowed results', async () => {
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadFacetValuesSuccess'])

        // The reload's service request (no facetSearch) hangs until released; the search request
        // (facetSearch set) and every other facet resolve immediately.
        let releaseStaleReload: (rows: _TracingAttributeBreakdownRowApi[]) => void = () => {}
        let staleReloadRequested: () => void = () => {}
        const staleReloadIssued = new Promise<void>((resolve) => (staleReloadRequested = resolve))
        mockBreakdown.mockImplementation((_, request) => {
            if (request.query.breakdownKey === 'service_name' && !request.query.facetSearch) {
                staleReloadRequested()
                return new Promise((resolve) => {
                    releaseStaleReload = (rows) => resolve({ results: rows, compare: null })
                })
            }
            if (request.query.facetSearch === 'kaf') {
                return Promise.resolve({ results: [row('kafka-consumer', 2)], compare: null })
            }
            return Promise.resolve({ results: [row('api', 10)], compare: null })
        })

        logic.actions.loadFacetValues(null)
        await staleReloadIssued

        logic.actions.setFacetSearch('service', 'kaf')
        await expectLogic(logic).toDispatchActions(['loadFacetValuesForKeySuccess'])
        expect(logic.values.facetValues['service']).toEqual([row('kafka-consumer', 2)])

        releaseStaleReload([row('api', 10), row('worker', 5)])
        await expectLogic(logic).toDispatchActions(['loadFacetValuesSuccess'])

        expect(logic.values.facetValues['service']).toEqual([row('kafka-consumer', 2)])
        expect(logic.values.erroredFacetKeys).toEqual([])
    })
})
