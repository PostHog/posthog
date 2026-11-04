import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import type { AiFirstHandoffLogicProps } from 'scenes/max/aiFirstCreate/aiFirstHandoffLogic'
import { projectLogic } from 'scenes/projectLogic'
import { urls } from 'scenes/urls'

import { projectTreeDataLogic } from '~/layout/panel-layout/ProjectTree/projectTreeDataLogic'
import { calculateMovePath } from '~/layout/panel-layout/ProjectTree/utils'

import { hogFlowsList } from '../generated/api'

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
    const projectId = String(projectLogic.findMounted()?.values.currentProjectId)
    const { results } = await hogFlowsList(projectId, { search, limit: 5 })
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

export function workflowHandoffInFolder(folder: string | null): AiFirstHandoffLogicProps {
    if (!folder) {
        return NEW_WORKFLOW_HANDOFF
    }
    return {
        ...NEW_WORKFLOW_HANDOFF,
        prepareCreated: async (id) => {
            // Filing is a follow-up step, so a failed move still opens the workflow the person just made.
            try {
                const { results } = await api.fileSystem.list({ type: 'hog_flow', ref: id })
                const entry = results.find((item) => item.type === 'hog_flow' && item.ref === id && !item.shortcut)
                if (!entry?.id) {
                    throw new Error('Workflow file not found')
                }
                const { newPath, isValidMove } = calculateMovePath(entry, folder)
                if (isValidMove) {
                    await api.fileSystem.move(entry.id, newPath)
                    projectTreeDataLogic.findMounted()?.actions.movedItem(entry, entry.path, newPath)
                }
            } catch {
                lemonToast.warning(
                    `Your workflow was created, but it couldn't be moved into ${folder}. It's in Unfiled / Workflows.`
                )
            }
        },
    }
}
