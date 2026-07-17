import type { z } from 'zod'

import { AgentResolveResourceSchema } from '@/schema/tool-inputs'
import { playbookIdFromRef, playbookUri } from '@/tools/agentPlatform/playbookIds'
import { PLAYBOOKS } from '@/tools/agentPlatform/playbooks'
import { buildToolSurface, renderToolSurface } from '@/tools/agentPlatform/playbookTools'
import type { Context, ToolBase } from '@/tools/types'

const schema = AgentResolveResourceSchema

type Params = z.infer<typeof schema>

type Result = {
    id: string
    uri: string
    title: string
    content: string
    /** Representative tools for this playbook that exist in the live surface, split by callability. */
    tools: { callable: string[]; gated: string[] }
}

export const resolveResourceHandler: ToolBase<typeof schema, Result>['handler'] = async (
    context: Context,
    params: Params
) => {
    // Accept either a bare id or the full resource URI (`PLAYBOOK_URI_PREFIX` + id).
    const id = playbookIdFromRef(params.resource)
    const playbook = id ? PLAYBOOKS[id] : undefined
    if (!playbook?.content) {
        throw new Error(
            `Unknown playbook "${params.resource}". Pass an id (${Object.keys(PLAYBOOKS).join(', ')}) or its URI (${playbookUri(
                Object.keys(PLAYBOOKS)[0] as keyof typeof PLAYBOOKS
            )}).`
        )
    }

    // Append a live tool surface computed against the caller's actual scopes, so the
    // agent reads ground-truth tool names (not stale prose) and sees exactly which
    // are scope-gated — the two things agents keep getting wrong. Best-effort:
    // a missing/erroring key just renders the flat list with required scopes.
    let scopes: string[] | undefined
    try {
        scopes = (await context.stateManager.getApiKey()).scopes
    } catch {
        scopes = undefined
    }
    const refs = buildToolSurface(playbook.id, scopes ?? [])
    const appendix = renderToolSurface(refs, scopes !== undefined)
    const content = appendix ? `${playbook.content.trimEnd()}\n\n${appendix}\n` : playbook.content

    return {
        id: playbook.id,
        uri: playbookUri(playbook.id),
        title: playbook.title,
        content,
        tools: {
            callable: refs.filter((r) => r.missingScopes.length === 0).map((r) => r.name),
            gated: refs.filter((r) => r.missingScopes.length > 0).map((r) => r.name),
        },
    }
}

const tool = (): ToolBase<typeof schema, Result> => ({
    name: 'agent-resolve-resource',
    schema,
    handler: resolveResourceHandler,
})

export default tool
