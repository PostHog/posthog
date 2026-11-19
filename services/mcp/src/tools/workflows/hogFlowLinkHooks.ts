import type { ToolHooks } from '@/tools/tool-hooks'
import { withPostHogUrl } from '@/tools/tool-utils'
import type { Context } from '@/tools/types'
import { type HogFlowLike, hogFlowPath } from '@/tools/workflows/hogFlowLink'

async function afterResponse(context: Context, _params: unknown, result: unknown): Promise<unknown> {
    const flow = result as HogFlowLike | null
    if (!flow?.id) {
        return result
    }
    return await withPostHogUrl(context, result, hogFlowPath({ ...flow, id: flow.id }))
}

export default { afterResponse } satisfies ToolHooks<unknown>
