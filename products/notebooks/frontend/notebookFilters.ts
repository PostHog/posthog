import { hashString } from 'lib/components/MarkdownNotebook/utils'
import { deriveOperand } from 'scenes/session-recordings/filters/recordingsQueryConversions'
import { filtersFromUniversalFilterGroups } from 'scenes/session-recordings/utils'

import { isAnyDataWarehouseNode, isDataTableNode, isInsightVizNode } from '~/queries/schema/node-guards'
import {
    ActorsQuery,
    DataTableNode,
    DateRange,
    InsightVizNode,
    Node,
    NodeKind,
    PersonsNode,
} from '~/queries/schema/schema-general'
import {
    AnyPropertyFilter,
    FilterLogicalOperator,
    LegacyRecordingFilters,
    PropertyFilterType,
    PropertyGroupFilter,
    RecordingUniversalFilters,
} from '~/types'

export interface NotebookFilters {
    properties: AnyPropertyFilter[]
    dateRange?: Pick<DateRange, 'date_from' | 'date_to'>
}

export function notebookFilteredBlockKey(shortId: string, nodeId: string, filters: NotebookFilters): string {
    return `notebook-filtered-${shortId}-${nodeId}-${hashString(JSON.stringify(filters))}`
}

function filterPeople<T extends ActorsQuery | PersonsNode>(
    source: T,
    { dateRange, properties }: NotebookFilters
): T | null {
    if (
        dateRange ||
        (source.kind === NodeKind.ActorsQuery && source.source) ||
        !properties.every((p) => p.type === PropertyFilterType.Person || p.type === PropertyFilterType.Cohort)
    ) {
        return null
    }
    return { ...source, fixedProperties: [...(source.fixedProperties ?? []), ...properties], offset: 0 }
}

function filterTable(table: DataTableNode, { properties, dateRange }: NotebookFilters): DataTableNode | null {
    const source = table.source
    switch (source?.kind) {
        case NodeKind.EventsQuery:
            return {
                ...table,
                source: {
                    ...source,
                    ...(dateRange && {
                        after: dateRange.date_from ?? undefined,
                        before: dateRange.date_to ?? undefined,
                    }),
                    fixedProperties: [...(source.fixedProperties ?? []), ...properties],
                    offset: 0,
                },
            }
        case NodeKind.ActorsQuery:
        case NodeKind.PersonsNode: {
            const people = filterPeople(source, { dateRange, properties })
            return people && { ...table, source: people }
        }
        default:
            return null
    }
}

function usesWarehouseData(source: InsightVizNode['source']): boolean {
    if (source.kind === NodeKind.RetentionQuery) {
        return [source.retentionFilter.targetEntity, source.retentionFilter.returningEntity].some(
            (entity) => entity?.type === 'data_warehouse'
        )
    }
    return 'series' in source && !!source.series?.some(isAnyDataWarehouseNode)
}

function combineProperties(
    authored: AnyPropertyFilter[] | PropertyGroupFilter | undefined,
    properties: AnyPropertyFilter[]
): AnyPropertyFilter[] | PropertyGroupFilter | undefined {
    if (!properties.length) {
        return authored
    }
    if (!authored || Array.isArray(authored)) {
        return [...(authored ?? []), ...properties]
    }
    return {
        type: FilterLogicalOperator.And,
        values: [authored, { type: FilterLogicalOperator.And, values: properties }],
    }
}

export function getFilteredNotebookQuery(
    query: Node | null | undefined,
    filters: NotebookFilters
): InsightVizNode | DataTableNode | null {
    if (isDataTableNode(query)) {
        return filterTable(query, filters)
    }
    if (!isInsightVizNode(query) || !query.source) {
        return null
    }
    const source = query.source
    if (
        source.kind === NodeKind.WebOverviewQuery ||
        source.kind === NodeKind.WebStatsTableQuery ||
        usesWarehouseData(source)
    ) {
        return null
    }
    return {
        ...query,
        source: {
            ...source,
            properties: combineProperties(source.properties, filters.properties),
            ...(filters.dateRange && { dateRange: { ...source.dateRange, ...filters.dateRange, explicitDate: false } }),
        },
    }
}

export interface NotebookPlaylistCollection {
    ids: string[] | undefined
    savedFilters: LegacyRecordingFilters | RecordingUniversalFilters
}

export function getFilteredNotebookPlaylist(
    authored: RecordingUniversalFilters,
    filters: NotebookFilters,
    collection?: NotebookPlaylistCollection
): RecordingUniversalFilters | null {
    const existing = filtersFromUniversalFilterGroups(authored)
    if (
        filters.properties.length &&
        deriveOperand(authored.filter_group) === FilterLogicalOperator.Or &&
        existing.length > 1
    ) {
        return null
    }
    const collectionIds = collection?.ids ?? []
    return {
        ...authored,
        ...(collection && {
            session_ids: authored.session_ids?.filter((id) => collectionIds.includes(id)) ?? collectionIds,
            // An absent date_from would restore the API's three-day default for the events lookup.
            date_from: collection.savedFilters.date_from ?? '',
            date_to: collection.savedFilters.date_to ?? null,
            duration:
                'duration' in collection.savedFilters || collection.savedFilters.session_recording_duration
                    ? authored.duration
                    : [],
        }),
        ...filters.dateRange,
        ...(filters.properties.length > 0 && {
            filter_group: {
                type: FilterLogicalOperator.And,
                values: [{ type: FilterLogicalOperator.And, values: [...existing, ...filters.properties] }],
            },
        }),
    }
}
