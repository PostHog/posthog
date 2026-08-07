import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'
import { UniversalFiltersGroup } from '~/types'

import { logsViewerFiltersLogic } from '../Filters/logsViewerFiltersLogic'
import { facetRailLogic } from './facetRailLogic'
import { FacetSelection, FacetSource, logFilterExclusions, resourceAttributeSelection } from './facets'

const LEVEL_SOURCE: FacetSource = {
    type: 'column',
    column: 'severity_text',
    filterKey: 'severityLevels',
    exclusionKey: 'severity_level',
}
const SERVICE_SOURCE: FacetSource = {
    type: 'column',
    column: 'service_name',
    filterKey: 'serviceNames',
    exclusionKey: 'service_name',
}
const NAMESPACE_SOURCE: FacetSource = { type: 'resourceAttribute', key: 'k8s.namespace.name' }

describe('facetRailLogic', () => {
    let filtersLogic: ReturnType<typeof logsViewerFiltersLogic.build>
    let logic: ReturnType<typeof facetRailLogic.build>

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

    describe('severity level cycling', () => {
        const readExcluded = (): string[] => logFilterExclusions(filtersLogic.values.filterGroup, 'severity_level')
        const click = async (value: string): Promise<void> => {
            await expectLogic(logic, () => logic.actions.toggleFacetValue(LEVEL_SOURCE, value)).toFinishAllListeners()
        }

        it('cycles a level across the two stores: dedicated field, then is_not log filter, then cleared', async () => {
            await click('error')
            expect(filtersLogic.values.severityLevels).toEqual(['error'])
            expect(readExcluded()).toEqual([])

            await click('error')
            expect(filtersLogic.values.severityLevels).toEqual([])
            expect(readExcluded()).toEqual(['error'])

            await click('error')
            expect(filtersLogic.values.severityLevels).toEqual([])
            expect(readExcluded()).toEqual([])
            // the is_not filter is dropped from the group entirely, not left empty
            expect((filtersLogic.values.filterGroup.values[0] as UniversalFiltersGroup).values).toEqual([])
        })

        it('holds one level included while another is excluded', async () => {
            await click('error')
            await click('warn')
            expect(filtersLogic.values.severityLevels).toEqual(['error', 'warn'])

            await click('error')
            expect(filtersLogic.values.severityLevels).toEqual(['warn'])
            expect(readExcluded()).toEqual(['error'])
        })
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

    describe('service name cycling', () => {
        it('cycles a service across the two stores: dedicated field, then is_not log filter, then cleared', async () => {
            await expectLogic(logic, () => logic.actions.toggleFacetValue(SERVICE_SOURCE, 'api')).toFinishAllListeners()
            expect(filtersLogic.values.serviceNames).toEqual(['api'])
            expect(logFilterExclusions(filtersLogic.values.filterGroup, 'service_name')).toEqual([])

            await expectLogic(logic, () => logic.actions.toggleFacetValue(SERVICE_SOURCE, 'api')).toFinishAllListeners()
            expect(filtersLogic.values.serviceNames).toEqual([])
            expect(logFilterExclusions(filtersLogic.values.filterGroup, 'service_name')).toEqual(['api'])

            await expectLogic(logic, () => logic.actions.toggleFacetValue(SERVICE_SOURCE, 'api')).toFinishAllListeners()
            expect(logFilterExclusions(filtersLogic.values.filterGroup, 'service_name')).toEqual([])
            expect((filtersLogic.values.filterGroup.values[0] as UniversalFiltersGroup).values).toEqual([])
        })

        it('holds one service included while another is excluded', async () => {
            await expectLogic(logic, () => logic.actions.toggleFacetValue(SERVICE_SOURCE, 'api')).toFinishAllListeners()
            await expectLogic(logic, () =>
                logic.actions.toggleFacetValue(SERVICE_SOURCE, 'worker')
            ).toFinishAllListeners()
            await expectLogic(logic, () => logic.actions.toggleFacetValue(SERVICE_SOURCE, 'api')).toFinishAllListeners()

            expect(filtersLogic.values.serviceNames).toEqual(['worker'])
            expect(logFilterExclusions(filtersLogic.values.filterGroup, 'service_name')).toEqual(['api'])
        })

        it('keeps service and severity exclusions under their own keys', async () => {
            // Both column facets store exclusions as is_not log filters — a service exclusion must
            // not clobber a severity exclusion already in the group, or vice versa.
            await expectLogic(logic, () => logic.actions.toggleFacetValue(LEVEL_SOURCE, 'error')).toFinishAllListeners()
            await expectLogic(logic, () => logic.actions.toggleFacetValue(LEVEL_SOURCE, 'error')).toFinishAllListeners()
            await expectLogic(logic, () => logic.actions.toggleFacetValue(SERVICE_SOURCE, 'api')).toFinishAllListeners()
            await expectLogic(logic, () => logic.actions.toggleFacetValue(SERVICE_SOURCE, 'api')).toFinishAllListeners()

            expect(logFilterExclusions(filtersLogic.values.filterGroup, 'severity_level')).toEqual(['error'])
            expect(logFilterExclusions(filtersLogic.values.filterGroup, 'service_name')).toEqual(['api'])
        })
    })

    describe('shared state', () => {
        it('toggles relative to selections already on the filters logic', async () => {
            filtersLogic.actions.setSeverityLevels(['info'])
            await expectLogic(filtersLogic).toFinishAllListeners()

            await expectLogic(logic, () => logic.actions.toggleFacetValue(LEVEL_SOURCE, 'error')).toFinishAllListeners()
            expect(filtersLogic.values.severityLevels).toEqual(['info', 'error'])
        })
    })

    describe('resource attribute cycling', () => {
        const read = (): FacetSelection =>
            resourceAttributeSelection(filtersLogic.values.filterGroup, 'k8s.namespace.name')
        const click = async (value: string): Promise<void> => {
            await expectLogic(logic, () =>
                logic.actions.toggleFacetValue(NAMESPACE_SOURCE, value)
            ).toFinishAllListeners()
        }

        it('cycles a value included → excluded → cleared through the shared filters logic', async () => {
            await click('argocd')
            expect(read()).toEqual({ included: ['argocd'], excluded: [] })

            await click('argocd')
            expect(read()).toEqual({ included: [], excluded: ['argocd'] })

            await click('argocd')
            expect(read()).toEqual({ included: [], excluded: [] })
            // the single inner group holds no filters once the cycle completes
            expect((filtersLogic.values.filterGroup.values[0] as UniversalFiltersGroup).values).toEqual([])
        })

        it('holds one value included while another is excluded (OR within includes, AND with excludes)', async () => {
            await click('argocd')
            await click('kube-system')
            expect(read()).toEqual({ included: ['argocd', 'kube-system'], excluded: [] })

            await click('argocd')
            expect(read()).toEqual({ included: ['kube-system'], excluded: ['argocd'] })
        })
    })
})
