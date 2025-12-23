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

export const LogEntrySchema = z.object({
    uuid: z.string(),
    timestamp: z.string(),
    body: z.string(),
    level: z.string(),
    severity_text: z.string().optional(),
    severity_number: z.number().optional(),
    trace_id: z.string().optional(),
    span_id: z.string().optional(),
    service_name: z.string().optional(),
    attributes: z.record(z.any()).optional(),
    resource_attributes: z.record(z.any()).optional(),
})

export type LogEntry = z.infer<typeof LogEntrySchema>

export const LogsQueryResponseSchema = z.object({
    results: z.array(LogEntrySchema),
    hasMore: z.boolean(),
    nextCursor: z.string().nullable(),
})

export type LogsQueryResponse = z.infer<typeof LogsQueryResponseSchema>

export const LogAttributeSchema = z.object({
    name: z.string(),
    propertyFilterType: z.string(),
})

export type LogAttribute = z.infer<typeof LogAttributeSchema>

export const LogsListAttributesResponseSchema = z.object({
    results: z.array(LogAttributeSchema),
    count: z.number(),
})

export type LogsListAttributesResponse = z.infer<typeof LogsListAttributesResponseSchema>

export const LogAttributeValueSchema = z.object({
    id: z.string(),
    name: z.string(),
})

export type LogAttributeValue = z.infer<typeof LogAttributeValueSchema>
