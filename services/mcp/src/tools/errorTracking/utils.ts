import { z } from 'zod'

export const dateRangeSchema = z
    .object({
        date_from: z.string().optional(),
        date_to: z.string().nullable().optional(),
    })
    .optional()

export const propertyFilterSchema = z.object({
    key: z.string().describe('Property key, for example $browser, $current_url, email, or a HogQL expression.'),
    type: z
        .enum(['event', 'person', 'session', 'group', 'cohort', 'hogql', 'feature', 'flag'])
        .describe('Property namespace to filter. Most exception event filters use event, person, or session.'),
    operator: z
        .enum([
            'exact',
            'is_not',
            'icontains',
            'not_icontains',
            'regex',
            'not_regex',
            'gt',
            'lt',
            'is_date_exact',
            'is_date_before',
            'is_date_after',
            'is_set',
            'is_not_set',
            'in',
            'not_in',
            'flag_evaluates_to',
        ])
        .optional()
        .describe('Comparison operator. Omit for hogql filters.'),
    value: z.union([z.string(), z.number(), z.boolean(), z.array(z.string())]).optional(),
    group_type_index: z.coerce.number().int().optional(),
})

export type PropertyFilter = z.infer<typeof propertyFilterSchema>

export function asRecord(value: unknown): Record<string, unknown> | undefined {
    return value && typeof value === 'object' && !Array.isArray(value) ? (value as Record<string, unknown>) : undefined
}

export function compactObject(record: Record<string, unknown>): Record<string, unknown> {
    return Object.fromEntries(
        Object.entries(record).filter(([, value]) => {
            if (value === undefined || value === null) {
                return false
            }
            if (Array.isArray(value)) {
                return value.length > 0
            }
            if (typeof value === 'object') {
                return Object.keys(value as Record<string, unknown>).length > 0
            }
            return true
        })
    )
}

export function escapeHogQLString(value: string): string {
    return value.replace(/\\/g, '\\\\').replace(/'/g, "\\'")
}

export function escapeHogQLLikePattern(value: string): string {
    // Escape LIKE wildcards first, then escape the resulting HogQL string literal.
    const likeEscaped = value.replace(/\\/g, '\\\\').replace(/%/g, '\\%').replace(/_/g, '\\_')
    return escapeHogQLString(likeEscaped)
}

export function normalizeColumn(column: unknown): string {
    if (typeof column === 'string') {
        return column
    }
    if (column && typeof column === 'object') {
        const record = column as Record<string, unknown>
        for (const key of ['key', 'name', 'id', 'field']) {
            if (typeof record[key] === 'string') {
                return record[key] as string
            }
        }
    }
    return ''
}

export function getPageInfo(
    data: Record<string, unknown>,
    limit: number,
    offset: number
): { hasMore: boolean; nextOffset?: number } {
    const rawRows = Array.isArray(data.results) ? data.results : []
    const hasMore = Boolean(data.hasMore) || rawRows.length > limit
    return hasMore ? { hasMore, nextOffset: offset + limit } : { hasMore }
}
