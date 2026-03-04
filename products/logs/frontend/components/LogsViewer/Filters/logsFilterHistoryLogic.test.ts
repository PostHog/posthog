import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'
import { FilterLogicalOperator } from '~/types'

import { LogsViewerFilters } from 'products/logs/frontend/components/LogsViewer/config/types'

import { logsFilterHistoryLogic } from './logsFilterHistoryLogic'

describe('logsFilterHistoryLogic', () => {
    let logic: ReturnType<typeof logsFilterHistoryLogic.build>

    const createFilters = (searchTerm: string): LogsViewerFilters => ({
        dateRange: { date_from: '-1h', date_to: null },
        searchTerm,
        severityLevels: [],
        serviceNames: [],
        filterGroup: { type: FilterLogicalOperator.And, values: [] },
    })

    beforeEach(async () => {
        initKeaTests()
        logic = logsFilterHistoryLogic({ id: 'test-tab' })
        logic.mount()

        logic.actions.clearFilterHistory()
        await expectLogic(logic).toFinishAllListeners()
    })

    afterEach(() => {
        logic.unmount()
    })

    describe('pushToFilterHistory', () => {
        it('adds entry to empty history', async () => {
            const filters = createFilters('test query')

            await expectLogic(logic, () => {
                logic.actions.pushToFilterHistory(filters)
            }).toMatchValues({
                filterHistory: [{ filters, timestamp: expect.any(Number) }],
            })
        })

        it('prepends new entries to history', async () => {
            const filters1 = createFilters('first')
            const filters2 = createFilters('second')

            logic.actions.pushToFilterHistory(filters1)
            await expectLogic(logic).toFinishAllListeners()

            await expectLogic(logic, () => {
                logic.actions.pushToFilterHistory(filters2)
            }).toMatchValues({
                filterHistory: [
                    { filters: filters2, timestamp: expect.any(Number) },
                    { filters: filters1, timestamp: expect.any(Number) },
                ],
            })
        })

        it('deduplicates consecutive identical filters', async () => {
            const filters = createFilters('same query')

            logic.actions.pushToFilterHistory(filters)
            await expectLogic(logic).toFinishAllListeners()

            await expectLogic(logic, () => {
                logic.actions.pushToFilterHistory(filters)
            }).toMatchValues({
                filterHistory: [{ filters, timestamp: expect.any(Number) }],
            })

            expect(logic.values.filterHistory).toHaveLength(1)
        })

        it('limits history to 10 entries', async () => {
            for (let i = 0; i < 15; i++) {
                logic.actions.pushToFilterHistory(createFilters(`query ${i}`))
            }
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.filterHistory).toHaveLength(10)
            expect(logic.values.filterHistory[0].filters.searchTerm).toBe('query 14')
            expect(logic.values.filterHistory[9].filters.searchTerm).toBe('query 5')
        })
    })

    describe('clearFilterHistory', () => {
        it('clears all history entries', async () => {
            logic.actions.pushToFilterHistory(createFilters('query 1'))
            logic.actions.pushToFilterHistory(createFilters('query 2'))
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.filterHistory).toHaveLength(2)

            await expectLogic(logic, () => {
                logic.actions.clearFilterHistory()
            }).toMatchValues({
                filterHistory: [],
            })
        })
    })

    describe('restoreFiltersFromHistory', () => {
        it('restores filters from history entry', async () => {
            const filters = createFilters('restored query')
            filters.severityLevels = ['error', 'warn']

            logic.actions.pushToFilterHistory(filters)
            await expectLogic(logic).toFinishAllListeners()

            await expectLogic(logic, () => {
                logic.actions.restoreFiltersFromHistory(0)
            }).toDispatchActions(['restoreFiltersFromHistory', 'setFilters'])
        })

        it('does not push to history when restoring', async () => {
            const filters1 = createFilters('first')
            const filters2 = createFilters('second')

            logic.actions.pushToFilterHistory(filters1)
            logic.actions.pushToFilterHistory(filters2)
            await expectLogic(logic).toFinishAllListeners()

            const historyLengthBefore = logic.values.filterHistory.length

            await expectLogic(logic, () => {
                logic.actions.restoreFiltersFromHistory(1)
            }).toFinishAllListeners()

            expect(logic.values.filterHistory).toHaveLength(historyLengthBefore)
        })

        it('does nothing for invalid index', async () => {
            logic.actions.pushToFilterHistory(createFilters('test'))
            await expectLogic(logic).toFinishAllListeners()

            await expectLogic(logic, () => {
                logic.actions.restoreFiltersFromHistory(99)
            })
                .toDispatchActions(['restoreFiltersFromHistory'])
                .toNotHaveDispatchedActions(['setFilters'])
        })
    })

    describe('hasFilterHistory selector', () => {
        it('returns false when history is empty', () => {
            expect(logic.values.hasFilterHistory).toBe(false)
        })

        it('returns true when history has entries', async () => {
            logic.actions.pushToFilterHistory(createFilters('test'))
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.hasFilterHistory).toBe(true)
        })
    })
})
