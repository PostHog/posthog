import { DateRange, LogsQuery } from '~/queries/schema/schema-general'
import { UniversalFiltersGroup } from '~/types'

import { Column } from 'products/logs/frontend/components/LogsViewer/columns/types'

export interface LogsViewerFilters {
    dateRange: DateRange
    searchTerm: LogsQuery['searchTerm']
    severityLevels: LogsQuery['severityLevels']
    serviceNames: LogsQuery['serviceNames']
    filterGroup: UniversalFiltersGroup
}

export type LogsViewerConfigVersion = 1

export interface LogsViewerConfig {
    version: LogsViewerConfigVersion
    filters: LogsViewerFilters
    orderBy: LogsQuery['orderBy']
    columns: Record<string, Column>
}
