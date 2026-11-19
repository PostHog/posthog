import type { ToolHooks } from '@/tools/tool-hooks'
import type { Context } from '@/tools/types'
import { keepTestSenderNoteOnlyWithWarning } from '@/tools/workflows/testSenderNote'

async function afterResponse(_context: Context, _params: unknown, result: unknown): Promise<unknown> {
    const workflow = typeof result === 'object' && result !== null ? (result as { workflow?: unknown }).workflow : null
    return keepTestSenderNoteOnlyWithWarning(result, workflow)
}

export default { afterResponse } satisfies ToolHooks<unknown>
