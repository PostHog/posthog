import { z } from 'zod'

import {
    ExternalDataJobsAfterSchema,
    ExternalDataJobsBeforeSchema,
    ExternalDataJobsLimitSchema,
    ExternalDataJobsSchemasSchema,
} from '@/schema/tool-inputs'
import { normalizeParamAliases } from '@/tools/cast-helpers'
import type { Context, ToolBase } from '@/tools/types'

const DEFAULT_LIMIT = 20
const ERROR_MAX_LENGTH = 500

const schema = z.preprocess(
    normalizeParamAliases({ id: ['source_id', 'sourceId'] }),
    z.object({
        id: z
            .string()
            .describe('UUID of the data warehouse source (from external-data-sources-list). Not a table (schema) id.'),
        after: ExternalDataJobsAfterSchema.optional(),
        before: ExternalDataJobsBeforeSchema.optional(),
        schemas: ExternalDataJobsSchemasSchema.optional(),
        limit: ExternalDataJobsLimitSchema.optional(),
    })
)

type Params = z.infer<typeof schema>

interface Job {
    created_at?: string
    latest_error?: string | null
    [key: string]: unknown
}

export interface ExternalDataJobsResult {
    results: Job[]
    /** True when the page is full, so older jobs can exist. */
    has_more: boolean
    /** Pass as `before` to get the next, older page. Null when `has_more` is false. */
    next_before: string | null
}

export function truncateText(value: string, maxLength: number): string {
    if (value.length <= maxLength) {
        return value
    }
    return `${value.slice(0, maxLength)}… [truncated, ${value.length} characters]`
}

const tool = (): ToolBase<typeof schema, ExternalDataJobsResult> => ({
    name: 'external-data-sources-jobs',
    schema,
    handler: async (context: Context, params: Params) => {
        const projectId = await context.stateManager.getProjectId()
        const limit = params.limit ?? DEFAULT_LIMIT
        const searchParams = new URLSearchParams()
        if (params.after) {
            searchParams.append('after', params.after)
        }
        if (params.before) {
            searchParams.append('before', params.before)
        }
        for (const schemaName of params.schemas ?? []) {
            searchParams.append('schemas', schemaName)
        }
        searchParams.append('limit', String(limit))
        const basePath = `/api/projects/${encodeURIComponent(String(projectId))}/external_data_sources/${encodeURIComponent(String(params.id))}/jobs/`
        const jobs = await context.api.request<Job[]>({
            method: 'GET',
            path: `${basePath}?${searchParams.toString()}`,
        })
        // An older backend ignores `limit`, so cut the page here too.
        const results = (jobs ?? [])
            .slice(0, limit)
            .map((job) =>
                typeof job.latest_error === 'string'
                    ? { ...job, latest_error: truncateText(job.latest_error, ERROR_MAX_LENGTH) }
                    : job
            )
        const hasMore = results.length === limit
        const last = results[results.length - 1]
        return {
            results,
            has_more: hasMore,
            next_before: hasMore && last?.created_at ? last.created_at : null,
        }
    },
})

export default tool
