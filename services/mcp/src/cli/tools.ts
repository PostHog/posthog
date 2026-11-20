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

export interface CliToolRegistry {
    get(name: string): Tool<ZodObjectAny> | undefined
    all(): Tool<ZodObjectAny>[]
}

const MAX_RECENT_TOOLS = 32

export function createCliToolRegistry(options: CliToolOptions = {}): CliToolRegistry {
    const { catalog } = options
    // Hand-written TOOL_MAP wins on collision (same as tool-catalog / getToolsFromContext).
    const factories: Record<string, () => ToolBase<ZodObjectAny>> = mergeToolFactories({
        generated: GENERATED_TOOL_MAP,
        handwritten: TOOL_MAP,
    })
    let offered: Set<string> | undefined
    const offeredNames = (): Set<string> =>
        (offered ??= new Set(
            getToolsForFeatures({
                aiConsentGiven: options.aiConsentGiven,
                ...(catalog ? { definitions: catalog.definitions } : {}),
            })
        ))
    // A catalog entry that cannot be built reports to `onUnbuildable` once, because that
    // callback records a dropped tool each time it runs.
    const unbuildable = new Set<string>()
    const recent = new Map<string, Tool<ZodObjectAny>>()
    let everything: Map<string, Tool<ZodObjectAny>> | undefined

    const build = (name: string): Tool<ZodObjectAny> | undefined => {
        const fromCatalog =
            catalog &&
            Object.prototype.hasOwnProperty.call(catalog.build, name) &&
            !(name in TOOL_MAP) &&
            !unbuildable.has(name)
        if (fromCatalog) {
            try {
                return materializeTool(name, catalog.build[name]!, catalog.definitions[name]!)
            } catch {
                unbuildable.add(name)
                catalog.onUnbuildable(name, "its input schema can't be read by this hog")
            }
        }

        const factory = factories[name]
        if (!factory) {
            return undefined
        }

        try {
            return materializeTool(name, () => factory(), getToolDefinition(name))
        } catch {
            return undefined
        }
    }

    const all = (): Map<string, Tool<ZodObjectAny>> => {
        if (!everything) {
            const tools: Tool<ZodObjectAny>[] = []
            for (const name of offeredNames()) {
                const tool = recent.get(name) ?? build(name)
                if (tool) {
                    tools.push(tool)
                }
            }
            tools.sort((a, b) => a.name.localeCompare(b.name))
            everything = new Map(tools.map((tool) => [tool.name, tool]))
            recent.clear()
        }
        return everything
    }

    return {
        get(name) {
            if (everything) {
                return everything.get(name)
            }
            if (!offeredNames().has(name)) {
                return undefined
            }
            const tool = recent.get(name) ?? build(name)
            if (!tool) {
                return undefined
            }
            recent.delete(name)
            recent.set(name, tool)
            if (recent.size > MAX_RECENT_TOOLS) {
                recent.delete(recent.keys().next().value!)
            }
            return tool
        },
        all: () => [...all().values()],
    }
}

export function getCliTools(options: CliToolOptions = {}): Tool<ZodObjectAny>[] {
    return createCliToolRegistry(options).all()
}
