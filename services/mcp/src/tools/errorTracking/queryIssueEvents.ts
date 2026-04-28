import { z } from 'zod'

import type { Context, ToolBase } from '@/tools/types'

import { type ExceptionVerbosity, normalizeErrorTrackingProperty } from './exceptionProperties'
import {
    dateRangeSchema,
    escapeHogQLLikePattern,
    escapeHogQLString,
    getPageInfo,
    normalizeColumn,
    propertyFilterSchema,
} from './utils'

const schema = z.object({
    issueId: z
        .string()
        .regex(/^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$/)
        .describe('Error tracking issue ID.'),
    dateRange: dateRangeSchema
        .default({ date_from: '-7d' })
        .optional()
        .describe(
            'Scopes which sample exception events are returned for this issue. Defaults to the last 7 days; widen it when you need older occurrences.'
        ),
    filterTestAccounts: z.coerce
        .boolean()
        .default(true)
        .optional()
        .describe('When true, exclude internal/test account data from results. Defaults to true.'),
    filterGroup: z.array(propertyFilterSchema).default([]).optional(),
    searchQuery: z.string().max(500).optional(),
    orderDirection: z.enum(['ASC', 'DESC']).default('DESC').optional(),
    limit: z.coerce.number().int().min(1).max(20).default(1).optional(),
    offset: z.coerce.number().int().min(0).default(0).optional(),
    verbosity: z
        .enum(['summary', 'stack', 'raw'])
        .default('summary')
        .optional()
        .describe(
            'Controls exception detail size: summary omits stack frames, stack includes parsed stack frames, raw preserves parsed exception fields. Defaults to summary.'
        ),
    onlyAppFrames: z.coerce
        .boolean()
        .default(true)
        .optional()
        .describe(
            'When true, include only stack frames marked in_app and suppress vendor/library frames. Defaults to true.'
        ),
})

type Params = z.infer<typeof schema>
type MapEventOptions = {
    verbosity: ExceptionVerbosity
    onlyAppFrames: boolean
}

const PROPERTY_SELECTS = [
    'properties.$exception_types',
    'properties.$exception_values',
    'properties.$exception_list',
    'properties.$exception_fingerprint',
    'properties.$exception_issue_id',
    'properties.$session_id',
    'properties.$lib',
    'properties.$browser',
    'properties.$browser_version',
    'properties.$os',
    'properties.$os_version',
    'properties.$current_url',
]

const SELECTS = ['uuid', 'timestamp', 'distinct_id', ...PROPERTY_SELECTS]

const SEARCH_PROPERTIES = ['properties.$exception_types', 'properties.$exception_values', 'properties.$current_url']

function propertyName(select: string): string | null {
    return select.startsWith('properties.') ? select.slice('properties.'.length) : null
}

function mapEventRow(row: unknown, columns: string[], options: MapEventOptions): Record<string, unknown> {
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
            properties[prop] = normalizeErrorTrackingProperty(prop, value, options)
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
        const search = escapeHogQLLikePattern(params.searchQuery)
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
    const limit = params.limit ?? 1
    const offset = params.offset ?? 0
    const verbosity = params.verbosity ?? 'summary'
    const onlyAppFrames = params.onlyAppFrames ?? true

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
        limit,
        offset,
        tags: { productKey: 'error_tracking' },
    }

    const data = await context.api.query({ projectId }).runQuery({ query })
    const columns = Array.isArray(data.columns) ? data.columns.map(normalizeColumn) : SELECTS
    const rawResults = Array.isArray(data.results) ? data.results : []
    const mapOptions = {
        verbosity,
        onlyAppFrames,
    }
    const results = rawResults.slice(0, limit).map((row: unknown) => mapEventRow(row, columns, mapOptions))
    const pageInfo = getPageInfo(data as Record<string, unknown>, limit, offset)

    return {
        results,
        hasMore: pageInfo.hasMore,
        limit,
        offset,
        nextOffset: pageInfo.nextOffset,
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
