import { z } from 'zod'

import { pickResponseFields } from '@/tools/tool-utils'
import type { Context, ToolBase } from '@/tools/types'

import { dateRangeSchema, escapeHogQLString, getPageInfo, propertyFilterSchema, type PropertyFilter } from './utils'

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
    release: z
        .string()
        .max(500)
        .optional()
        .describe('Filter by exact release ID, version, or git commit ID captured in $exception_releases.'),
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

function addReleaseFilter(filters: PropertyFilter[], release: string): void {
    const escapedRelease = escapeHogQLString(release)
    const releasesJson = "ifNull(nullIf(JSONExtractRaw(properties, '$exception_releases'), ''), '{}')"
    filters.push({
        type: 'hogql',
        key: `arrayExists(r -> (r.1 = '${escapedRelease}' OR JSONExtractString(r.2, 'version') = '${escapedRelease}' OR JSONExtractString(JSONExtractRaw(r.2, 'metadata'), 'git', 'commit_id') = '${escapedRelease}'), JSONExtractKeysAndValuesRaw(${releasesJson}))`,
    })
}

function buildFilterGroup(params: Params): PropertyFilter[] {
    const filters = [...(params.filterGroup ?? [])]

    if (params.library) {
        addEventFilter(filters, '$lib', 'exact', params.library)
    }
    if (params.release) {
        addReleaseFilter(filters, params.release)
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
