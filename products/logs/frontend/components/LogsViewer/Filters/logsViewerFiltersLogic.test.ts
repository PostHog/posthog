import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'
import { FilterLogicalOperator } from '~/types'

import { LogsViewerFilters } from 'products/logs/frontend/components/LogsViewer/config/types'

import { logsViewerFiltersLogic } from './logsViewerFiltersLogic'

describe('logsViewerFiltersLogic', () => {
    let logic: ReturnType<typeof logsViewerFiltersLogic.build>

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
            ['setSeverityLevels', 'severityLevels', ['error', 'warn']],
            ['setServiceNames', 'serviceNames', ['api', 'worker']],
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

        it('preserves other filters when setting a single filter', async () => {
            logic.actions.setSearchTerm('first')
            logic.actions.setSeverityLevels(['error'])
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.filters.searchTerm).toBe('first')
            expect(logic.values.filters.severityLevels).toEqual(['error'])
        })
    })

    describe('setFilters (bulk)', () => {
        it('applies partial filter updates without resetting others', async () => {
            logic.actions.setSearchTerm('existing search')
            await expectLogic(logic).toFinishAllListeners()

            logic.actions.setFilters({ severityLevels: ['error', 'warn'] })
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.filters.searchTerm).toBe('existing search')
            expect(logic.values.filters.severityLevels).toEqual(['error', 'warn'])
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
            }).toMatchValues({
                filters: newFilters,
            })
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
