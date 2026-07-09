import { TOOL_MAP } from '@/tools'
import { GENERATED_TOOL_MAP } from '@/tools/generated'
import { type ToolDefinition, getToolDefinition, getToolsForFeatures } from '@/tools/toolDefinitions'
import type { Tool, ToolBase, ZodObjectAny } from '@/tools/types'

interface CliToolOptions {
    aiConsentGiven?: boolean | undefined
}

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
            continue
        }

        try {
            const definition = getToolDefinition(name)
            tools.push(materializeTool(name, () => factory(), definition))
        } catch {
            continue
        }
    }

    return tools.sort((a, b) => a.name.localeCompare(b.name))
}
