import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { logsViewerFiltersLogic } from '../Filters/logsViewerFiltersLogic'
import { fieldRailLogic } from './fieldRailLogic'
import { FieldSource, resourceAttributeValues } from './fields'

const LEVEL_SOURCE: FieldSource = { type: 'column', column: 'severity_text', filterKey: 'severityLevels' }
const SERVICE_SOURCE: FieldSource = { type: 'column', column: 'service_name', filterKey: 'serviceNames' }
const NAMESPACE_SOURCE: FieldSource = { type: 'resourceAttribute', key: 'k8s.namespace.name' }

describe('fieldRailLogic', () => {
    let filtersLogic: ReturnType<typeof logsViewerFiltersLogic.build>
    let logic: ReturnType<typeof fieldRailLogic.build>

    beforeEach(() => {
        initKeaTests()
        filtersLogic = logsViewerFiltersLogic({ id: 'test' })
        filtersLogic.mount()
        logic = fieldRailLogic({ id: 'test' })
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        filtersLogic.unmount()
    })

    describe('severity level toggling', () => {
        it('adds, accumulates (OR), and removes levels on the shared filters logic', async () => {
            await expectLogic(logic, () => logic.actions.toggleFieldValue(LEVEL_SOURCE, 'error')).toFinishAllListeners()
            expect(filtersLogic.values.severityLevels).toEqual(['error'])

            await expectLogic(logic, () => logic.actions.toggleFieldValue(LEVEL_SOURCE, 'warn')).toFinishAllListeners()
            expect(filtersLogic.values.severityLevels).toEqual(['error', 'warn'])

            await expectLogic(logic, () => logic.actions.toggleFieldValue(LEVEL_SOURCE, 'error')).toFinishAllListeners()
            expect(filtersLogic.values.severityLevels).toEqual(['warn'])
        })

        it.each(['trace', 'info', 'error', 'fatal'] as const)(
            'toggling %s on then off round-trips to empty',
            async (level) => {
                await expectLogic(logic, () =>
                    logic.actions.toggleFieldValue(LEVEL_SOURCE, level)
                ).toFinishAllListeners()
                expect(filtersLogic.values.severityLevels).toEqual([level])

                await expectLogic(logic, () =>
                    logic.actions.toggleFieldValue(LEVEL_SOURCE, level)
                ).toFinishAllListeners()
                expect(filtersLogic.values.severityLevels).toEqual([])
            }
        )
    })

    describe('field collapse', () => {
        it('adds a field to the collapsed set, then removes it on the second toggle', async () => {
            await expectLogic(logic, () => logic.actions.toggleFieldCollapsed('level')).toFinishAllListeners()
            expect(logic.values.collapsedFields).toContain('level')

            await expectLogic(logic, () => logic.actions.toggleFieldCollapsed('service')).toFinishAllListeners()
            expect(logic.values.collapsedFields).toEqual(expect.arrayContaining(['level', 'service']))

            await expectLogic(logic, () => logic.actions.toggleFieldCollapsed('level')).toFinishAllListeners()
            expect(logic.values.collapsedFields).not.toContain('level')
            expect(logic.values.collapsedFields).toContain('service')
        })
    })

    describe('service name toggling', () => {
        it('adds then removes a service on the shared filters logic', async () => {
            await expectLogic(logic, () => logic.actions.toggleFieldValue(SERVICE_SOURCE, 'api')).toFinishAllListeners()
            expect(filtersLogic.values.serviceNames).toEqual(['api'])

            await expectLogic(logic, () => logic.actions.toggleFieldValue(SERVICE_SOURCE, 'api')).toFinishAllListeners()
            expect(filtersLogic.values.serviceNames).toEqual([])
        })
    })

    describe('shared state', () => {
        it('toggles relative to selections already on the filters logic', async () => {
            filtersLogic.actions.setSeverityLevels(['info'])
            await expectLogic(filtersLogic).toFinishAllListeners()

            await expectLogic(logic, () => logic.actions.toggleFieldValue(LEVEL_SOURCE, 'error')).toFinishAllListeners()
            expect(filtersLogic.values.severityLevels).toEqual(['info', 'error'])
        })
    })

    describe('resource attribute toggling', () => {
        const read = (): string[] => resourceAttributeValues(filtersLogic.values.filterGroup, 'k8s.namespace.name')

        it('adds, accumulates (OR), and removes values as a log_resource_attribute filter in the group', async () => {
            await expectLogic(logic, () =>
                logic.actions.toggleFieldValue(NAMESPACE_SOURCE, 'argocd')
            ).toFinishAllListeners()
            expect(read()).toEqual(['argocd'])

            await expectLogic(logic, () =>
                logic.actions.toggleFieldValue(NAMESPACE_SOURCE, 'kube-system')
            ).toFinishAllListeners()
            expect(read()).toEqual(['argocd', 'kube-system'])

            await expectLogic(logic, () =>
                logic.actions.toggleFieldValue(NAMESPACE_SOURCE, 'argocd')
            ).toFinishAllListeners()
            expect(read()).toEqual(['kube-system'])
        })
    })
})
