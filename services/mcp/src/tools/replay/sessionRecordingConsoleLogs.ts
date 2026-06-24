import { z } from 'zod'

import { withPostHogUrl, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase } from '@/tools/types'

const schema = z.object({
    session_id: z
        .string()
        .min(1)
        .describe(
            'The session recording ID — any `$session_id` value from an event, error, or person. Console logs are returned for this session only.'
        ),
    level: z
        .array(z.string())
        .min(1)
        .optional()
        .describe(
            'Optional case-insensitive filter on log level. Common values are `info`, `log`, `warn`, and `error` (also `debug`, `fatal`). Omit to return every level. Example: `["warn", "error"]` to see only warnings and errors.'
        ),
    search: z
        .string()
        .min(1)
        .optional()
        .describe('Optional case-insensitive substring to match against the log message.'),
    limit: z.coerce
        .number()
        .int()
        .min(1)
        .max(1000)
        .optional()
        .describe('Maximum number of log lines to return. Default 200, max 1000.'),
    order: z
        .enum(['asc', 'desc'])
        .optional()
        .describe(
            'Chronological order by timestamp. `asc` (default) reads oldest-first; `desc` shows the latest logs.'
        ),
})

type Params = z.infer<typeof schema>

interface ConsoleLogLine {
    timestamp: unknown
    level: unknown
    message: unknown
}

type Result = WithPostHogUrl<{ results: ConsoleLogLine[] }>

const DEFAULT_LIMIT = 200

/**
 * Returns the actual console log lines (timestamp, level, message) captured for a single
 * session recording. The aggregate counts on `session-recording-get` tell an agent that
 * errors happened; this surfaces what they said. Backed by the `console_logs_log_entries`
 * HogQL table (the same data reachable via `execute-sql`), filtered to one session.
 */
const sessionRecordingConsoleLogs = (): ToolBase<typeof schema, Result> => ({
    name: 'session-recording-console-logs',
    schema,
    handler: async (context: Context, params: Params): Promise<Result> => {
        const projectId = await context.stateManager.getProjectId()

        const limit = params.limit ?? DEFAULT_LIMIT
        const direction = params.order === 'desc' ? 'DESC' : 'ASC'

        const values: Record<string, unknown> = { session_id: params.session_id }
        const conditions = ['log_source_id = {session_id}']

        if (params.level?.length) {
            values.levels = params.level.map((l) => l.toLowerCase())
            conditions.push('lower(level) IN {levels}')
        }
        if (params.search !== undefined) {
            values.search = `%${params.search}%`
            conditions.push('message ILIKE {search}')
        }

        const query = {
            kind: 'HogQLQuery',
            query: `SELECT timestamp, level, message
FROM console_logs_log_entries
WHERE ${conditions.join(' AND ')}
ORDER BY timestamp ${direction}
LIMIT ${limit}`,
            values,
        }

        const response = await context.api.query({ projectId }).execute({ queryBody: query })
        if (!response.success) {
            throw new Error(`Failed to fetch console logs: ${response.error.message}`)
        }

        const rows = (response.data.results ?? []) as unknown[][]
        const results: ConsoleLogLine[] = rows.map(([timestamp, level, message]) => ({
            timestamp,
            level,
            message,
        }))

        return withPostHogUrl(context, { results }, `/replay/${params.session_id}`)
    },
})

export default sessionRecordingConsoleLogs
