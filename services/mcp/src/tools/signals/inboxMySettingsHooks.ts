import { PostHogApiError } from '@/lib/errors'
import type { ToolHooks } from '@/tools/tool-hooks'
import type { Context } from '@/tools/types'

type MySettingsParams = { user_id?: string }

// The API lets staff read and change the settings of other users, so the tools always act for the caller.
function beforeRequest<T extends MySettingsParams>(_context: Context, params: T): T {
    return { ...params, user_id: '@me' }
}

// The API answers 404 when the user saved no overrides. That is the usual state, not a failure.
function onError(_context: Context, _params: MySettingsParams, error: unknown): unknown {
    if (error instanceof PostHogApiError && error.status === 404 && error.method === 'GET') {
        return {
            has_overrides: false as const,
            message: 'You have no personal inbox overrides. The project defaults apply to every setting.',
        }
    }
    throw error
}

export default { beforeRequest, onError } satisfies ToolHooks<MySettingsParams>
