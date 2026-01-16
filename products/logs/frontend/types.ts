import { DateRange, LogsQuery } from '~/queries/schema/schema-general'
import { LogMessage } from '~/queries/schema/schema-general'
import { JsonType, UniversalFiltersGroup } from '~/types'

export interface LogsFilters {
    dateRange: DateRange
    searchTerm: LogsQuery['searchTerm']
    severityLevels: LogsQuery['severityLevels']
    serviceNames: LogsQuery['serviceNames']
    filterGroup: UniversalFiltersGroup
}

export interface LogsFiltersHistoryEntry {
    filters: LogsFilters
    timestamp: number
}

export type ParsedLogMessage = Omit<LogMessage, 'attributes'> & {
    attributes: Record<string, string>
    cleanBody: string
    parsedBody: JsonType | null
    originalLog: LogMessage
}

export type LogsOrderBy = 'earliest' | 'latest' | undefined

export interface AttributeColumnConfig {
    order: number
    width?: number
}
