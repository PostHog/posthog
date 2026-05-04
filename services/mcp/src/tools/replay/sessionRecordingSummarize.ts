import { z } from 'zod'

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

interface SummaryEvent {
    session_id: string
    summary?: SessionSummary
    error?: string
}

interface DoneEvent {
    completed: string[]
    failed: string[]
}

type SseResult = WithPostHogUrl<Record<string, SessionSummary>>

/**
 * Hand-written session-recording-summarize tool that uses SSE streaming
 * to avoid gateway timeouts on long-running summary generation (~5 min).
 *
 * Instead of blocking on a single HTTP request, this tool:
 * 1. Calls the streaming endpoint which returns SSE events
 * 2. Accumulates individual session summaries as they complete
 * 3. Returns the full result once the stream ends
 */
const sessionRecordingSummarize = (): ToolBase<typeof schema, SseResult> => ({
    name: 'session-recording-summarize',
    schema,
    handler: async (context: Context, params: Params): Promise<SseResult> => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}

        if (params.session_ids !== undefined) {
            body['session_ids'] = params.session_ids
        }
        if (params.focus_area !== undefined) {
            body['focus_area'] = params.focus_area
        }

        const summaries: Record<string, SessionSummary> = {}

        await context.api.requestSSE<SummaryEvent | DoneEvent>({
            method: 'POST',
            path: `/api/environments/${encodeURIComponent(String(projectId))}/session_summaries/stream_batch/`,
            body,
            timeoutMs: 8 * 60 * 1000, // 8 minutes
            onEvent: (event, data) => {
                if (event === 'summary') {
                    const summaryData = data as SummaryEvent
                    if (summaryData.session_id && summaryData.summary) {
                        summaries[summaryData.session_id] = summaryData.summary
                    }
                }
                // error and done events are informational — we just collect summaries
            },
        })

        return withPostHogUrl(context, summaries, '/replay')
    },
})

export default sessionRecordingSummarize
