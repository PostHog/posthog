import { z } from 'zod'

import type { Context, ToolBase } from '@/tools/types'

const dateRangeSchema = z
    .object({
        date_from: z.string().optional(),
        date_to: z.string().nullable().optional(),
    })
    .optional()

const propertyFilterSchema = z.object({
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

const schema = z.object({
    issueId: z
        .string()
        .regex(/^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$/)
        .describe('Error tracking issue ID.'),
    dateRange: dateRangeSchema.default({ date_from: '-7d' }).optional(),
    filterTestAccounts: z.coerce.boolean().default(true).optional(),
    filterGroup: z.array(propertyFilterSchema).default([]).optional(),
    searchQuery: z.string().max(500).optional(),
    orderDirection: z.enum(['ASC', 'DESC']).default('DESC').optional(),
    limit: z.coerce.number().int().min(1).max(20).default(1).optional(),
    offset: z.coerce.number().int().min(0).default(0).optional(),
})

type Params = z.infer<typeof schema>

const PROPERTY_SELECTS = [
    'properties.$exception_type',
    'properties.$exception_message',
    'properties.$exception_value',
    'properties.$exception_list',
    'properties.$exception_fingerprint',
    'properties.$exception_issue_id',
    'properties.$lib',
    'properties.$browser',
    'properties.$browser_version',
    'properties.$os',
    'properties.$os_version',
    'properties.$current_url',
    'properties.$sentry_url',
    'properties.$exception_synthetic',
]

const SELECTS = ['uuid', 'timestamp', 'distinct_id', ...PROPERTY_SELECTS]

const SEARCH_PROPERTIES = [
    'properties.$exception_type',
    'properties.$exception_message',
    'properties.$exception_value',
    'properties.$current_url',
]

function escapeHogQLString(value: string): string {
    return value.replace(/\\/g, '\\\\').replace(/'/g, "\\'")
}

function escapeLikePattern(value: string): string {
    return escapeHogQLString(value).replace(/%/g, '\\%').replace(/_/g, '\\_')
}

function normalizeColumn(column: unknown): string {
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

function propertyName(select: string): string | null {
    return select.startsWith('properties.') ? select.slice('properties.'.length) : null
}

function mapEventRow(row: unknown, columns: string[]): Record<string, unknown> {
    const values = Array.isArray(row) ? row : columns.map((column) => (row as Record<string, unknown>)?.[column])
    const event: Record<string, unknown> = { properties: {} }
    const properties = event.properties as Record<string, unknown>

    for (let i = 0; i < columns.length; i++) {
        const column = columns[i]
        const value = values[i]
        if (!column || value === undefined || value === null) {
            continue
        }
        const prop = propertyName(column)
        if (prop) {
            properties[prop] = value
        } else {
            event[column] = value
        }
    }

    return event
}

function buildWhere(params: Params): string[] {
    const issueId = escapeHogQLString(params.issueId)
    const where = [`(issue_id = '${issueId}' OR properties.$exception_issue_id = '${issueId}')`]

    if (params.searchQuery) {
        const search = escapeLikePattern(params.searchQuery)
        const chunks = SEARCH_PROPERTIES.map((prop) => `ilike(toString(${prop}), '%${search}%')`)
        where.push(`(${chunks.join(' OR ')})`)
    }

    return where
}

export const queryIssueEventsHandler: ToolBase<typeof schema>['handler'] = async (
    context: Context,
    rawParams: Params
) => {
    const params = schema.parse(rawParams)
    const projectId = await context.stateManager.getProjectId()
    const baseUrl = context.api.getProjectBaseUrl(projectId)

    const query = {
        kind: 'EventsQuery',
        event: '$exception',
        select: SELECTS,
        where: buildWhere(params),
        properties: params.filterGroup,
        filterTestAccounts: params.filterTestAccounts,
        after: params.dateRange?.date_from,
        before: params.dateRange?.date_to ?? undefined,
        orderBy: [`timestamp ${params.orderDirection}`],
        limit: params.limit,
        offset: params.offset,
        tags: { productKey: 'error_tracking' },
    }

    const data = await context.api.query({ projectId }).runQuery({ query })
    const columns = Array.isArray(data.columns) ? data.columns.map(normalizeColumn) : SELECTS
    const results = Array.isArray(data.results) ? data.results.map((row: unknown) => mapEventRow(row, columns)) : []
    const nextOffset = data.hasMore
        ? (data.offset ?? params.offset ?? 0) + (data.limit ?? params.limit ?? 0)
        : undefined

    return {
        results,
        hasMore: data.hasMore,
        limit: data.limit ?? params.limit,
        offset: data.offset ?? params.offset,
        nextOffset,
        _posthogUrl: `${baseUrl}/error_tracking/${encodeURIComponent(params.issueId)}`,
    }
}

const tool = (): ToolBase<typeof schema> => ({
    name: 'query-error-tracking-issue-events',
    schema,
    handler: queryIssueEventsHandler,
    _meta: {
        ui: { resourceUri: 'ui://posthog/error-details.html' },
    },
})

export default tool
