import { DateRange, LogsQuery } from '@posthog/query-frontend/schema/schema-general'

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
