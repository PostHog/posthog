import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'
import { UniversalFiltersGroup } from '~/types'

import { logsViewerFiltersLogic } from '../Filters/logsViewerFiltersLogic'
import { facetRailLogic } from './facetRailLogic'
import { FacetSource, resourceAttributeValues } from './facets'

const LEVEL_SOURCE: FacetSource = { type: 'column', column: 'severity_text', filterKey: 'severityLevels' }
const SERVICE_SOURCE: FacetSource = { type: 'column', column: 'service_name', filterKey: 'serviceNames' }
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

    describe('severity level toggling', () => {
        it('adds, accumulates (OR), and removes levels on the shared filters logic', async () => {
            await expectLogic(logic, () => logic.actions.toggleFacetValue(LEVEL_SOURCE, 'error')).toFinishAllListeners()
            expect(filtersLogic.values.severityLevels).toEqual(['error'])

            await expectLogic(logic, () => logic.actions.toggleFacetValue(LEVEL_SOURCE, 'warn')).toFinishAllListeners()
            expect(filtersLogic.values.severityLevels).toEqual(['error', 'warn'])

            await expectLogic(logic, () => logic.actions.toggleFacetValue(LEVEL_SOURCE, 'error')).toFinishAllListeners()
            expect(filtersLogic.values.severityLevels).toEqual(['warn'])
        })

        it.each(['trace', 'info', 'error', 'fatal'] as const)(
            'toggling %s on then off round-trips to empty',
            async (level) => {
                await expectLogic(logic, () =>
                    logic.actions.toggleFacetValue(LEVEL_SOURCE, level)
                ).toFinishAllListeners()
                expect(filtersLogic.values.severityLevels).toEqual([level])

                await expectLogic(logic, () =>
                    logic.actions.toggleFacetValue(LEVEL_SOURCE, level)
                ).toFinishAllListeners()
                expect(filtersLogic.values.severityLevels).toEqual([])
            }
        )
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

    describe('service name toggling', () => {
        it('adds then removes a service on the shared filters logic', async () => {
            await expectLogic(logic, () => logic.actions.toggleFacetValue(SERVICE_SOURCE, 'api')).toFinishAllListeners()
            expect(filtersLogic.values.serviceNames).toEqual(['api'])

            await expectLogic(logic, () => logic.actions.toggleFacetValue(SERVICE_SOURCE, 'api')).toFinishAllListeners()
            expect(filtersLogic.values.serviceNames).toEqual([])
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

    describe('resource attribute toggling', () => {
        const read = (): string[] => resourceAttributeValues(filtersLogic.values.filterGroup, 'k8s.namespace.name')

        it('adds, accumulates (OR), and removes values as a log_resource_attribute filter in the group', async () => {
            await expectLogic(logic, () =>
                logic.actions.toggleFacetValue(NAMESPACE_SOURCE, 'argocd')
            ).toFinishAllListeners()
            expect(read()).toEqual(['argocd'])

            await expectLogic(logic, () =>
                logic.actions.toggleFacetValue(NAMESPACE_SOURCE, 'kube-system')
            ).toFinishAllListeners()
            expect(read()).toEqual(['argocd', 'kube-system'])

            await expectLogic(logic, () =>
                logic.actions.toggleFacetValue(NAMESPACE_SOURCE, 'argocd')
            ).toFinishAllListeners()
            expect(read()).toEqual(['kube-system'])
        })

        it('removing the last value drops the filter from the group entirely', async () => {
            await expectLogic(logic, () =>
                logic.actions.toggleFacetValue(NAMESPACE_SOURCE, 'argocd')
            ).toFinishAllListeners()
            expect(read()).toEqual(['argocd'])

            await expectLogic(logic, () =>
                logic.actions.toggleFacetValue(NAMESPACE_SOURCE, 'argocd')
            ).toFinishAllListeners()
            expect(read()).toEqual([])
            // the single inner group holds no filters once the last value is removed
            expect((filtersLogic.values.filterGroup.values[0] as UniversalFiltersGroup).values).toEqual([])
        })
    })
})
