import { PostHogApiError } from '@/lib/errors'
import type { ToolHooks } from '@/tools/tool-hooks'
import type { Context } from '@/tools/types'

// Turns the API's "Recording not found" 404 into a result the agent can read, instead of a tool error.
function onError(_context: Context, params: { id: string }, error: unknown): unknown {
    if (
        error instanceof PostHogApiError &&
        error.status === 404 &&
        error.method === 'GET' &&
        error.url.split('?')[0]?.endsWith(`/session_recordings/${encodeURIComponent(params.id)}/`) &&
        isRecordingNotFound(error.body)
    ) {
        return {
            found: false as const,
            id: params.id,
            reason: 'recording_not_found' as const,
            message: 'No session recording is available for this ID in the active project.',
        }
    }
    throw error
}

function isRecordingNotFound(body: string): boolean {
    try {
        return JSON.parse(body)?.detail === 'Recording not found'
    } catch {
        return false
    }
}

export default { onError } satisfies ToolHooks<{ id: string }>
