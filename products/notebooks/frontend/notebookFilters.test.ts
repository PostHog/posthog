import { convertUniversalFiltersToRecordingsQuery } from 'scenes/session-recordings/filters/recordingsQueryConversions'

import { DataTableNode, InsightVizNode, NodeKind } from '~/queries/schema/schema-general'
import { FilterLogicalOperator, PropertyFilterType, PropertyOperator, RecordingUniversalFilters } from '~/types'

import { getFilteredNotebookPlaylist, getFilteredNotebookQuery } from './notebookFilters'

describe('notebook filters', () => {
    const cohort = { type: PropertyFilterType.Cohort, key: 'id', operator: PropertyOperator.In, value: 42 } as const
    const otherCohort = { ...cohort, value: 7 }
    const condition = {
        type: PropertyFilterType.Person,
        key: 'region',
        operator: PropertyOperator.Exact,
        value: 'west',
    } as const

    const event = {
        type: PropertyFilterType.Event,
        key: 'source',
        operator: PropertyOperator.Exact,
        value: 'web',
    } as const
    const dateRange = { date_from: '-30d', date_to: null }

    it('combines authored OR conditions with multiple notebook properties', () => {
        const original: InsightVizNode = {
            kind: NodeKind.InsightVizNode,
            source: {
                kind: NodeKind.TrendsQuery,
                series: [{ kind: NodeKind.EventsNode, event: null }],
                properties: {
                    type: FilterLogicalOperator.Or,
                    values: [{ type: FilterLogicalOperator.Or, values: [condition, otherCohort] }],
                },
            },
        }
        const before = structuredClone(original)
        expect(getFilteredNotebookQuery(original, { properties: [cohort, event] })).toMatchObject({
            source: {
                properties: {
                    type: 'AND',
                    values: [before.source.properties, { type: 'AND', values: [cohort, event] }],
                },
            },
        })
        expect(original).toEqual(before)
    })

    it.each([NodeKind.ActorsQuery, NodeKind.PersonsNode, NodeKind.EventsQuery] as const)(
        'narrows %s and starts at its first page',
        (kind) => {
            const table: DataTableNode = {
                kind: NodeKind.DataTableNode,
                source: { kind, select: ['id'], fixedProperties: [otherCohort], offset: 20 },
            }
            expect(getFilteredNotebookQuery(table, { properties: [cohort] })).toMatchObject({
                source: { fixedProperties: [otherCohort, cohort], offset: 0 },
            })
            expect(table.source).toMatchObject({ fixedProperties: [otherCohort], offset: 20 })
        }
    )

    it('keeps both list and collection constraints in the replay request', () => {
        const filters: RecordingUniversalFilters = {
            duration: [],
            date_from: '-7d',
            filter_group: { type: FilterLogicalOperator.And, values: [condition] },
        }
        const preview = getFilteredNotebookPlaylist(filters, { properties: [cohort] }, ['recording-a'])
        expect(convertUniversalFiltersToRecordingsQuery(preview!)).toMatchObject({
            date_from: '-7d',
            operand: 'AND',
            properties: [{ ...condition, value: ['west'] }, cohort],
            session_ids: ['recording-a'],
        })
        expect(filters.filter_group.values).toEqual([condition])
        expect(
            getFilteredNotebookPlaylist(
                { ...filters, filter_group: { type: FilterLogicalOperator.Or, values: [otherCohort, condition] } },
                { properties: [cohort] }
            )
        ).toBeNull()
    })

    it.each([
        [['recording-a', 'recording-c'], ['recording-a']],
        [['recording-c'], []],
        [[], []],
    ])('intersects authored session IDs %j with collection membership', (authored, expected) => {
        const filters: RecordingUniversalFilters = {
            duration: [],
            filter_group: { type: FilterLogicalOperator.And, values: [] },
            session_ids: authored,
        }
        const preview = getFilteredNotebookPlaylist(filters, { properties: [cohort] }, ['recording-a', 'recording-b'])
        expect(convertUniversalFiltersToRecordingsQuery(preview!).session_ids).toEqual(expected)
    })

    it('does not mark an account users table as cohort filtered', () => {
        const table: DataTableNode = {
            kind: NodeKind.DataTableNode,
            source: { kind: NodeKind.ActorsQuery, source: { kind: NodeKind.AccountUsersQuery, accountId: 'a' } },
        }
        expect(getFilteredNotebookQuery(table, { properties: [cohort] })).toBeNull()
    })

    it.each(['targetEntity', 'returningEntity'] as const)('rejects warehouse retention on the %s side', (side) => {
        const query: InsightVizNode = {
            kind: NodeKind.InsightVizNode,
            source: { kind: NodeKind.RetentionQuery, retentionFilter: { [side]: { type: 'data_warehouse' } } },
        }
        expect(getFilteredNotebookQuery(query, { properties: [cohort] })).toBeNull()
    })

    it.each([NodeKind.PersonsNode, NodeKind.ActorsQuery] as const)(
        'leaves %s unfiltered when it cannot apply every condition',
        (kind) => {
            const table: DataTableNode = { kind: NodeKind.DataTableNode, source: { kind } }
            expect(getFilteredNotebookQuery(table, { properties: [condition, event] })).toBeNull()
            expect(getFilteredNotebookQuery(table, { properties: [cohort], dateRange })).toBeNull()
            expect(getFilteredNotebookQuery(table, { properties: [condition, cohort] })?.source).toMatchObject({
                fixedProperties: [condition, cohort],
            })
        }
    )

    it('overrides dates for events and applies person and event filters', () => {
        const table: DataTableNode = {
            kind: NodeKind.DataTableNode,
            source: { kind: NodeKind.EventsQuery, select: ['event'], before: 'yesterday', after: '-7d' },
        }
        expect(getFilteredNotebookQuery(table, { properties: [condition, event], dateRange })?.source).toMatchObject({
            before: undefined,
            after: '-30d',
            fixedProperties: [condition, event],
        })
    })

    it('preserves insight exclusions and authored properties when only the date changes', () => {
        const insight: InsightVizNode = {
            kind: NodeKind.InsightVizNode,
            source: {
                kind: NodeKind.TrendsQuery,
                series: [],
                dateRange: { date_from: '-7d', daysOfWeek: [1] },
                properties: [condition],
            },
        }
        expect(getFilteredNotebookQuery(insight, { properties: [], dateRange })?.source).toMatchObject({
            dateRange: { ...dateRange, daysOfWeek: [1] },
            properties: [condition],
        })
    })

    it('can override dates on a match-any recording list without changing its conditions', () => {
        const filters: RecordingUniversalFilters = {
            duration: [],
            date_from: '-7d',
            filter_group: { type: FilterLogicalOperator.Or, values: [event, cohort] },
        }
        const preview = getFilteredNotebookPlaylist(filters, { properties: [], dateRange })
        expect(convertUniversalFiltersToRecordingsQuery(preview!)).toMatchObject({
            ...dateRange,
            operand: 'OR',
            properties: [{ ...event, value: ['web'] }, cohort],
        })
        const combined = getFilteredNotebookPlaylist(
            { ...filters, filter_group: { type: FilterLogicalOperator.And, values: [] } },
            { properties: [event, condition], dateRange }
        )
        expect(convertUniversalFiltersToRecordingsQuery(combined!)).toMatchObject({
            ...dateRange,
            properties: [
                { ...event, value: ['web'] },
                { ...condition, value: ['west'] },
            ],
        })
    })

    it('does not label a SQL table as filtered', () => {
        const table: DataTableNode = {
            kind: NodeKind.DataTableNode,
            source: { kind: NodeKind.HogQLQuery, query: 'select 1' },
        }
        expect(getFilteredNotebookQuery(table, { properties: [cohort] })).toBeNull()
    })
})
