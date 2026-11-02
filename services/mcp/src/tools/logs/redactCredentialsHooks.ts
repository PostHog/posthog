import { redactCredentials } from '@/lib/credential-redaction'
import type { ToolHooks } from '@/tools/tool-hooks'
import type { Context } from '@/tools/types'

// Log bodies and attribute values are application text, so they can carry credentials the field filters cannot reach.
function afterResponse(_context: Context, _params: unknown, result: unknown): unknown {
    return redactCredentials(result)
}

export default { afterResponse } satisfies ToolHooks<unknown>
