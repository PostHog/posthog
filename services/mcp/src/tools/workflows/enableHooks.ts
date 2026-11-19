import type { ToolHooks } from '@/tools/tool-hooks'
import { withPostHogUrl } from '@/tools/tool-utils'
import type { Context } from '@/tools/types'
import { type HogFlowLike, hogFlowPath } from '@/tools/workflows/hogFlowLink'
import { keepTestSenderNoteOnlyWithWarning } from '@/tools/workflows/testSenderNote'

async function afterResponse(context: Context, _params: unknown, result: unknown): Promise<unknown> {
    const flow = result as HogFlowLike | null
    if (!flow?.id) {
        return keepTestSenderNoteOnlyWithWarning(result, result)
    }
    const linked = await withPostHogUrl(context, result, hogFlowPath({ ...flow, id: flow.id }))
    return keepTestSenderNoteOnlyWithWarning(linked, result)
}

export default { afterResponse } satisfies ToolHooks<unknown>
