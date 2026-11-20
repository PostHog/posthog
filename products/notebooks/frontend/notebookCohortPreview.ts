import { deriveOperand } from 'scenes/session-recordings/filters/recordingsQueryConversions'
import { filtersFromUniversalFilterGroups } from 'scenes/session-recordings/utils'

import { isAnyDataWarehouseNode, isDataTableNode, isInsightVizNode } from '~/queries/schema/node-guards'
import {
    ActorsQuery,
    DataTableNode,
    EventsQuery,
    InsightVizNode,
    Node,
    NodeKind,
    PersonsNode,
} from '~/queries/schema/schema-general'
import {
    CohortPropertyFilter,
    FilterLogicalOperator,
    PropertyFilterType,
    PropertyOperator,
    RecordingUniversalFilters,
} from '~/types'

function notebookCohortProperty(id: number): CohortPropertyFilter {
    return { type: PropertyFilterType.Cohort, key: 'id', operator: PropertyOperator.In, value: id }
}

function filterTableSource<T extends ActorsQuery | PersonsNode | EventsQuery>(
    source: T,
    cohort: CohortPropertyFilter
): T {
    return { ...source, fixedProperties: [...(source.fixedProperties ?? []), cohort], offset: 0 }
}

export function getNotebookCohortQuery(
    query: Node | null | undefined,
    id: number
): InsightVizNode | DataTableNode | null {
    const cohort = notebookCohortProperty(id)
    if (isDataTableNode(query)) {
        const source = query.source
        switch (source.kind) {
            case NodeKind.ActorsQuery:
            case NodeKind.PersonsNode:
            case NodeKind.EventsQuery:
                return { ...query, source: filterTableSource(source, cohort) }
            default:
                return null
        }
    }
    if (!isInsightVizNode(query)) {
        return null
    }
    const source = query.source
    if (
        source.kind === NodeKind.WebOverviewQuery ||
        source.kind === NodeKind.WebStatsTableQuery ||
        ('series' in source && source.series?.some(isAnyDataWarehouseNode))
    ) {
        return null
    }
    const properties = source.properties
    return {
        ...query,
        source: {
            ...source,
            properties:
                Array.isArray(properties) || !properties
                    ? [...(properties ?? []), cohort]
                    : {
                          type: FilterLogicalOperator.And,
                          values: [properties, { type: FilterLogicalOperator.And, values: [cohort] }],
                      },
        },
    }
}

export function getNotebookCohortPlaylist(
    filters: RecordingUniversalFilters,
    id: number,
    collectionIds?: string[]
): RecordingUniversalFilters | null {
    const existing = filtersFromUniversalFilterGroups(filters)
    if (deriveOperand(filters.filter_group) === FilterLogicalOperator.Or && existing.length > 1) {
        return null
    }
    return {
        ...filters,
        ...(collectionIds ? { session_ids: collectionIds } : {}),
        filter_group: {
            type: FilterLogicalOperator.And,
            values: [{ type: FilterLogicalOperator.And, values: [...existing, notebookCohortProperty(id)] }],
        },
    }
}
