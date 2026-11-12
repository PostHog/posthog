import { redactCredentials } from '@/lib/credential-redaction'
import type { ToolHooks } from '@/tools/tool-hooks'
import type { Context } from '@/tools/types'

// The REST API returns the same logs without redaction, so this scope opens no data that `logs:read` does not.
// The key must name the scope. A full-access `*` key does not count, and a failed key lookup keeps redaction on.
export async function holdsUnredactedLogsScope(context: Context): Promise<boolean> {
    try {
        return (await context.stateManager.getApiKey()).scopes.includes('logs_unredacted:read')
    } catch {
        return false
    }
}

// Log bodies and attribute values are application text, so they can carry credentials the field filters cannot reach.
async function afterResponse(context: Context, _params: unknown, result: unknown): Promise<unknown> {
    return (await holdsUnredactedLogsScope(context)) ? result : redactCredentials(result)
}

export default { afterResponse } satisfies ToolHooks<unknown>
