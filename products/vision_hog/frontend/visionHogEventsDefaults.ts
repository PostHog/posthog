import { defaultDataTableColumns } from '~/queries/nodes/DataTable/utils'
import { DataTableNode, NodeKind } from '~/queries/schema/schema-general'
import { AnyPropertyFilter, PropertyFilterType, PropertyOperator } from '~/types'

export const getDefaultVisionHogEventsQuery = (additionalProperties?: AnyPropertyFilter[]): DataTableNode => {
    // Define the camera filter to only include events with distinct_id starting with "camera:"
    const cameraFilter: AnyPropertyFilter = {
        key: 'distinct_id',
        value: 'camera:',
        operator: PropertyOperator.IContains,
        type: PropertyFilterType.Event,
    }

    // Combine the camera filter with any additional properties
    const properties = additionalProperties ? [cameraFilter, ...additionalProperties] : [cameraFilter]

    return {
        kind: NodeKind.DataTableNode,
        full: true,
        source: {
            kind: NodeKind.EventsQuery,
            select: defaultDataTableColumns(NodeKind.EventsQuery),
            orderBy: ['timestamp DESC'],
            after: '-24h',
            properties,
            modifiers: {
                usePresortedEventsTable: true,
            },
        },
        propertiesViaUrl: true,
        showSavedQueries: true,
        showPersistentColumnConfigurator: true,
    }
}
