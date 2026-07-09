import { uuid } from 'lib/utils/dom'

import { LogsQuery } from '~/queries/schema/schema-general'

import { AttributeColumnConfig, ParsedLogMessage } from 'products/logs/frontend/types'

export type LogsColumnType = 'timestamp' | 'level' | 'source' | 'trace_id' | 'span_id' | 'message' | 'custom'

export interface LogsColumnConfig {
    /** Stable identity for list operations (React keys, reorder). Never sent to the server. */
    id: string
    type: LogsColumnType
    /** Header label override. Defaults to the registry label (built-ins) or the expression (custom). */
    name?: string
    /**
     * Only meaningful for `type: 'custom'`: a source-prefixed shorthand (`attributes.<key>`,
     * `resource_attributes.<key>`, `body.<json.path>`) or a scalar HogQL expression, sent
     * verbatim in `LogsQuery.customColumns`. Column order is the array index.
     */
    expression?: string
    width?: number
}

interface BuiltInColumnDef {
    label: string
    getValue: (log: ParsedLogMessage) => string
}

// Built-in column types resolve client-side from fields every log row already carries —
// they never hit the wire. `source` has no top-level row field; the service name rides in
// resource_attributes per OTel convention.
export const LOGS_COLUMN_REGISTRY: Record<Exclude<LogsColumnType, 'custom'>, BuiltInColumnDef> = {
    timestamp: { label: 'Timestamp', getValue: (log) => log.timestamp },
    level: { label: 'Level', getValue: (log) => log.severity_text },
    source: { label: 'Source', getValue: (log) => String(log.resource_attributes?.['service.name'] ?? '') },
    trace_id: { label: 'Trace ID', getValue: (log) => log.trace_id },
    span_id: { label: 'Span ID', getValue: (log) => log.span_id },
    message: { label: 'Message', getValue: (log) => log.body },
}

// Mirrors today's default table (timestamp + message) so the rendering cutover is invisible
// for users with no column customization.
export const DEFAULT_LOGS_COLUMNS: LogsColumnConfig[] = [
    { id: 'timestamp', type: 'timestamp' },
    { id: 'message', type: 'message' },
]

export function columnLabel(column: LogsColumnConfig): string {
    if (column.name) {
        return column.name
    }
    return column.type === 'custom' ? (column.expression ?? '') : LOGS_COLUMN_REGISTRY[column.type].label
}

/** Lower a column list to the `LogsQuery.customColumns` wire value. Built-ins never hit the wire. */
export function columnsToCustomColumns(columns: LogsColumnConfig[]): LogsQuery['customColumns'] {
    const expressions = columns
        .map((column) => (column.type === 'custom' ? column.expression?.trim() : undefined))
        .filter((expression): expression is string => !!expression)
    // Undefined (not []) when there are no custom columns, so the query payload is
    // byte-identical to a pre-custom-columns query and cache keys are unaffected.
    return expressions.length > 0 ? expressions : undefined
}

function escapeHogQLString(value: string): string {
    return value.replace(/\\/g, '\\\\').replace(/'/g, "\\'")
}

/**
 * Expression preserving the legacy attribute-column lookup, which coalesced across both maps
 * (`log.attributes[key] ?? log.resource_attributes[key]`). The `attributes.<key>` shorthand
 * reads only one map, so a plain shorthand would render resource-attribute columns empty.
 */
export function attributeLookupExpression(key: string): string {
    const escaped = escapeHogQLString(key)
    return `if(mapContains(attributes, '${escaped}'), attributes['${escaped}'], resource_attributes['${escaped}'])`
}

/** Migrate the legacy persisted `attributeColumnsConfig` map to typed custom columns. */
export function migrateAttributeColumns(config: Record<string, AttributeColumnConfig>): LogsColumnConfig[] {
    return Object.entries(config)
        .sort(([, a], [, b]) => a.order - b.order)
        .map(([key, { width }]) => ({
            id: uuid(),
            type: 'custom' as const,
            name: key,
            expression: attributeLookupExpression(key),
            ...(width !== undefined ? { width } : {}),
        }))
}
