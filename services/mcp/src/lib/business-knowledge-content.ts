import type { Context } from '@/tools/types'

const SOURCE_CREATE_TOOLS: ReadonlySet<string> = new Set([
    'business-knowledge-sources-text-create',
    'business-knowledge-sources-url-create',
])

export async function clearBusinessKnowledgeContentAfterSourceCreate(
    toolName: string,
    context: Pick<Context, 'stateManager'>
): Promise<void> {
    if (!SOURCE_CREATE_TOOLS.has(toolName)) {
        return
    }
    try {
        await context.stateManager.clearBusinessKnowledgeContent(await context.stateManager.getProjectId())
    } catch {
        // The source is already saved, so a failed clear must not turn the call into an error.
    }
}
