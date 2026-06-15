import { DateRange, LogsQuery } from '~/queries/schema/schema-general'
import { UniversalFiltersGroup } from '~/types'

export interface LogsViewerFilters {
    dateRange: DateRange
    searchTerm: LogsQuery['searchTerm']
    severityLevels: LogsQuery['severityLevels']
    serviceNames: LogsQuery['serviceNames']
    filterGroup: UniversalFiltersGroup
}

export interface LogsViewerConfig {
    filters: LogsViewerFilters
}
