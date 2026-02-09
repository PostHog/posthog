import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'
import { FilterLogicalOperator } from '~/types'

import { logsViewerConfigLogic } from './logsViewerConfigLogic'
import { LogsViewerFilters } from './types'

describe('logsViewerConfigLogic', () => {
    let logic: ReturnType<typeof logsViewerConfigLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = logsViewerConfigLogic({ id: 'test-tab' })
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    describe('setFilter', () => {
        it.each([
            ['dateRange', { date_from: '-24h', date_to: null }],
            ['searchTerm', 'error message'],
            ['severityLevels', ['error', 'warn']],
            ['serviceNames', ['api', 'worker']],
            ['filterGroup', { type: FilterLogicalOperator.Or, values: [] }],
        ])('sets %s filter', async (filterKey, value) => {
            await expectLogic(logic, () => {
                logic.actions.setFilter(filterKey as keyof LogsViewerFilters, value)
            }).toFinishAllListeners()

            expect(logic.values.filters[filterKey as keyof LogsViewerFilters]).toEqual(value)
        })

        it('preserves other filters when setting a single filter', async () => {
            logic.actions.setFilter('searchTerm', 'first')
            await expectLogic(logic).toFinishAllListeners()

            logic.actions.setFilter('severityLevels', ['error'])
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.filters.searchTerm).toBe('first')
            expect(logic.values.filters.severityLevels).toEqual(['error'])
        })
    })

    describe('setFilters', () => {
        it('replaces all filters', async () => {
            const newFilters: LogsViewerFilters = {
                dateRange: { date_from: '-7d', date_to: null },
                searchTerm: 'test query',
                severityLevels: ['info', 'debug'],
                serviceNames: ['frontend'],
                filterGroup: { type: FilterLogicalOperator.And, values: [] },
            }

            await expectLogic(logic, () => {
                logic.actions.setFilters(newFilters)
            }).toMatchValues({
                filters: newFilters,
            })
        })
    })

    describe('keyed instances', () => {
        it('maintains separate state for different keys', async () => {
            const logic1 = logsViewerConfigLogic({ id: 'tab-1' })
            const logic2 = logsViewerConfigLogic({ id: 'tab-2' })
            logic1.mount()
            logic2.mount()

            logic1.actions.setFilter('searchTerm', 'tab 1 search')
            logic2.actions.setFilter('searchTerm', 'tab 2 search')
            await expectLogic(logic1).toFinishAllListeners()
            await expectLogic(logic2).toFinishAllListeners()

            expect(logic1.values.filters.searchTerm).toBe('tab 1 search')
            expect(logic2.values.filters.searchTerm).toBe('tab 2 search')

            logic1.unmount()
            logic2.unmount()
        })
    })
})
