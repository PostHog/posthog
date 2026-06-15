import { TOOL_MAP } from '@/tools'
import { GENERATED_TOOL_MAP } from '@/tools/generated'
import { type ToolDefinition, getToolDefinition, getToolsForFeatures } from '@/tools/toolDefinitions'
import type { Tool, ToolBase, ZodObjectAny } from '@/tools/types'

interface CliToolOptions {
    aiConsentGiven?: boolean | undefined
}

const warnedSkippedTools = new Set<string>()

function materializeTool(
    name: string,
    factory: () => ToolBase<ZodObjectAny>,
    definition: ToolDefinition
): Tool<ZodObjectAny> {
    return {
        ...factory(),
        title: definition.title,
        description: definition.description,
        scopes: definition.required_scopes ?? [],
        annotations: definition.annotations,
    }
}

function warnSkippedTool(name: string, reason: unknown): void {
    const detail = reason instanceof Error ? reason.message : String(reason)
    const warningKey = `${name}:${detail}`
    if (warnedSkippedTools.has(warningKey)) {
        return
    }
    warnedSkippedTools.add(warningKey)
    process.stderr.write(`Warning: Skipping PostHog API tool "${name}": ${detail}\n`)
}

export function getCliTools(options: CliToolOptions = {}): Tool<ZodObjectAny>[] {
    const factories: Record<string, () => ToolBase<ZodObjectAny>> = {
        ...TOOL_MAP,
        ...GENERATED_TOOL_MAP,
    }
    const names = getToolsForFeatures({
        aiConsentGiven: options.aiConsentGiven,
    })

    const tools: Tool<ZodObjectAny>[] = []
    for (const name of names) {
        const factory = factories[name]
        if (!factory) {
            warnSkippedTool(name, 'no implementation factory was registered')
            continue
        }

        try {
            const definition = getToolDefinition(name)
            tools.push(materializeTool(name, () => factory(), definition))
        } catch (error) {
            warnSkippedTool(name, error)
            continue
        }
    }

    return tools.sort((a, b) => a.name.localeCompare(b.name))
}
