import type { ToolHooks } from '@/tools/tool-hooks'
import { withAgentNote, withPostHogUrl } from '@/tools/tool-utils'
import type { Context } from '@/tools/types'
import { broadcastConversionNote, type HogFlowLike, hogFlowPath } from '@/tools/workflows/hogFlowLink'

async function afterResponse(context: Context, _params: unknown, result: unknown): Promise<unknown> {
    const flow = result as HogFlowLike | null
    if (!flow?.id) {
        return result
    }
    const linked = await withPostHogUrl(context, result, hogFlowPath({ ...flow, id: flow.id }))
    const note = broadcastConversionNote(flow)
    return note ? withAgentNote(linked, note) : linked
}

export default { afterResponse } satisfies ToolHooks<unknown>
