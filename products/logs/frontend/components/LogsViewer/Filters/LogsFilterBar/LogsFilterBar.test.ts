import { recentTaxonomicFiltersLogic } from 'lib/components/TaxonomicFilter/recentTaxonomicFiltersLogic'
import { TaxonomicFilterGroup, TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import { initKeaTests } from '~/test/init'
import { PropertyFilterType, PropertyOperator } from '~/types'

import { addLogsValueFilter } from './LogsFilterBar'

// The Logs group's getValue returns option.key, so `value` is 'message' while the searched-for text
// lives on item.value. See buildTaxonomicGroups' localItemsSearch for the Logs group.
const LOGS_GROUP = { name: 'Logs', type: TaxonomicFilterGroupType.Logs } as TaxonomicFilterGroup
const messageSearchItem = (query: string): Record<string, any> => ({
    key: 'message',
    name: `Search log message for "${query}"`,
    value: query,
    propertyFilterType: 'log',
})

describe('addLogsValueFilter', () => {
    let logic: ReturnType<typeof recentTaxonomicFiltersLogic.build>

    beforeEach(() => {
        localStorage.clear()
        initKeaTests()
        logic = recentTaxonomicFiltersLogic.build()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('builds a contains filter for the searched text', () => {
        expect(addLogsValueFilter(LOGS_GROUP, 'message', messageSearchItem('foobar'), [])).toEqual([
            {
                key: 'message',
                value: 'foobar',
                operator: PropertyOperator.IContains,
                type: PropertyFilterType.Log,
            },
        ])
    })

    it('appends to existing filters rather than replacing them', () => {
        const existing = [{ key: 'severity_level', value: 'error', type: PropertyFilterType.Log }] as any
        expect(addLogsValueFilter(LOGS_GROUP, 'message', messageSearchItem('foobar'), existing)).toHaveLength(2)
    })

    it('reconciles with an existing filter on the same attribute instead of duplicating it', () => {
        const existing = addLogsValueFilter(LOGS_GROUP, 'message', messageSearchItem('foobar'), [])

        expect(addLogsValueFilter(LOGS_GROUP, 'message', messageSearchItem('foobar'), existing)).toEqual(existing)
    })

    // The regression: without recording the complete filter here, the only record of this selection is
    // taxonomicFilterLogic's, which drops the value — so re-selecting from "Recent" yields `message`
    // with nothing to match on.
    it('records the searched value to recents so re-selecting it restores the filter', () => {
        addLogsValueFilter(LOGS_GROUP, 'message', messageSearchItem('foobar'), [])

        expect(logic.values.recentFilters).toHaveLength(1)
        expect(logic.values.recentFilters[0].propertyFilter).toMatchObject({
            key: 'message',
            value: 'foobar',
            operator: PropertyOperator.IContains,
            type: PropertyFilterType.Log,
        })
    })

    // Recents are expanded into a bare-key row plus a full-filter row, and the bare row inherits this name
    // while dropping the value. Naming it after the search phrase produced the reported bug: a row reading
    // `Search log message for "foobar"` that applied an empty `message` filter when clicked.
    it('names the recent after the key so the bare-key row does not promise a value', () => {
        addLogsValueFilter(LOGS_GROUP, 'message', messageSearchItem('foobar'), [])

        expect(logic.values.recentFilters[0].item).toEqual({ name: 'message' })
    })

    // What taxonomicFilterLogic writes for the same selection: same group and value, but a stripped item and
    // no propertyFilter. Whichever order the two writes land in, the reducer keeps the complete one — so the
    // outcome does not depend on the ordering between our synchronous write and its deferred one.
    const recordValueLessWrite = (): void =>
        logic.actions.recordRecentFilter({
            groupType: TaxonomicFilterGroupType.Logs,
            groupName: 'Logs',
            value: 'message',
            item: { name: 'message' },
        })

    it("survives taxonomicFilterLogic's value-less record landing after ours", () => {
        addLogsValueFilter(LOGS_GROUP, 'message', messageSearchItem('foobar'), [])
        recordValueLessWrite()

        expect(logic.values.recentFilters).toHaveLength(1)
        expect(logic.values.recentFilters[0].propertyFilter).toMatchObject({ value: 'foobar' })
    })

    it("survives taxonomicFilterLogic's value-less record landing before ours", () => {
        recordValueLessWrite()
        addLogsValueFilter(LOGS_GROUP, 'message', messageSearchItem('foobar'), [])

        expect(logic.values.recentFilters).toHaveLength(1)
        expect(logic.values.recentFilters[0].propertyFilter).toMatchObject({ value: 'foobar' })
    })
})
