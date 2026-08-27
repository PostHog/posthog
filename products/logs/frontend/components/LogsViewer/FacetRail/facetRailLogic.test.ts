import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'
import { FilterLogicalOperator, PropertyFilterType, PropertyOperator, UniversalFiltersGroup } from '~/types'

import { logsViewerFiltersLogic } from '../Filters/logsViewerFiltersLogic'
import { FacetSelection, facetFilterTarget, facetSelection } from './facetFilters'
import { facetRailLogic } from './facetRailLogic'
import { FacetSource } from './facets'

const LEVEL_SOURCE: FacetSource = { type: 'column', column: 'severity_text', logKey: 'severity_level' }
const SERVICE_SOURCE: FacetSource = { type: 'column', column: 'service_name', logKey: 'service_name' }
const NAMESPACE_SOURCE: FacetSource = { type: 'resourceAttribute', key: 'k8s.namespace.name' }

describe('facetRailLogic', () => {
    let filtersLogic: ReturnType<typeof logsViewerFiltersLogic.build>
    let logic: ReturnType<typeof facetRailLogic.build>

    const selectionOf = (source: FacetSource): FacetSelection =>
        facetSelection(filtersLogic.values.filterGroup, facetFilterTarget(source))
    const innerFilterValues = (): unknown[] =>
        (filtersLogic.values.filterGroup.values[0] as UniversalFiltersGroup).values
    const click = async (source: FacetSource, value: string): Promise<void> => {
        await expectLogic(logic, () => logic.actions.toggleFacetValue(source, value)).toFinishAllListeners()
    }

    beforeEach(() => {
        initKeaTests()
        filtersLogic = logsViewerFiltersLogic({ id: 'test' })
        filtersLogic.mount()
        logic = facetRailLogic({ id: 'test' })
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        filtersLogic.unmount()
    })

    describe('facet collapse', () => {
        it('adds a facet to the collapsed set, then removes it on the second toggle', async () => {
            await expectLogic(logic, () => logic.actions.toggleFacetCollapsed('level')).toFinishAllListeners()
            expect(logic.values.collapsedFacets).toContain('level')

            await expectLogic(logic, () => logic.actions.toggleFacetCollapsed('service')).toFinishAllListeners()
            expect(logic.values.collapsedFacets).toEqual(expect.arrayContaining(['level', 'service']))

            await expectLogic(logic, () => logic.actions.toggleFacetCollapsed('level')).toFinishAllListeners()
            expect(logic.values.collapsedFacets).not.toContain('level')
            expect(logic.values.collapsedFacets).toContain('service')
        })
    })

    // Every facet keeps both polarities in the filterGroup, so one suite covers all three kinds.
    describe.each<[string, FacetSource]>([
        ['level', LEVEL_SOURCE],
        ['service', SERVICE_SOURCE],
        ['namespace', NAMESPACE_SOURCE],
    ])('%s facet cycling', (_, source) => {
        it('cycles a value unchecked → included → excluded → cleared in the filterGroup', async () => {
            await click(source, 'a')
            expect(selectionOf(source)).toEqual({ included: ['a'], excluded: [] })

            await click(source, 'a')
            expect(selectionOf(source)).toEqual({ included: [], excluded: ['a'] })

            await click(source, 'a')
            expect(selectionOf(source)).toEqual({ included: [], excluded: [] })
            // both filters are dropped from the group entirely, not left empty
            expect(innerFilterValues()).toEqual([])
        })

        it('holds one value included while another is excluded', async () => {
            await click(source, 'a')
            await click(source, 'b')
            expect(selectionOf(source)).toEqual({ included: ['a', 'b'], excluded: [] })

            await click(source, 'a')
            expect(selectionOf(source)).toEqual({ included: ['b'], excluded: ['a'] })
        })
    })

    describe('shared filter state', () => {
        it('keeps each facet under its own key', async () => {
            await click(LEVEL_SOURCE, 'error')
            await click(LEVEL_SOURCE, 'error')
            await click(SERVICE_SOURCE, 'api')
            await click(NAMESPACE_SOURCE, 'argocd')

            expect(selectionOf(LEVEL_SOURCE)).toEqual({ included: [], excluded: ['error'] })
            expect(selectionOf(SERVICE_SOURCE)).toEqual({ included: ['api'], excluded: [] })
            expect(selectionOf(NAMESPACE_SOURCE)).toEqual({ included: ['argocd'], excluded: [] })
        })

        it('toggles relative to a selection the filter bar already holds', async () => {
            // A filter the user typed into the chips bar (or an `=` they edited an exclusion chip into)
            // is the same state the rail reads, so the next click cycles it on rather than ANDing a
            // second, contradictory filter under the same key onto the query.
            filtersLogic.actions.setFilterGroup(
                {
                    type: FilterLogicalOperator.And,
                    values: [
                        {
                            type: FilterLogicalOperator.And,
                            values: [
                                {
                                    key: 'service_name',
                                    type: PropertyFilterType.Log,
                                    operator: PropertyOperator.Exact,
                                    value: ['api'],
                                },
                            ],
                        } as UniversalFiltersGroup,
                    ],
                },
                false
            )
            await expectLogic(filtersLogic).toFinishAllListeners()
            expect(selectionOf(SERVICE_SOURCE)).toEqual({ included: ['api'], excluded: [] })

            await click(SERVICE_SOURCE, 'api')
            expect(selectionOf(SERVICE_SOURCE)).toEqual({ included: [], excluded: ['api'] })
            expect(innerFilterValues()).toEqual([
                { key: 'service_name', type: PropertyFilterType.Log, operator: PropertyOperator.IsNot, value: ['api'] },
            ])
        })
    })
})
