import type { ToolHooks } from '@/tools/tool-hooks'
import { withAgentNote } from '@/tools/tool-utils'
import type { Context } from '@/tools/types'
import { testSenderLiveNote } from '@/tools/workflows/hogFlowLink'

async function afterResponse(_context: Context, _params: unknown, result: unknown): Promise<unknown> {
    const note = testSenderLiveNote((result as { workflow?: { warnings?: { code?: string }[] } } | null)?.workflow)
    return note ? withAgentNote(result, note) : result
}

export default { afterResponse } satisfies ToolHooks<unknown>
