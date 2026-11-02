import { uuid } from 'lib/utils/dom'

import { LogsQuery } from '~/queries/schema/schema-general'
import { PropertyFilterType } from '~/types'

import { FacetFilterTarget } from 'products/logs/frontend/components/LogsViewer/FacetRail/facetFilters'
import { COLUMN_FILTER_KEYS } from 'products/logs/frontend/components/LogsViewer/Filters/columnFilters'
import { MAX_ATTRIBUTE_COLUMN_WIDTH } from 'products/logs/frontend/components/VirtualizedLogsList/layoutUtils'
import { AttributeColumnConfig, ParsedLogMessage } from 'products/logs/frontend/types'

export type LogsColumnType =
    | 'timestamp'
    | 'level'
    | 'source'
    | 'trace_id'
    | 'span_id'
    | 'person'
    | 'session'
    | 'pattern'
    | 'message'
    | 'custom'

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
    /**
     * Reads the value off the row. Absent when the value only exists server-side (see `expression`),
     * or when the cell resolves it itself (see `person` and `session` below).
     */
    getValue?: (log: ParsedLogMessage) => string
    /** HogQL the server computes for this column, for values a log row does not carry. */
    expression?: string
}

// Most built-in column types resolve client-side from fields every log row already carries —
// they never hit the wire. `source` has no top-level row field; the service name rides in
// resource_attributes per OTel convention. `pattern` is the exception: it is a table column the
// row payload leaves out, so it rides the same wire mechanism as custom columns and is only
// fetched while the column is on screen. `person` and `session` have no fixed field either: the
// value sits under whichever attribute key the team's logs config names, so the cell resolves it
// per row (see IdentityCell) rather than a `getValue` here.
export const LOGS_COLUMN_REGISTRY: Record<Exclude<LogsColumnType, 'custom'>, BuiltInColumnDef> = {
    timestamp: { label: 'Timestamp', getValue: (log) => log.timestamp },
    level: { label: 'Level', getValue: (log) => log.severity_text },
    source: { label: 'Source', getValue: (log) => String(log.resource_attributes?.['service.name'] ?? '') },
    trace_id: { label: 'Trace ID', getValue: (log) => log.trace_id },
    span_id: { label: 'Span ID', getValue: (log) => log.span_id },
    person: { label: 'Person' },
    session: { label: 'Session' },
    pattern: { label: 'Pattern', expression: 'pattern' },
    message: { label: 'Message', getValue: (log) => log.body },
}

// Mirrors today's default table (timestamp + message) so the rendering cutover is invisible
// for users with no column customization.
export const DEFAULT_LOGS_COLUMNS: LogsColumnConfig[] = [
    { id: 'timestamp', type: 'timestamp' },
    { id: 'message', type: 'message' },
]

/**
 * Message is pinned to the end: it's the flex fill column, and the row FAB (whose scroll
 * buttons drive the message cell) anchors to the row's right edge.
 */
export function isPinnedColumn(column: LogsColumnConfig): boolean {
    return column.type === 'message'
}

/** Sort pinned columns last, stable otherwise. Returns the input untouched when already normalized. */
export function normalizeColumns(columns: LogsColumnConfig[]): LogsColumnConfig[] {
    const firstPinnedIndex = columns.findIndex(isPinnedColumn)
    if (firstPinnedIndex === -1 || columns.slice(firstPinnedIndex).every(isPinnedColumn)) {
        return columns
    }
    const rest = columns.filter((column) => !isPinnedColumn(column))
    return [...rest, ...columns.filter(isPinnedColumn)]
}

/** The one validation rule shared by the add-form and the draft: custom columns need an expression. */
export function customColumnExpressionError(type: LogsColumnType, expression: string | undefined): string | null {
    return type === 'custom' && !expression?.trim() ? 'Custom columns need an expression' : null
}

export function columnLabel(column: LogsColumnConfig): string {
    if (column.name) {
        return column.name
    }
    return column.type === 'custom' ? (column.expression ?? '') : LOGS_COLUMN_REGISTRY[column.type].label
}

/**
 * The HogQL the server must compute for a column, or undefined when the row already carries
 * the value. Keys the server's returned alias, so the wire list and the cell lookup stay in step.
 */
export function columnExpression(column: LogsColumnConfig): string | undefined {
    const expression = column.type === 'custom' ? column.expression : LOGS_COLUMN_REGISTRY[column.type].expression
    return expression?.trim() || undefined
}

/** Lower a column list to the `LogsQuery.customColumns` wire value. Client-side built-ins never hit the wire. */
export function columnsToCustomColumns(columns: LogsColumnConfig[]): LogsQuery['customColumns'] {
    // Deduplicated: the server aliases each expression by its hash, so sending one twice would
    // define the same alias twice and fail the whole query. Two columns sharing an expression
    // (two Pattern columns, or Pattern next to a hand-written `pattern`) read the same alias.
    const expressions = [
        ...new Set(columns.map(columnExpression).filter((expression): expression is string => !!expression)),
    ]
    // Undefined (not []) when there are no server-computed columns, so the query payload is
    // byte-identical to a pre-custom-columns query and cache keys are unaffected.
    return expressions.length > 0 ? expressions : undefined
}

/**
 * Shape columns to what the saved-view serializer accepts. Local column state can hold a
 * fractional width (from a touch drag, or an unbounded legacy width) and a whitespace-only
 * name (from the inline editor). The serializer rejects both, and one bad column fails the
 * whole save, so round and clamp widths and drop blank names.
 */
export function columnsForSavedView(columns: LogsColumnConfig[]): LogsColumnConfig[] {
    return columns.map(({ name, width, ...column }) => {
        const trimmedName = name?.trim()
        return {
            ...column,
            ...(trimmedName ? { name: trimmedName } : {}),
            ...(width !== undefined
                ? { width: Math.min(Math.max(Math.round(width), 1), MAX_ATTRIBUTE_COLUMN_WIDTH) }
                : {}),
        }
    })
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

const ATTRIBUTE_LOOKUP_PATTERN =
    /^if\(mapContains\(attributes, '((?:[^'\\]|\\[\s\S])*)'\), attributes\['\1'\], resource_attributes\['\1'\]\)$/

function attributeLookupKey(expression: string): string | null {
    const escaped = ATTRIBUTE_LOOKUP_PATTERN.exec(expression)?.[1]
    if (escaped === undefined) {
        return null
    }
    const key = escaped.replace(/\\([\s\S])/g, '$1')
    return attributeLookupExpression(key) === expression ? key : null
}

function shorthandKey(expression: string, prefix: 'attributes' | 'resource_attributes'): string | null {
    const key = expression.startsWith(`${prefix}.`) ? expression.slice(prefix.length + 1) : ''
    return key || null
}

export function customColumnFilterTarget(
    column: LogsColumnConfig,
    attributes: Record<string, unknown> | undefined,
    resourceAttributes: Record<string, unknown> | undefined
): FacetFilterTarget {
    const expression = column.expression?.trim() ?? ''

    const attributeKey = shorthandKey(expression, 'attributes')
    if (attributeKey) {
        return { key: attributeKey, type: PropertyFilterType.LogAttribute }
    }
    const resourceAttributeKey = shorthandKey(expression, 'resource_attributes')
    if (resourceAttributeKey) {
        return { key: resourceAttributeKey, type: PropertyFilterType.LogResourceAttribute }
    }

    const lookupKey = attributeLookupKey(expression)
    if (lookupKey !== null) {
        // Same check as the expression's mapContains, so the filter targets the map the cell read
        const readResourceMap =
            !(attributes && Object.hasOwn(attributes, lookupKey)) &&
            !!resourceAttributes &&
            Object.hasOwn(resourceAttributes, lookupKey)
        return {
            key: lookupKey,
            type: readResourceMap ? PropertyFilterType.LogResourceAttribute : PropertyFilterType.LogAttribute,
        }
    }

    if (COLUMN_FILTER_KEYS.has(expression)) {
        return { key: expression, type: PropertyFilterType.Log }
    }
    return { key: column.name ?? expression, type: PropertyFilterType.LogAttribute }
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
