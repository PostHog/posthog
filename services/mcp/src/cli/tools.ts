import { TOOL_MAP } from '@/tools'
import { GENERATED_TOOL_MAP } from '@/tools/generated'
import { mergeToolFactories } from '@/tools/mergeToolFactories'
import { type ToolDefinition, getToolDefinition, getToolsForFeatures } from '@/tools/toolDefinitions'
import type { Tool, ToolBase, ZodObjectAny } from '@/tools/types'

export interface CatalogTools {
    definitions: Record<string, ToolDefinition>
    build: Record<string, () => ToolBase<ZodObjectAny>>
    onUnbuildable: (name: string, reason: string) => void
}

interface CliToolOptions {
    aiConsentGiven?: boolean | undefined
    catalog?: CatalogTools
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
    const { catalog } = options
    // Hand-written TOOL_MAP wins on collision (same as tool-catalog / getToolsFromContext).
    const factories: Record<string, () => ToolBase<ZodObjectAny>> = mergeToolFactories({
        generated: GENERATED_TOOL_MAP,
        handwritten: TOOL_MAP,
    })
    const names = getToolsForFeatures({
        aiConsentGiven: options.aiConsentGiven,
        ...(catalog ? { definitions: catalog.definitions } : {}),
    })

    const tools: Tool<ZodObjectAny>[] = []
    for (const name of names) {
        const fromCatalog = catalog && Object.prototype.hasOwnProperty.call(catalog.build, name) && !(name in TOOL_MAP)
        if (fromCatalog) {
            try {
                tools.push(materializeTool(name, catalog.build[name]!, catalog.definitions[name]!))
                continue
            } catch {
                catalog.onUnbuildable(name, "its input schema can't be read by this hog")
            }
        }

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
