import { useMemo } from 'react'

import { LogsViewer } from 'products/logs/frontend/components/LogsViewer'
import { LogsViewerFilters } from 'products/logs/frontend/components/LogsViewer/config/types'
import { SURROUNDING_LOGS_WINDOW_MINUTES, buildDateRangeAround } from 'products/logs/frontend/utils'

export interface SurroundingLogsPanelProps {
    /** Keys the embedded viewer's logics and its persisted display settings. */
    id: string
    /** Centre of the window the panel opens on. Without one the viewer falls back to its own default range. */
    timestamp?: string
    /** Narrows the panel to one session. Leave unset to show every log in the window. */
    sessionId?: string
}

/**
 * An embedded logs viewer opened on the minutes around one event, for products that surface logs
 * next to something else (an exception, a span). The viewer keeps its own filter bar, so this only
 * picks the starting scope.
 */
export function SurroundingLogsPanel({ id, timestamp, sessionId }: SurroundingLogsPanelProps): JSX.Element {
    // logsViewerFiltersLogic compares this prop by identity and re-applies the filters whenever it
    // changes, so an inline object would reset the user's filters on every render.
    const initialFilters = useMemo<Partial<LogsViewerFilters> | undefined>(
        () => (timestamp ? { dateRange: buildDateRangeAround(timestamp, SURROUNDING_LOGS_WINDOW_MINUTES) } : undefined),
        [timestamp]
    )

    return (
        <LogsViewer
            id={id}
            initialFilters={initialFilters}
            sessionId={sessionId}
            showFullScreenButton={false}
            defaultFacetRailCollapsed
            defaultSparklineCollapsed
        />
    )
}
