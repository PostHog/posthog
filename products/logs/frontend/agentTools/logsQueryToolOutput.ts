import { asRecord, getToolOutputRecord } from 'products/posthog_ai/frontend/api/tools'
import type { ToolCallMessage } from 'products/posthog_ai/frontend/api/types'

export interface LogRowSummary {
    severityText: string
    body: string
    timestamp: string
}

function asString(value: unknown): string {
    return typeof value === 'string' ? value : ''
}

function stringList(value: unknown): string[] {
    return Array.isArray(value) ? value.filter((v): v is string => typeof v === 'string') : []
}

/**
 * Pull the returned log rows out of a `query-logs` tool result. Returns an array (possibly empty when
 * the query matched nothing) or null when the output has no `results` array to render — in which case
 * the widget falls back to the generic card rather than showing an empty rows panel.
 */
export function extractLogRows(message: ToolCallMessage): LogRowSummary[] | null {
    const output = getToolOutputRecord(message)
    const results = output?.results
    if (!Array.isArray(results)) {
        return null
    }
    return results
        .map((row) => asRecord(row))
        .filter((row): row is Record<string, unknown> => row !== null)
        .map((row) => ({
            severityText: asString(row.severity_text),
            body: asString(row.body),
            timestamp: asString(row.timestamp),
        }))
}

/**
 * A one-line summary of what the query-logs call asked for, drawn from the tool's own input args, for
 * the card subtitle. The args are raw agent JSON, so every field is read defensively.
 */
export function describeLogsQuery(message: ToolCallMessage): string | undefined {
    const input = asRecord(message.innerInput)
    const query = asRecord(input?.query) ?? input
    if (!query) {
        return undefined
    }

    const services = stringList(query.serviceNames)
    const severities = stringList(query.severityLevels)
    const search = asString(query.searchTerm)
    const dateFrom = asString(asRecord(query.dateRange)?.date_from)

    const parts = [
        services.length > 0 ? services.join(', ') : '',
        severities.length > 0 ? severities.join(', ') : '',
        search ? `search: ${search}` : '',
        dateFrom,
    ].filter(Boolean)

    return parts.length > 0 ? parts.join(' · ') : undefined
}
