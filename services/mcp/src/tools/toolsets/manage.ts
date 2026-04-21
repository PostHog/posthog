import type { z } from 'zod'

import { ToolsetsInputSchema } from '@/schema/tool-inputs'
import { getToolDefinitions } from '@/tools/toolDefinitions'
import {
    COMPOSITE_TOOLSETS,
    expandToolsetToFeatures,
    getAllToolsets,
    getToolsetById,
    isValidToolsetId,
} from '@/tools/toolsets/taxonomy'
import type { Context, ToolBase } from '@/tools/types'

const schema = ToolsetsInputSchema
type Params = z.infer<typeof schema>

/**
 * DO cache key for the set of enabled toolset IDs (base or composite). Stored as-is;
 * expansion to features happens at filter/registration time via resolveEnabledFeatures.
 */
export const ENABLED_TOOLSETS_KEY = 'enabledToolsets' as const

async function readEnabled(context: Context): Promise<string[]> {
    const raw = (await context.cache.get(ENABLED_TOOLSETS_KEY as any)) as string[] | undefined
    return raw ?? []
}

async function writeEnabled(context: Context, ids: string[]): Promise<void> {
    const dedup = Array.from(new Set(ids))
    await context.cache.set(ENABLED_TOOLSETS_KEY as any, dedup as any)
}

function toolsForFeatures(features: string[], version?: number): { name: string; description: string }[] {
    const defs = getToolDefinitions(version)
    const featureSet = new Set(features)
    return Object.entries(defs)
        .filter(([_, meta]) => featureSet.has(meta.feature))
        .map(([name, meta]) => ({ name, description: meta.summary }))
}

export const toolsetsHandler = async (context: Context, params: Params): Promise<unknown> => {
    const { action, name } = params

    if (action === 'list') {
        const enabled = await readEnabled(context)
        const all = getAllToolsets()
        // Group base vs composite in the response so the model sees the two layers clearly.
        const base = all.filter((ts) => ts.isBase)
        const composites = all.filter((ts) => !ts.isBase)
        return {
            composites: composites.map((ts) => ({
                id: ts.id,
                title: ts.title,
                description: ts.description,
                bundles: ts.features,
                enabled: enabled.includes(ts.id),
            })),
            base: base.map((ts) => ({
                id: ts.id,
                title: ts.title,
                description: ts.description,
                enabled: enabled.includes(ts.id),
            })),
            enabled,
            usage:
                "Call toolsets(action='enable', name='<id>') to activate a toolset. Composites bundle " +
                'multiple base toolsets; base toolsets map 1:1 to a PostHog product area.',
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
        const features = expandToolsetToFeatures(name)
        return {
            id: toolset.id,
            title: toolset.title,
            description: toolset.description,
            composite: !toolset.isBase,
            bundles: toolset.isBase ? undefined : features,
            tools: toolsForFeatures(features),
        }
    }

    if (action === 'enable') {
        const enabled = await readEnabled(context)
        if (!enabled.includes(name)) {
            enabled.push(name)
            await writeEnabled(context, enabled)
        }
        const features = expandToolsetToFeatures(name)
        const toolNames = toolsForFeatures(features).map((t) => t.name)
        const reconnectQuery = `?progressive=true&toolsets=${enabled.join(',')}`
        return {
            enabled: name,
            enabledNow: enabled,
            expandedFeatures: features,
            newlyAvailableTools: toolNames,
            // Keep this terse and action-first. Empirically, wordy notes get Sonnet-class
            // models to retry-and-thrash before surfacing the reconnect. Leading with the
            // concrete instruction reduces wasted turns.
            nextStep: `If calling a newly-available tool returns "No such tool available", ask the user to reconnect the MCP with: ${reconnectQuery}`,
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

// Re-export for callers that need the composites table
export { COMPOSITE_TOOLSETS }

const tool = (): ToolBase<typeof schema> => ({
    name: 'toolsets',
    schema,
    handler: toolsetsHandler,
})

export default tool
