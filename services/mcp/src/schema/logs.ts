import { z } from 'zod'

export const LogSeverityLevel = z.enum(['trace', 'debug', 'info', 'warn', 'error', 'fatal'])
export type LogSeverityLevel = z.infer<typeof LogSeverityLevel>

export const LogsQueryInputSchema = z.object({
    dateFrom: z.string().describe('Start of date range (ISO 8601 format, e.g., "2024-01-01T00:00:00Z")'),
    dateTo: z.string().describe('End of date range (ISO 8601 format, e.g., "2024-01-02T00:00:00Z")'),
    severityLevels: z
        .array(LogSeverityLevel)
        .optional()
        .describe('Filter by severity levels (trace, debug, info, warn, error, fatal)'),
    serviceNames: z.array(z.string()).optional().describe('Filter by service names'),
    searchTerm: z.string().optional().describe('Free text search term to filter logs'),
    orderBy: z.enum(['latest', 'earliest']).optional().describe('Order results by timestamp (default: latest)'),
    limit: z.number().int().min(1).max(1000).optional().describe('Maximum number of results (1-1000, default: 100)'),
    after: z.string().optional().describe('Cursor for pagination (from previous response nextCursor)'),
})

export type LogsQueryInput = z.infer<typeof LogsQueryInputSchema>

export const LogsListAttributesInputSchema = z.object({
    search: z.string().optional().describe('Search filter for attribute names'),
    attributeType: z
        .enum(['log', 'resource'])
        .optional()
        .describe(
            'Type of attributes to list: "log" for log attributes, "resource" for resource attributes (default: log)'
        ),
    limit: z.number().int().min(1).max(100).optional().describe('Maximum number of results (1-100, default: 100)'),
    offset: z.number().int().min(0).optional().describe('Offset for pagination (default: 0)'),
})

export type LogsListAttributesInput = z.infer<typeof LogsListAttributesInputSchema>

export const LogsListAttributeValuesInputSchema = z.object({
    key: z.string().describe('The attribute key to get values for'),
    attributeType: z
        .enum(['log', 'resource'])
        .optional()
        .describe('Type of attribute: "log" for log attributes, "resource" for resource attributes (default: log)'),
    search: z.string().optional().describe('Search filter for attribute values'),
})

export type LogsListAttributeValuesInput = z.infer<typeof LogsListAttributeValuesInputSchema>

export interface LogEntry {
    uuid: string
    timestamp: string
    body: string
    level: string
    severity_text?: string
    severity_number?: number
    trace_id?: string
    span_id?: string
    service_name?: string
    attributes?: Record<string, unknown>
    resource_attributes?: Record<string, unknown>
}

export interface LogsQueryResponse {
    results: LogEntry[]
    hasMore: boolean
    nextCursor: string | null
}

export interface LogAttribute {
    name: string
    propertyFilterType: string
}

export interface LogsListAttributesResponse {
    results: LogAttribute[]
    count: number
}

export interface LogAttributeValue {
    id: string
    name: string
}
