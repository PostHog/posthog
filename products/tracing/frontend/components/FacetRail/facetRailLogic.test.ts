import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'
import { UniversalFiltersGroup } from '~/types'

import { tracingFiltersLogic } from '../../tracingFiltersLogic'
import { facetRailLogic } from './facetRailLogic'
import { FacetSource, FilterGroupFacetSource, facetFilterValues } from './facets'

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
    ])('%s toggling', (_, source) => {
        const read = (): string[] => facetFilterValues(filtersLogic.values.filterGroup, source)

        it('adds, accumulates (OR), and removes values as a property filter in the group', async () => {
            await expectLogic(logic, () => logic.actions.toggleFacetValue(source, 'a')).toFinishAllListeners()
            expect(read()).toEqual(['a'])

            await expectLogic(logic, () => logic.actions.toggleFacetValue(source, 'b')).toFinishAllListeners()
            expect(read()).toEqual(['a', 'b'])

            await expectLogic(logic, () => logic.actions.toggleFacetValue(source, 'a')).toFinishAllListeners()
            expect(read()).toEqual(['b'])
        })

        it('removing the last value drops the filter from the group entirely', async () => {
            await expectLogic(logic, () => logic.actions.toggleFacetValue(source, 'a')).toFinishAllListeners()
            await expectLogic(logic, () => logic.actions.toggleFacetValue(source, 'a')).toFinishAllListeners()
            expect(read()).toEqual([])
            expect((filtersLogic.values.filterGroup.values[0] as UniversalFiltersGroup).values).toEqual([])
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
