import type { z } from 'zod'

import { markExecPayload, type ToolResultPayload } from '@/lib/build-tool-result'
import { findRecoverableApiError, PostHogApiError } from '@/lib/errors'
import { formatResponse } from '@/lib/response'
import { GENERATED_TOOLS } from '@/tools/generated/replay'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

/**
 * Structured "the recording does not exist" answer. Agents call
 * `session-recording-get` as an existence check ("is this id a captured
 * recording?"), and a missing recording is the answer they wanted — not a
 * failure. Returning this as a normal (non-error) result lets them branch on
 * `exists` instead of parsing an error message off the error path.
 */
interface SessionRecordingNotFound {
    exists: false
    reason: 'not_found'
    session_id: string
    message: string
}

function buildNotFoundResult(sessionId: string): SessionRecordingNotFound {
    return {
        exists: false,
        reason: 'not_found',
        session_id: sessionId,
        message:
            `No session recording exists for id "${sessionId}". This is a definitive "does not exist" answer, ` +
            'not an error — branch on `exists`. A session can have no recording because replay was never enabled ' +
            'for the project or session, the session was sampled out, or the recording passed its retention window ' +
            'and expired. To diagnose why capture did not happen, query `$recording_status`, ' +
            '`$session_recording_start_reason`, `$replay_sample_rate`, and `$sdk_debug_recording_script_not_loaded` ' +
            'on the events table with `execute-sql` (filter by `$session_id` for this session).',
    }
}

/**
 * Hand-written wrapper over the generated `session-recording-get` tool.
 *
 * The generated handler surfaces a missing recording as a 404 error result
 * (`isError: true`), which agents using the tool as an existence check have to
 * reason around. This wrapper turns that single case — a 404 from the retrieve
 * endpoint — into a structured success payload so existence checks branch
 * cleanly. Every other failure (5xx, network, non-404 4xx) is re-thrown
 * untouched so the executor's error path still classifies and captures it (a
 * real failure now reaches Error Tracking instead of hiding behind the 404
 * noise that dominated this tool's error rate).
 *
 * Kept out of the generated file (`generated/replay.ts` is regenerated from
 * `products/replay/mcp/tools.yaml`) and registered in `TOOL_MAP`, which takes
 * precedence over `GENERATED_TOOL_MAP` for this tool name.
 */
const sessionRecordingGet = (): ToolBase<ZodObjectAny> => {
    const inner = GENERATED_TOOLS['session-recording-get']!()
    return {
        ...inner,
        handler: async (context: Context, params: z.infer<ZodObjectAny>): Promise<unknown> => {
            try {
                return await inner.handler(context, params)
            } catch (error: unknown) {
                const apiError = findRecoverableApiError(error)
                if (apiError instanceof PostHogApiError && apiError.status === 404) {
                    const notFound = buildNotFoundResult(String((params as { id: unknown }).id))
                    // Return a pre-built payload (rather than a plain object) so the
                    // session-recording UI app — which expects a real recording in
                    // `structuredContent` — is not rendered against the not-found shape.
                    const payload: ToolResultPayload = {
                        content: [{ type: 'text', text: formatResponse(notFound) }],
                    }
                    return markExecPayload(payload)
                }
                throw error
            }
        },
    }
}

export default sessionRecordingGet
