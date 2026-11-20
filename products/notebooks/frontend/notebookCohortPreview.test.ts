import { convertUniversalFiltersToRecordingsQuery } from 'scenes/session-recordings/filters/recordingsQueryConversions'

import { DataTableNode, InsightVizNode, NodeKind } from '~/queries/schema/schema-general'
import { FilterLogicalOperator, PropertyFilterType, PropertyOperator, RecordingUniversalFilters } from '~/types'

import { getNotebookCohortPlaylist, getNotebookCohortQuery } from './notebookCohortPreview'

describe('notebook cohort preview', () => {
    const cohort = { type: PropertyFilterType.Cohort, key: 'id', operator: PropertyOperator.In, value: 42 } as const
    const otherCohort = { ...cohort, value: 7 }
    const condition = {
        type: PropertyFilterType.Person,
        key: 'region',
        operator: PropertyOperator.Exact,
        value: 'west',
    } as const

    it('combines an insight’s existing OR group with the preview cohort', () => {
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
        expect(getNotebookCohortQuery(original, 42)).toMatchObject({
            source: {
                properties: { type: 'AND', values: [before.source.properties, { type: 'AND', values: [cohort] }] },
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
            expect(getNotebookCohortQuery(table, 42)).toMatchObject({
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
        const preview = getNotebookCohortPlaylist(filters, 42, ['recording-a'])
        expect(convertUniversalFiltersToRecordingsQuery(preview!)).toMatchObject({
            date_from: '-7d',
            operand: 'AND',
            properties: [{ ...condition, value: ['west'] }, cohort],
            session_ids: ['recording-a'],
        })
        expect(filters.filter_group.values).toEqual([condition])
        expect(
            getNotebookCohortPlaylist(
                { ...filters, filter_group: { type: FilterLogicalOperator.Or, values: [otherCohort, condition] } },
                42
            )
        ).toBeNull()
    })

    it('does not label a SQL table as filtered', () => {
        const table: DataTableNode = {
            kind: NodeKind.DataTableNode,
            source: { kind: NodeKind.HogQLQuery, query: 'select 1' },
        }
        expect(getNotebookCohortQuery(table, 42)).toBeNull()
    })
})
