import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'
import { UniversalFiltersGroup } from '~/types'

import { tracingFiltersLogic } from '../../tracingFiltersLogic'
import { facetRailLogic } from './facetRailLogic'
import { FacetSelection, FacetSource, FilterGroupFacetSource, facetFilterSelection } from './facets'

const SERVICE_SOURCE: FacetSource = { type: 'column', column: 'service_name' }
const STATUS_SOURCE: FilterGroupFacetSource = { type: 'column', column: 'status_code' }
const NAMESPACE_SOURCE: FilterGroupFacetSource = { type: 'resourceAttribute', key: 'k8s.namespace.name' }

describe('facetRailLogic', () => {
    let filtersLogic: ReturnType<typeof tracingFiltersLogic.build>
    let logic: ReturnType<typeof facetRailLogic.build>

    beforeEach(() => {
        initKeaTests()
        filtersLogic = tracingFiltersLogic({ id: 'test' })
        filtersLogic.mount()
        logic = facetRailLogic({ id: 'test' })
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        filtersLogic.unmount()
    })

    describe('service toggling', () => {
        it('routes to the dedicated serviceNames field, never the filterGroup', async () => {
            await expectLogic(logic, () => logic.actions.toggleFacetValue(SERVICE_SOURCE, 'api')).toFinishAllListeners()
            expect(filtersLogic.values.serviceNames).toEqual(['api'])
            // The span queries read serviceNames — a filterGroup entry would silently not filter.
            expect((filtersLogic.values.filterGroup.values[0] as UniversalFiltersGroup).values).toEqual([])

            await expectLogic(logic, () => logic.actions.toggleFacetValue(SERVICE_SOURCE, 'api')).toFinishAllListeners()
            expect(filtersLogic.values.serviceNames).toEqual([])
        })

        it('toggles relative to services already selected outside the rail', async () => {
            filtersLogic.actions.setServiceNames(['worker'])

            await expectLogic(logic, () => logic.actions.toggleFacetValue(SERVICE_SOURCE, 'api')).toFinishAllListeners()
            expect(filtersLogic.values.serviceNames).toEqual(['worker', 'api'])
        })
    })

    describe.each<[string, FilterGroupFacetSource]>([
        ['status column facet', STATUS_SOURCE],
        ['resource-attribute facet', NAMESPACE_SOURCE],
    ])('%s cycling', (_, source) => {
        const read = (): FacetSelection => facetFilterSelection(filtersLogic.values.filterGroup, source)
        const click = async (value: string): Promise<void> => {
            await expectLogic(logic, () => logic.actions.toggleFacetValue(source, value)).toFinishAllListeners()
        }

        it('cycles a value included → excluded → cleared through the shared filters logic', async () => {
            await click('a')
            expect(read()).toEqual({ included: ['a'], excluded: [] })

            await click('a')
            expect(read()).toEqual({ included: [], excluded: ['a'] })

            await click('a')
            expect(read()).toEqual({ included: [], excluded: [] })
            expect((filtersLogic.values.filterGroup.values[0] as UniversalFiltersGroup).values).toEqual([])
        })

        it('holds one value included while another is excluded', async () => {
            await click('a')
            await click('b')
            expect(read()).toEqual({ included: ['a', 'b'], excluded: [] })

            await click('a')
            expect(read()).toEqual({ included: ['b'], excluded: ['a'] })
        })
    })

    describe('facet collapse', () => {
        it('adds a facet to the collapsed set, then removes it on the second toggle', () => {
            logic.actions.toggleFacetCollapsed('service')
            expect(logic.values.collapsedFacets).toContain('service')

            logic.actions.toggleFacetCollapsed('status')
            expect(logic.values.collapsedFacets).toEqual(expect.arrayContaining(['service', 'status']))

            logic.actions.toggleFacetCollapsed('service')
            expect(logic.values.collapsedFacets).not.toContain('service')
            expect(logic.values.collapsedFacets).toContain('status')
        })
    })
})
