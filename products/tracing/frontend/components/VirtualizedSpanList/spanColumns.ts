import type { TracingOrderBy } from '../../tracingFiltersLogic'
import type { Span } from '../../types'
import { MIN_COLUMN_WIDTH, ResizableColumnSpec } from '../TableColumns/columnWidths'

export type BuiltInSpanColumnType = 'timestamp' | 'name' | 'service' | 'kind' | 'duration' | 'status' | 'traceId'

export type SpanColumnConfig = { type: BuiltInSpanColumnType } | { type: 'attribute'; attributeKey: string }

export type SpanColumnType = SpanColumnConfig['type']

interface BuiltInSpanColumn {
    label: string
    width: number
    sortKey?: TracingOrderBy
}

// pinned: these keys are also the stored-width keys, so a rename resets everyone's widths.
export const SPAN_COLUMN_REGISTRY: Record<BuiltInSpanColumnType, BuiltInSpanColumn> = {
    timestamp: { label: 'Timestamp', width: 215, sortKey: 'timestamp' },
    name: { label: 'Name', width: 320 },
    service: { label: 'Service', width: 200 },
    kind: { label: 'Kind', width: 90 },
    duration: { label: 'Duration', width: 90, sortKey: 'duration' },
    status: { label: 'Status', width: 80 },
    traceId: { label: 'Trace ID', width: 140 },
}

export const DEFAULT_ATTRIBUTE_COLUMN_WIDTH = 200

export const DEFAULT_SPAN_COLUMNS: SpanColumnConfig[] = [
    { type: 'timestamp' },
    { type: 'name' },
    { type: 'service' },
    { type: 'kind' },
    { type: 'duration' },
    { type: 'status' },
    { type: 'traceId' },
]

/** The prefix keeps an attribute named `name` from colliding with the built-in `name` column. */
export function spanColumnKey(column: SpanColumnConfig): string {
    return column.type === 'attribute' ? `attr:${column.attributeKey}` : column.type
}

export function spanColumnLabel(column: SpanColumnConfig): string {
    return column.type === 'attribute' ? column.attributeKey : SPAN_COLUMN_REGISTRY[column.type].label
}

export function spanColumnSortKey(column: SpanColumnConfig): TracingOrderBy | undefined {
    return column.type === 'attribute' ? undefined : SPAN_COLUMN_REGISTRY[column.type].sortKey
}

export function spanAttributeValue(span: Span, attributeKey: string): string {
    return span.attributes?.[attributeKey] ?? span.resource_attributes?.[attributeKey] ?? ''
}

export function availableBuiltInColumns(columns: SpanColumnConfig[]): BuiltInSpanColumnType[] {
    const present = new Set(columns.map(spanColumnKey))
    return (Object.keys(SPAN_COLUMN_REGISTRY) as BuiltInSpanColumnType[]).filter((type) => !present.has(type))
}

export function addSpanColumn(columns: SpanColumnConfig[], column: SpanColumnConfig): SpanColumnConfig[] {
    const key = spanColumnKey(column)
    return columns.some((existing) => spanColumnKey(existing) === key) ? columns : [...columns, column]
}

export function removeSpanColumn(columns: SpanColumnConfig[], key: string): SpanColumnConfig[] {
    return columns.filter((column) => spanColumnKey(column) !== key)
}

export function moveSpanColumn(columns: SpanColumnConfig[], key: string, direction: 'up' | 'down'): SpanColumnConfig[] {
    const index = columns.findIndex((column) => spanColumnKey(column) === key)
    const target = direction === 'up' ? index - 1 : index + 1
    if (index === -1 || target < 0 || target >= columns.length) {
        return columns
    }
    const next = [...columns]
    ;[next[index], next[target]] = [next[target], next[index]]
    return next
}

export function toggleSpanAttributeColumn(columns: SpanColumnConfig[], attributeKey: string): SpanColumnConfig[] {
    const key = spanColumnKey({ type: 'attribute', attributeKey })
    return columns.some((column) => spanColumnKey(column) === key)
        ? removeSpanColumn(columns, key)
        : addSpanColumn(columns, { type: 'attribute', attributeKey })
}

/** Filters what an older version persisted, so editing the registry cannot throw on load. */
export function normalizeSpanColumns(stored: unknown): SpanColumnConfig[] {
    if (!Array.isArray(stored)) {
        return DEFAULT_SPAN_COLUMNS
    }
    const normalized = stored.reduce<SpanColumnConfig[]>((columns, entry) => {
        if (!entry || typeof entry !== 'object') {
            return columns
        }
        const { type, attributeKey } = entry as { type?: unknown; attributeKey?: unknown }
        if (type === 'attribute') {
            return typeof attributeKey === 'string' && attributeKey
                ? addSpanColumn(columns, { type, attributeKey })
                : columns
        }
        return typeof type === 'string' && type in SPAN_COLUMN_REGISTRY
            ? addSpanColumn(columns, { type: type as BuiltInSpanColumnType })
            : columns
    }, [])
    return normalized.length > 0 ? normalized : DEFAULT_SPAN_COLUMNS
}

/** The error badge is not configurable, because its flagged feature owns whether it renders. */
export function toSpanColumnSpecs(
    columns: SpanColumnConfig[],
    { showSpanErrors }: { showSpanErrors: boolean }
): ResizableColumnSpec[] {
    // Without a growing column the table stops filling the viewport, so the last one takes over.
    const growColumn = columns.find((column) => column.type === 'name') ?? columns[columns.length - 1]
    const growKey = growColumn && spanColumnKey(growColumn)

    const specs: ResizableColumnSpec[] = columns.map((column) => {
        const key = spanColumnKey(column)
        return {
            key,
            width:
                column.type === 'attribute' ? DEFAULT_ATTRIBUTE_COLUMN_WIDTH : SPAN_COLUMN_REGISTRY[column.type].width,
            grow: key === growKey || undefined,
        }
    })

    if (showSpanErrors) {
        // The error badge holds its width on rows with no errors so the columns beside it stay
        // aligned down the page as counts arrive.
        specs.push({ key: 'spanErrors', width: MIN_COLUMN_WIDTH })
    }
    specs.push({ key: 'actions', width: 130 })
    return specs
}
