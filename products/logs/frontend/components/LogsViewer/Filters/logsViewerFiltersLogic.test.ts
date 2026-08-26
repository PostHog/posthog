import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'
import { FilterLogicalOperator, PropertyFilterType, PropertyOperator, UniversalFiltersGroup } from '~/types'

import { LogsViewerFilters } from 'products/logs/frontend/components/LogsViewer/config/types'
import {
    SERVICE_NAME_FILTER,
    SEVERITY_LEVEL_FILTER,
    facetSelection,
} from 'products/logs/frontend/components/LogsViewer/FacetRail/facetFilters'

import { logsViewerFiltersLogic } from './logsViewerFiltersLogic'

describe('logsViewerFiltersLogic', () => {
    let logic: ReturnType<typeof logsViewerFiltersLogic.build>

    const selectedLevels = (built = logic): string[] =>
        facetSelection(built.values.filters.filterGroup, SEVERITY_LEVEL_FILTER).included
    const selectedServices = (built = logic): string[] =>
        facetSelection(built.values.filters.filterGroup, SERVICE_NAME_FILTER).included

    beforeEach(() => {
        initKeaTests()
        logic = logsViewerFiltersLogic({ id: 'test-tab' })
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    describe('individual filter actions', () => {
        it.each([
            ['setDateRange', 'dateRange', { date_from: '-24h', date_to: null }],
            ['setSearchTerm', 'searchTerm', 'error message'],
            [
                'setFilterGroup',
                'filterGroup',
                { type: FilterLogicalOperator.Or, values: [{ type: FilterLogicalOperator.And, values: [] }] },
            ],
        ])('%s sets %s', async (action, key, value) => {
            await expectLogic(logic, () => {
                ;(logic.actions as any)[action](value)
            }).toFinishAllListeners()

            expect((logic.values.filters as any)[key]).toEqual(value)
        })
    })

    describe('setFilters (bulk)', () => {
        it('applies partial filter updates without resetting others', async () => {
            logic.actions.setSearchTerm('existing search')
            await expectLogic(logic).toFinishAllListeners()

            logic.actions.setFilters({ severityLevels: ['error', 'warn'] })
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.filters.searchTerm).toBe('existing search')
            expect(selectedLevels()).toEqual(['error', 'warn'])
        })

        it('applies all filters when fully specified', async () => {
            const newFilters: LogsViewerFilters = {
                dateRange: { date_from: '-7d', date_to: null },
                searchTerm: 'test query',
                severityLevels: ['info', 'debug'],
                serviceNames: ['frontend'],
                filterGroup: {
                    type: FilterLogicalOperator.And,
                    values: [{ type: FilterLogicalOperator.And, values: [] }],
                },
            }

            await expectLogic(logic, () => {
                logic.actions.setFilters(newFilters)
            }).toFinishAllListeners()

            expect(logic.values.filters.dateRange).toEqual(newFilters.dateRange)
            expect(logic.values.filters.searchTerm).toBe('test query')
            expect(selectedLevels()).toEqual(['info', 'debug'])
            expect(selectedServices()).toEqual(['frontend'])
        })

        // The level/service fields are an input channel; a caller that hands them over gets a chip in
        // the filter bar, which is the same state the facet rail reads.
        it('folds a level and service selection into the filterGroup', async () => {
            await expectLogic(logic, () => {
                logic.actions.setFilters({ severityLevels: ['error'], serviceNames: ['api'] })
            }).toFinishAllListeners()

            expect((logic.values.filters.filterGroup.values[0] as UniversalFiltersGroup).values).toEqual([
                {
                    key: 'severity_level',
                    type: PropertyFilterType.Log,
                    operator: PropertyOperator.Exact,
                    value: ['error'],
                },
                { key: 'service_name', type: PropertyFilterType.Log, operator: PropertyOperator.Exact, value: ['api'] },
            ])
        })

        it('clears a folded selection when handed the field empty', async () => {
            logic.actions.setFilters({ serviceNames: ['api'] })
            await expectLogic(logic).toFinishAllListeners()

            await expectLogic(logic, () => {
                logic.actions.setFilters({ serviceNames: [] })
            }).toFinishAllListeners()

            expect(selectedServices()).toEqual([])
        })

        // A filter-history entry or a saved view can hand over both, and the group is then the whole
        // selection.
        it('keeps a chip when an empty field arrives alongside a group', async () => {
            await expectLogic(logic, () => {
                logic.actions.setFilters({
                    serviceNames: [],
                    severityLevels: [],
                    filterGroup: {
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
                            },
                        ],
                    },
                })
            }).toFinishAllListeners()

            expect(selectedServices()).toEqual(['api'])
        })
    })

    describe('setFilterGroup fallback', () => {
        it('falls back to default when given invalid filterGroup', async () => {
            logic.actions.setFilterGroup(null as any)
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.filters.filterGroup).toEqual({
                type: FilterLogicalOperator.And,
                values: [{ type: FilterLogicalOperator.And, values: [] }],
            })
        })
    })

    describe('utcDateRange', () => {
        it.each([
            {
                label: 'converts valid absolute dates to ISO strings',
                dateRange: { date_from: '2024-01-15T10:30:00', date_to: '2024-01-15T12:00:00' },
                expected: {
                    date_from: expect.stringMatching(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}/),
                    date_to: expect.stringMatching(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}/),
                },
            },
            {
                label: 'preserves relative date_from and null date_to',
                dateRange: { date_from: '-1h', date_to: null },
                expected: { date_from: '-1h', date_to: null },
            },
            {
                label: 'preserves relative date_from with valid absolute date_to',
                dateRange: { date_from: '-7d', date_to: '2024-01-15T12:00:00' },
                expected: {
                    date_from: '-7d',
                    date_to: expect.stringMatching(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}/),
                },
            },
            {
                label: 'forwards explicitDate unchanged',
                dateRange: { date_from: '-1h', date_to: null, explicitDate: true },
                expected: { date_from: '-1h', date_to: null, explicitDate: true },
            },
        ])('$label', async ({ dateRange, expected }) => {
            logic.actions.setDateRange(dateRange)
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.utcDateRange).toEqual(expect.objectContaining(expected))
        })
    })

    describe('initialFilters', () => {
        it('applies initialFilters on mount', async () => {
            const initialLogic = logsViewerFiltersLogic({
                id: 'with-initial',
                initialFilters: { searchTerm: 'session_id:abc', severityLevels: ['error'] },
            })
            initialLogic.mount()
            await expectLogic(initialLogic).toFinishAllListeners()

            expect(initialLogic.values.filters.searchTerm).toBe('session_id:abc')
            expect(selectedLevels(initialLogic)).toEqual(['error'])
            // other filters remain at defaults
            expect(initialLogic.values.filters.dateRange).toEqual({ date_from: '-1h', date_to: null })

            initialLogic.unmount()
        })

        it('does not call setFilters when no initialFilters provided', async () => {
            const plainLogic = logsViewerFiltersLogic({ id: 'no-initial' })
            plainLogic.mount()
            await expectLogic(plainLogic).toFinishAllListeners()

            expect(plainLogic.values.filters.searchTerm).toBe('')
            expect(selectedLevels(plainLogic)).toEqual([])

            plainLogic.unmount()
        })

        it('applies new initialFilters when props change', async () => {
            const initialProps = {
                id: 'props-changed',
                initialFilters: { searchTerm: 'first' },
            }
            const builtLogic = logsViewerFiltersLogic.build(initialProps)
            builtLogic.mount()
            await expectLogic(builtLogic).toFinishAllListeners()

            expect(builtLogic.values.filters.searchTerm).toBe('first')

            // Simulate props change (as BindLogic would do when parent re-renders with new props)
            logsViewerFiltersLogic.build({
                id: 'props-changed',
                initialFilters: { searchTerm: 'second', severityLevels: ['warn'] },
            })
            await expectLogic(builtLogic).toFinishAllListeners()

            expect(builtLogic.values.filters.searchTerm).toBe('second')
            expect(selectedLevels(builtLogic)).toEqual(['warn'])

            builtLogic.unmount()
        })

        it('resets filters when initialFilters is removed', async () => {
            const builtLogic = logsViewerFiltersLogic.build({
                id: 'props-cleared',
                initialFilters: { searchTerm: 'session_id:abc' },
            })
            builtLogic.mount()
            await expectLogic(builtLogic).toFinishAllListeners()
            expect(builtLogic.values.filters.searchTerm).toBe('session_id:abc')

            // Simulate reopening without initialFilters
            logsViewerFiltersLogic.build({ id: 'props-cleared', initialFilters: undefined })
            await expectLogic(builtLogic).toFinishAllListeners()

            expect(builtLogic.values.filters.searchTerm).toBe('')
            expect(selectedLevels(builtLogic)).toEqual([])
            expect(selectedServices(builtLogic)).toEqual([])

            builtLogic.unmount()
        })
    })

    describe('keyed instances', () => {
        it('maintains separate state for different keys', async () => {
            const logic1 = logsViewerFiltersLogic({ id: 'tab-1' })
            const logic2 = logsViewerFiltersLogic({ id: 'tab-2' })
            logic1.mount()
            logic2.mount()

            logic1.actions.setSearchTerm('tab 1 search')
            logic2.actions.setSearchTerm('tab 2 search')
            await expectLogic(logic1).toFinishAllListeners()
            await expectLogic(logic2).toFinishAllListeners()

            expect(logic1.values.filters.searchTerm).toBe('tab 1 search')
            expect(logic2.values.filters.searchTerm).toBe('tab 2 search')

            logic1.unmount()
            logic2.unmount()
        })
    })
})
