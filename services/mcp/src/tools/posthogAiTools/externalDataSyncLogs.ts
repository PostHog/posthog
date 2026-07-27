import { z } from 'zod'

import type { Context, ToolBase } from '@/tools/types'

// PostHog ids are UUIDTs whose version/variant nibbles don't follow RFC 4122, so `z.uuid()`
// (which enforces those nibbles in Zod 4) rejects valid ids — e.g. a `0` version nibble. Use
// `z.guid()`, which accepts any 8-4-4-4-12 hex string.
const schema = z.object({
    schema_id: z.guid().describe('UUID of the external data schema (table) to get sync logs for.'),
    job_id: z
        .guid()
        .optional()
        .describe(
            'Optional workflow_run_id to filter logs for a specific sync job. Get this from external-data-sources-jobs.'
        ),
    level: z
        .enum(['DEBUG', 'INFO', 'WARNING', 'ERROR'])
        .optional()
        .describe('Minimum log level to return. Defaults to INFO (excludes DEBUG).'),
    search: z.string().optional().describe('Search string to filter log messages (case-insensitive substring match).'),
    limit: z.number().int().min(1).max(500).optional().describe('Max number of log entries to return (default 100).'),
})

type Params = z.infer<typeof schema>

const LEVEL_ORDER = ['DEBUG', 'INFO', 'WARNING', 'ERROR'] as const

const tool = (): ToolBase<typeof schema, unknown> => ({
    name: 'external-data-sync-logs',
    schema,
    handler: async (context: Context, params: Params) => {
        const projectId = await context.stateManager.getProjectId()

        const minLevel = params.level ?? 'INFO'
        const minIndex = LEVEL_ORDER.indexOf(minLevel)
        const includedLevels = LEVEL_ORDER.slice(minIndex).join(',')

        const searchParams = new URLSearchParams()
        searchParams.set('limit', String(params.limit ?? 100))
        searchParams.set('level', includedLevels)
        if (params.job_id) {
            searchParams.set('instance_id', params.job_id)
        }
        if (params.search) {
            searchParams.set('search', params.search)
        }

        const basePath = `/api/environments/${encodeURIComponent(String(projectId))}/external_data_schemas/${encodeURIComponent(params.schema_id)}/logs/`
        return context.api.request<unknown>({
            method: 'GET',
            path: `${basePath}?${searchParams.toString()}`,
        })
    },
})

export default tool
