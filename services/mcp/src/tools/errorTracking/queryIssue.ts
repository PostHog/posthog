import { z } from 'zod'

import { pickResponseFields } from '@/tools/tool-utils'
import type { Context, ToolBase } from '@/tools/types'

const dateRangeSchema = z
    .object({
        date_from: z.string().optional(),
        date_to: z.string().nullable().optional(),
    })
    .optional()

const schema = z.object({
    issueId: z
        .string()
        .regex(/^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$/)
        .describe('Error tracking issue ID.'),
    dateRange: dateRangeSchema.default({ date_from: '-7d' }).optional(),
    filterTestAccounts: z.coerce.boolean().default(true).optional(),
    volumeResolution: z.coerce.number().int().min(0).default(0).optional(),
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

export const queryIssueHandler: ToolBase<typeof schema>['handler'] = async (context: Context, rawParams: Params) => {
    const params = schema.parse(rawParams)
    const projectId = await context.stateManager.getProjectId()
    const baseUrl = context.api.getProjectBaseUrl(projectId)
    const posthogUrl = `${baseUrl}/error_tracking/${encodeURIComponent(params.issueId)}`

    const query = {
        kind: 'ErrorTrackingQuery',
        issueId: params.issueId,
        dateRange: params.dateRange,
        filterTestAccounts: params.filterTestAccounts,
        volumeResolution: params.volumeResolution,
        limit: 1,
        orderBy: 'last_seen',
        orderDirection: 'DESC',
        withAggregations: true,
        withFirstEvent: false,
        withLastEvent: false,
        tags: { productKey: 'error_tracking' },
    }

    const data = await context.api.query({ projectId }).runQuery({ query })
    const issue = Array.isArray(data.results) ? data.results[0] : undefined

    if (!issue || typeof issue !== 'object') {
        return { result: null, _posthogUrl: posthogUrl }
    }

    return {
        ...pickResponseFields(issue, ISSUE_FIELDS),
        _posthogUrl: posthogUrl,
    }
}

const tool = (): ToolBase<typeof schema> => ({
    name: 'query-error-tracking-issue',
    schema,
    handler: queryIssueHandler,
})

export default tool
