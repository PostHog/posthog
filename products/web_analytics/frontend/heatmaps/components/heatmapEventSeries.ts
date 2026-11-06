import { HeatmapEventFilter } from 'lib/components/heatmaps/types'
import { convertPropertyGroupToProperties } from 'lib/components/PropertyFilters/utils'
import { SeriesNode, isEventsSeriesNode } from 'scenes/insights/filters/ActionFilter/seriesNode'

import { NodeKind } from '~/queries/schema/schema-general'
import { EntityTypes } from '~/types'

const NODE_IDENTITY_KEYS = ['kind', 'version', 'event', 'id', 'nodes']

// The `events` request parameter is the JSON of these entries, so their key order is part of the wire format.
export function heatmapEventFiltersToSeries(events: HeatmapEventFilter[] | undefined): SeriesNode[] {
    return [...(events ?? [])]
        .sort((a, b) => (a.order ?? 0) - (b.order ?? 0))
        .map(({ type, id, order, ...shared }) => {
            if (Array.isArray(shared.properties)) {
                shared.properties = convertPropertyGroupToProperties(shared.properties)
            }
            return { ...shared, kind: NodeKind.EventsNode, event: id } as SeriesNode
        })
}

export function seriesToHeatmapEventFilters(series: SeriesNode[]): HeatmapEventFilter[] {
    const filters: HeatmapEventFilter[] = []
    series.forEach((node, order) => {
        if (isEventsSeriesNode(node)) {
            const shared = Object.fromEntries(Object.entries(node).filter(([key]) => !NODE_IDENTITY_KEYS.includes(key)))
            filters.push({ ...shared, id: node.event ?? null, type: EntityTypes.EVENTS, order })
        }
    })
    return filters
}
