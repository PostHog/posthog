import api from 'lib/api'
import type { AiFirstHandoffLogicProps } from 'scenes/max/aiFirstCreate/aiFirstHandoffLogic'
import { urls } from 'scenes/urls'

// pinned: MCP tool name from products/workflows/mcp/tools.yaml
const CREATE_WORKFLOW_TOOL = 'workflows-create'

/**
 * Fallback for a completed create whose output carries no record: the draft is found by exact name, newest
 * `created_at` first. No name means no guess.
 */
export async function findCreatedWorkflowId(name: unknown): Promise<string | null> {
    const search = typeof name === 'string' && name.trim() ? name.trim() : undefined
    if (!search) {
        return null
    }
    const { results } = await api.hogFlows.getHogFlows({ search, limit: 5 })
    const match = results
        .filter((workflow) => workflow.name === search)
        .sort((a, b) => b.created_at.localeCompare(a.created_at))[0]
    return match?.id ?? null
}

/** A completed `workflows-create` opens the panel and routes to the draft. */
export const NEW_WORKFLOW_HANDOFF: AiFirstHandoffLogicProps = {
    toolName: CREATE_WORKFLOW_TOOL,
    findCreatedId: (innerInput) => findCreatedWorkflowId(innerInput?.name),
    urlFor: (id) => urls.workflow(id, 'workflow'),
    notOpenedMessage: 'Your workflow was created, but it could not be opened. Find it in the workflows list.',
    // pinned: analytics event names
    eventPrefix: 'workflow ai composer',
    createdEvent: 'workflow ai composer created workflow',
    createdIdProperty: 'workflow_id',
}
