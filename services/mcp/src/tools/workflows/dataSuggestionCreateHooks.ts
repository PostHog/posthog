import type { ToolHooks } from '@/tools/tool-hooks'
import { withPostHogUrl } from '@/tools/tool-utils'
import type { Context } from '@/tools/types'

// The editor link only exists once the draft is saved, so a building or failed result gets none.
async function afterResponse(context: Context, _params: unknown, result: unknown): Promise<unknown> {
    const workflowId = (result as { workflow_id?: string | null } | null)?.workflow_id
    return workflowId ? await withPostHogUrl(context, result, `/workflows/${workflowId}/workflow`) : result
}

export default { afterResponse } satisfies ToolHooks<unknown>
