import { DateRange, LogsQuery } from '~/queries/schema/schema-general'
import { UniversalFiltersGroup } from '~/types'

export interface LogsViewerFilters {
    dateRange: DateRange
    searchTerm: LogsQuery['searchTerm']
    /**
     * Level and service selections reach the viewer through these fields (URL params, saved views,
     * alerts, embedding scenes), but it doesn't keep them: logsViewerFiltersLogic folds them into
     * `filterGroup` as `exact` log filters, which is where the facet rail and the chips bar both read
     * the selection from. Anything reading a viewer selection back out reads the filterGroup.
     */
    severityLevels?: LogsQuery['severityLevels']
    serviceNames?: LogsQuery['serviceNames']
    filterGroup: UniversalFiltersGroup
}

export interface LogsViewerConfig {
    filters: LogsViewerFilters
}

// The scope an embedding scene puts a viewer in. The full-screen modal re-applies it when it
// mounts a viewer under the same id, because the logics are keyed by id: opening full screen
// with these left out would rebind the same logics with no scope, so the maximised viewer would
// query project-wide and the embedded viewer would lose its scope once the modal closes.
export interface LogsViewerScope {
    initialFilters?: Partial<LogsViewerFilters>
    pinnedFilters?: UniversalFiltersGroup
    personId?: string
}
