import type { ToolHooks } from '@/tools/tool-hooks'
import { withPostHogUrl } from '@/tools/tool-utils'
import type { Context } from '@/tools/types'
import { hogFlowPath } from '@/tools/workflows/hogFlowLink'

// The warning rule stays in this file because the CLI catalog versions a hook by hashing its own source, so a change
// to the rule gives the hook a new version.

function isRecord(value: unknown): value is Record<string, unknown> {
    return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function hasTestSenderLiveWarning(flow: unknown): boolean {
    const warnings = isRecord(flow) ? flow.warnings : undefined
    return (
        Array.isArray(warnings) &&
        warnings.some(
            (warning) =>
                isRecord(warning) &&
                warning.code === 'test_sender_live' &&
                typeof warning.message === 'string' &&
                warning.message.trim() !== ''
        )
    )
}

function keepNoteOnlyWithWarning(result: Record<string, unknown>, flow: unknown): Record<string, unknown> {
    if (!('_agentNote' in result) || hasTestSenderLiveWarning(flow)) {
        return result
    }
    const { _agentNote: _dropped, ...rest } = result
    return rest
}

// workflows-publish returns { published, workflow, ... }; workflows-enable returns the workflow itself, with a link.
async function afterResponse(context: Context, _params: unknown, result: unknown): Promise<unknown> {
    if (!isRecord(result)) {
        return result
    }
    if ('published' in result) {
        // The note says the workflow was published, so a preview never keeps it.
        return keepNoteOnlyWithWarning(result, result.published === true ? result.workflow : null)
    }
    const id = typeof result.id === 'string' && result.id !== '' ? result.id : null
    if (!id) {
        return keepNoteOnlyWithWarning(result, result)
    }
    const origin = typeof result.origin_product === 'string' ? result.origin_product : null
    const linked = await withPostHogUrl(context, result, hogFlowPath({ id, origin_product: origin }))
    return keepNoteOnlyWithWarning(linked as Record<string, unknown>, result)
}

export default { afterResponse } satisfies ToolHooks<unknown>
