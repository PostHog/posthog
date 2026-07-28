import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'
import { UniversalFiltersGroup } from '~/types'

import { logsViewerFiltersLogic } from '../Filters/logsViewerFiltersLogic'
import { facetRailLogic } from './facetRailLogic'
import { FacetSelection, FacetSource, resourceAttributeSelection } from './facets'

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
