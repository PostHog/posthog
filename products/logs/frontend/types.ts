import { LogMessage } from '~/queries/schema/schema-general'
import { JsonType } from '~/types'

export type ParsedLogMessage = LogMessage & { cleanBody: string; parsedBody: JsonType | null }

export type LogsOrderBy = 'earliest' | 'latest' | undefined

export interface AttributeColumnConfig {
    order: number
    width?: number
}
