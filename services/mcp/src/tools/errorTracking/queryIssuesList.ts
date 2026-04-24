import { z } from 'zod'

import { pickResponseFields } from '@/tools/tool-utils'
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

const stringOrStringsSchema = z.union([z.string(), z.array(z.string()).min(1)])

const schema = z.object({
    dateRange: dateRangeSchema.default({ date_from: '-7d' }).optional(),
    status: z
        .enum(['archived', 'active', 'resolved', 'pending_release', 'suppressed', 'all'])
        .default('active')
        .optional()
        .describe('Filter by issue status. Defaults to active.'),
    assignee: z
        .union([
            z.object({
                id: z.union([z.coerce.number().int(), z.string()]),
                type: z.enum(['user', 'role']),
            }),
            z.null(),
        ])
        .optional()
        .describe('Filter by issue assignee.'),
    filterTestAccounts: z.coerce
        .boolean()
        .default(true)
        .optional()
        .describe('When true, exclude internal/test account data from results. Defaults to true.'),
    searchQuery: z
        .string()
        .max(500)
        .optional()
        .describe('Free-text search across exception type, message, stack frames, and email fields.'),
    filterGroup: z
        .array(propertyFilterSchema)
        .default([])
        .optional()
        .describe('Advanced flat AND property filters. Prefer the typed shortcut fields when they fit.'),
    orderBy: z.enum(['last_seen', 'first_seen', 'occurrences', 'users', 'sessions']).default('occurrences').optional(),
    orderDirection: z.enum(['ASC', 'DESC']).default('DESC').optional(),
    limit: z.coerce.number().int().min(1).max(100).default(25).optional(),
    offset: z.coerce.number().int().min(0).default(0).optional(),
    volumeResolution: z.coerce.number().int().min(0).default(0).optional(),
    library: stringOrStringsSchema
        .optional()
        .describe('Filter by SDK/library value from event $lib, for example posthog-js or posthog-node.'),
    release: z.string().max(500).optional().describe('Filter by release/version text captured in $exception_releases.'),
    environment: z
        .string()
        .max(200)
        .optional()
        .describe('Filter by runtime environment captured in event $environment.'),
    fingerprint: stringOrStringsSchema
        .optional()
        .describe('Filter by exact exception fingerprint hash, usually a long hex-style hash, not fuzzy search.'),
    user: z.string().max(500).optional().describe('Search user/email text in exception event and person email fields.'),
    personId: z.string().max(100).optional().describe('Filter by exact PostHog person UUID.'),
    url: z.string().max(1000).optional().describe('Filter by current URL substring from event $current_url.'),
    filePath: z
        .string()
        .max(1000)
        .optional()
        .describe('Search stack-frame source/file path text captured in exception sources.'),
})

type Params = z.infer<typeof schema>
type PropertyFilter = z.infer<typeof propertyFilterSchema>

const ISSUE_FIELDS = [
    'id',
    'name',
    'description',
    'status',
    'first_seen',
    'last_seen',
    'library',
    'source',
    'assignee',
    'aggregations',
]

function asArray(value: string | string[]): string[] {
    return Array.isArray(value) ? value : [value]
}

function addEventFilter(
    filters: PropertyFilter[],
    key: string,
    operator: NonNullable<PropertyFilter['operator']>,
    value: string | string[]
): void {
    filters.push({ type: 'event', key, operator, value: operator === 'exact' ? asArray(value) : value })
}

function buildFilterGroup(params: Params): PropertyFilter[] {
    const filters = [...(params.filterGroup ?? [])]

    if (params.library) {
        addEventFilter(filters, '$lib', 'exact', params.library)
    }
    if (params.release) {
        addEventFilter(filters, '$exception_releases', 'icontains', params.release)
    }
    if (params.environment) {
        addEventFilter(filters, '$environment', 'exact', params.environment)
    }
    if (params.fingerprint) {
        addEventFilter(filters, '$exception_fingerprint', 'exact', params.fingerprint)
    }
    if (params.url) {
        addEventFilter(filters, '$current_url', 'icontains', params.url)
    }

    return filters
}

function searchTerm(value: string): string {
    const trimmed = value.trim().replace(/["']/g, ' ')
    return /\s/.test(trimmed) ? `"${trimmed}"` : trimmed
}

function buildSearchQuery(params: Params): string | undefined {
    const terms = [params.searchQuery, params.user, params.filePath].filter(
        (value): value is string => typeof value === 'string' && value.trim().length > 0
    )

    if (terms.length === 0) {
        return undefined
    }

    return terms.map(searchTerm).join(' ')
}

function getPageInfo(
    data: Record<string, unknown>,
    limit: number,
    offset: number
): { hasMore: boolean; nextOffset?: number } {
    const rawRows = Array.isArray(data.results) ? data.results : []
    const hasMore = Boolean(data.hasMore) || rawRows.length > limit
    return hasMore ? { hasMore, nextOffset: offset + limit } : { hasMore }
}

export const queryIssuesListHandler: ToolBase<typeof schema>['handler'] = async (
    context: Context,
    rawParams: Params
) => {
    const params = schema.parse(rawParams)
    const projectId = await context.stateManager.getProjectId()
    const baseUrl = context.api.getProjectBaseUrl(projectId)
    const filterGroup = buildFilterGroup(params)
    const limit = params.limit ?? 25
    const offset = params.offset ?? 0

    const query: Record<string, unknown> = {
        kind: 'ErrorTrackingQuery',
        dateRange: params.dateRange,
        status: params.status,
        assignee: params.assignee,
        filterTestAccounts: params.filterTestAccounts,
        searchQuery: buildSearchQuery(params),
        filterGroup: filterGroup.length > 0 ? filterGroup : undefined,
        orderBy: params.orderBy,
        orderDirection: params.orderDirection,
        limit,
        offset,
        volumeResolution: params.volumeResolution,
        personId: params.personId,
        withAggregations: true,
        withFirstEvent: false,
        withLastEvent: false,
        tags: { productKey: 'error_tracking' },
    }

    for (const [key, value] of Object.entries(query)) {
        if (value === undefined) {
            delete query[key]
        }
    }

    const data = await context.api.query({ projectId }).runQuery({ query })
    const rawResults = Array.isArray(data.results) ? data.results : []
    const results = rawResults.slice(0, limit).map((issue: unknown) => pickResponseFields(issue, ISSUE_FIELDS))
    const pageInfo = getPageInfo(data as Record<string, unknown>, limit, offset)

    return {
        results,
        hasMore: pageInfo.hasMore,
        limit,
        offset,
        nextOffset: pageInfo.nextOffset,
        _posthogUrl: `${baseUrl}/error_tracking`,
    }
}

const tool = (): ToolBase<typeof schema> => ({
    name: 'query-error-tracking-issues-list',
    schema,
    handler: queryIssuesListHandler,
    _meta: {
        ui: { resourceUri: 'ui://posthog/error-issue-list.html' },
    },
})

export default tool
