import { z } from 'zod'

import { withUiApp } from '@/resources/ui-apps'
import { withPostHogUrl, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase } from '@/tools/types'

const schema = z.object({
    session_ids: z.array(z.string()).min(1).max(300).describe('List of session IDs to summarize (max 300)'),
    focus_area: z.string().max(500).optional().describe('Optional focus area for the summarization'),
})

type Params = z.infer<typeof schema>

interface SessionSummary {
    [key: string]: unknown
}

interface SessionError {
    error: string
    error_message: string
}

type SessionResult = SessionSummary | SessionError

interface SummaryEvent {
    session_id: string
    summary: SessionSummary
}

interface ErrorEvent {
    session_id: string
    error: string
    error_message: string
}

interface DoneEvent {
    completed: string[]
    failed: string[]
}

type SseEvent = SummaryEvent | ErrorEvent | DoneEvent

type SseResult = WithPostHogUrl<Record<string, SessionResult>>

/**
 * Hand-written session-recording-summarize tool that uses SSE streaming
 * to avoid gateway timeouts on long-running summary generation (~5 min).
 *
 * Instead of blocking on a single HTTP request, this tool:
 * 1. Calls the streaming endpoint which returns SSE events
 * 2. Accumulates individual session summaries as they complete
 * 3. Returns the full result once the stream ends
 */
const sessionRecordingSummarize = (): ToolBase<typeof schema, SseResult> =>
    withUiApp('session-summary', {
        name: 'session-recording-summarize',
        schema,
        handler: async (context: Context, params: Params): Promise<SseResult> => {
            const projectId = await context.stateManager.getProjectId()
            const body: Record<string, unknown> = { session_ids: params.session_ids }
            if (params.focus_area !== undefined) {
                body['focus_area'] = params.focus_area
            }

            const results: Record<string, SessionResult> = {}
            let sawDone = false

            await context.api.requestSSE<SseEvent>({
                method: 'POST',
                path: `/api/environments/${encodeURIComponent(String(projectId))}/session_summaries/stream_batch/`,
                body,
                onEvent: (event, data) => {
                    if (event === 'summary') {
                        const d = data as SummaryEvent
                        if (d.session_id && d.summary) {
                            results[d.session_id] = d.summary
                        }
                    } else if (event === 'error') {
                        const d = data as ErrorEvent
                        if (d.session_id) {
                            results[d.session_id] = {
                                error: d.error,
                                error_message: d.error_message,
                            }
                        }
                    } else if (event === 'done') {
                        sawDone = true
                    }
                },
            })

            if (!sawDone) {
                throw new Error(
                    `SSE stream ended without a done event — results may be incomplete (received ${Object.keys(results).length}/${params.session_ids.length} sessions)`
                )
            }

            return withPostHogUrl(context, results, '/replay')
        },
    })

export default sessionRecordingSummarize
