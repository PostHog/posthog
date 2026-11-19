import { FEATURE_FLAG_CALLED_EVENT } from 'scenes/feature-flags/flagEvaluationsTable'

import { DataTableNode, NodeKind } from '~/queries/schema/schema-general'

export function createInitialFlagCallsPayload(personId: string): DataTableNode {
    return {
        kind: NodeKind.DataTableNode,
        full: true,
        // EventsQueryRunner reads flag_evaluations only while the event filter is exactly $feature_flag_called.
        // Another event, an action, a saved table view, or a saved query would send the list back to events.
        showEventFilter: false,
        showEventsFilter: false,
        showTableViews: false,
        showSavedQueries: false,
        showSavedFilters: false,
        source: {
            kind: NodeKind.EventsQuery,
            select: [
                '*',
                'properties.$feature_flag',
                'properties.$feature_flag_response',
                'coalesce(properties.$current_url, properties.$screen_name) -- Url / Screen',
                'properties.$lib',
                'timestamp',
            ],
            event: FEATURE_FLAG_CALLED_EVENT,
            personId,
            after: '-24h',
        },
    }
}
