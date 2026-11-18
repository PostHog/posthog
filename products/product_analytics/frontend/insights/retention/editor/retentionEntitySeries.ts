import { convertPropertyGroupToProperties } from 'lib/components/PropertyFilters/utils'
import {
    SeriesNode,
    isActionsSeriesNode,
    isEventsSeriesNode,
    isWarehouseSeriesNode,
    seriesNodeEntityType,
    toActionId,
} from 'scenes/insights/filters/ActionFilter/seriesNode'

import { NodeKind } from '~/queries/schema/schema-general'
import { EntityTypes, RetentionEntity } from '~/types'

const NODE_IDENTITY_KEYS = ['kind', 'version', 'event', 'id', 'nodes']

/** When the picker holds more than one row, the first row of the earliest type here is the one stored. */
const RETENTION_ENTITY_TYPES = [EntityTypes.EVENTS, EntityTypes.ACTIONS, EntityTypes.DATA_WAREHOUSE]

export function retentionEntityToSeries(entity: RetentionEntity | undefined): SeriesNode[] {
    if (!entity) {
        return []
    }
    const { type, id, order, uuid, ...shared } = entity
    if (Array.isArray(shared.properties)) {
        shared.properties = convertPropertyGroupToProperties(shared.properties)
    }

    if (type === EntityTypes.ACTIONS) {
        return [{ ...shared, kind: NodeKind.ActionsNode, id: toActionId(id) } as SeriesNode]
    }
    if (type === EntityTypes.DATA_WAREHOUSE) {
        // The table name is the node's key, and an older entity may carry it only as its `id`.
        const tableName = shared.table_name ?? (typeof id === 'string' ? id : undefined)
        return [
            { ...shared, kind: NodeKind.DataWarehouseNode, table_name: tableName, id: tableName ?? id } as SeriesNode,
        ]
    }
    return [{ ...shared, kind: NodeKind.EventsNode, event: id } as SeriesNode]
}

export function seriesToRetentionEntity(series: SeriesNode[]): RetentionEntity | undefined {
    for (const type of RETENTION_ENTITY_TYPES) {
        const order = series.findIndex((node) => seriesNodeEntityType(node) === type)
        if (order >= 0) {
            return seriesNodeToRetentionEntity(series[order], order)
        }
    }
    return undefined
}

function seriesNodeToRetentionEntity(node: SeriesNode, order: number): RetentionEntity {
    const shared = Object.fromEntries(Object.entries(node).filter(([key]) => !NODE_IDENTITY_KEYS.includes(key)))

    let id: RetentionEntity['id'] | null = null
    if (isEventsSeriesNode(node)) {
        id = node.event ?? null
    } else if (isActionsSeriesNode(node)) {
        id = node.id
    } else if (isWarehouseSeriesNode(node)) {
        id = node.table_name
    }

    return { ...shared, id, type: seriesNodeEntityType(node), order } as RetentionEntity
}
