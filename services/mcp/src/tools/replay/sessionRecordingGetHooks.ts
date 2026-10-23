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

// A person's display name falls back to their email, so drop it to keep personal data out of agent context.
function afterResponse(_context: Context, _params: { id: string }, result: unknown): unknown {
    if (!isRecord(result) || !isRecord(result.person) || !looksLikeEmail(result.person.name)) {
        return result
    }
    const { name: _name, ...person } = result.person
    return { ...result, person }
}

function isRecord(value: unknown): value is Record<string, unknown> {
    return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function looksLikeEmail(value: unknown): boolean {
    return typeof value === 'string' && /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value.trim())
}

export default { afterResponse, onError } satisfies ToolHooks<{ id: string }>
