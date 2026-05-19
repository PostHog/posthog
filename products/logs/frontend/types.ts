import { LogMessage } from '~/queries/schema/schema-general'
import { JsonType } from '~/types'

import { LogsViewerFilters } from 'products/logs/frontend/components/LogsViewer/config/types'

export interface LogsFiltersHistoryEntry {
    filters: LogsViewerFilters
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
