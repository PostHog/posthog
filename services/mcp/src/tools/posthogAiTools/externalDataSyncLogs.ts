import { z } from 'zod'

import type { Context, ToolBase } from '@/tools/types'

import { invokeMcpTool } from './invokeTool'

const schema = z.object({
    schema_id: z.uuid().describe('UUID of the external data schema (table) to get sync logs for.'),
    job_id: z
        .uuid()
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

const tool = (): ToolBase<typeof schema, string> => ({
    name: 'external-data-sync-logs',
    schema,
    handler: async (context: Context, params: Params) => {
        const minLevel = params.level ?? 'INFO'
        const minIndex = LEVEL_ORDER.indexOf(minLevel)
        const includedLevels = LEVEL_ORDER.slice(minIndex).map((l) => `'${l.toLowerCase()}'`)

        let whereClause = `log_source = 'external_data_jobs' AND log_source_id = '${params.schema_id}'`
        whereClause += ` AND lower(level) IN (${includedLevels.join(',')})`

        if (params.job_id) {
            whereClause += ` AND instance_id = '${params.job_id}'`
        }

        if (params.search) {
            const escaped = params.search.replace(/'/g, "\\'")
            whereClause += ` AND message ILIKE '%${escaped}%'`
        }

        const limit = params.limit ?? 100
        const query = `SELECT instance_id, timestamp, level, message FROM log_entries WHERE ${whereClause} ORDER BY timestamp DESC LIMIT ${limit}`

        const result = await invokeMcpTool(context, 'execute_sql', {
            query,
            truncate: true,
        })

        if (!result.success) {
            throw new Error(result.content)
        }

        return result.content
    },
})

export default tool
