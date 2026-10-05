import { PostHogApiError } from '@/lib/errors'
import { GENERATED_TOOLS } from '@/tools/generated/replay'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const getSessionRecording = (): ToolBase<ZodObjectAny> => {
    const tool = GENERATED_TOOLS['session-recording-get']!()

    return {
        ...tool,
        handler: async (context: Context, params: { id: string }) => {
            try {
                return await tool.handler(context, params)
            } catch (error) {
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
        },
    }
}

function isRecordingNotFound(body: string): boolean {
    try {
        return JSON.parse(body)?.detail === 'Recording not found'
    } catch {
        return false
    }
}

export default getSessionRecording
