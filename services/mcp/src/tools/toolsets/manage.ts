import type { z } from 'zod'

import { ToolsetsInputSchema } from '@/schema/tool-inputs'
import { getToolDefinitions } from '@/tools/toolDefinitions'
import {
    TOOLSETS,
    type ToolsetId,
    getToolsetById,
    isValidToolsetId,
    toolsetIdForFeature,
} from '@/tools/toolsets/taxonomy'
import type { Context, ToolBase } from '@/tools/types'

const schema = ToolsetsInputSchema
type Params = z.infer<typeof schema>

export const ENABLED_TOOLSETS_KEY = 'enabledToolsets' as const

async function readEnabled(context: Context): Promise<ToolsetId[]> {
    const raw = (await context.cache.get(ENABLED_TOOLSETS_KEY as any)) as ToolsetId[] | undefined
    return raw ?? []
}

async function writeEnabled(context: Context, ids: ToolsetId[]): Promise<void> {
    const dedup = Array.from(new Set(ids))
    await context.cache.set(ENABLED_TOOLSETS_KEY as any, dedup as any)
}

function toolsInToolset(toolsetId: ToolsetId, version?: number): { name: string; description: string }[] {
    const defs = getToolDefinitions(version)
    return Object.entries(defs)
        .filter(([_, meta]) => toolsetIdForFeature(meta.feature) === toolsetId)
        .map(([name, meta]) => ({ name, description: meta.summary }))
}

export const toolsetsHandler = async (context: Context, params: Params): Promise<unknown> => {
    const { action, name } = params

    if (action === 'list') {
        const enabled = await readEnabled(context)
        return {
            toolsets: TOOLSETS.map((ts) => ({
                id: ts.id,
                title: ts.title,
                description: ts.description,
                enabled: enabled.includes(ts.id),
            })),
            enabled,
            usage: "Call toolsets(action='enable', name='<id>') to activate a toolset.",
        }
    }

    if (!name) {
        return {
            error: `Action '${action}' requires a 'name' parameter. Call toolsets(action='list') to see valid ids.`,
        }
    }

    if (!isValidToolsetId(name)) {
        return {
            error: `Unknown toolset '${name}'. Call toolsets(action='list') to see valid ids.`,
        }
    }

    if (action === 'describe') {
        const toolset = getToolsetById(name)
        if (!toolset) {
            return { error: `Unknown toolset '${name}'.` }
        }
        return {
            id: toolset.id,
            title: toolset.title,
            description: toolset.description,
            tools: toolsInToolset(name),
        }
    }

    if (action === 'enable') {
        const enabled = await readEnabled(context)
        if (!enabled.includes(name)) {
            enabled.push(name)
            await writeEnabled(context, enabled)
        }
        const toolNames = toolsInToolset(name).map((t) => t.name)
        return {
            enabled: name,
            enabledNow: enabled,
            newlyAvailableTools: toolNames,
            note: `Tools in this toolset are now callable. If your MCP client supports tools/list_changed, they will appear automatically. If not, ask the user to reconnect with ?progressive=true&toolsets=${enabled.join(',')}`,
        }
    }

    if (action === 'disable') {
        const enabled = await readEnabled(context)
        const next = enabled.filter((id) => id !== name)
        await writeEnabled(context, next)
        return {
            disabled: name,
            enabledNow: next,
        }
    }

    return { error: `Unknown action '${action}'.` }
}

const tool = (): ToolBase<typeof schema> => ({
    name: 'toolsets',
    schema,
    handler: toolsetsHandler,
})

export default tool
