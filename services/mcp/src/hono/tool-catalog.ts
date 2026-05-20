import { hasScopes } from '@/lib/api'
import {
    type ToolDefinition,
    type ToolFilterOptions,
    getToolDefinitions,
    getToolsForFeatures,
} from '@/tools/toolDefinitions'
import type { Tool, ToolBase, ZodObjectAny } from '@/tools/types'

interface PreBuiltTool {
    base: ToolBase<ZodObjectAny>
    definitions: {
        v1: ToolDefinition | undefined
        v2: ToolDefinition | undefined
    }
}

export interface ToolCatalogFilterOptions extends ToolFilterOptions {
    scopes?: string[]
    excludeTools?: string[]
}

export class ToolCatalog {
    private _preBuilt: Map<string, PreBuiltTool> = new Map()
    private _warmedUp = false

    get warmedUp(): boolean {
        return this._warmedUp
    }

    async warmup(): Promise<void> {
        if (this._warmedUp) {
            return
        }

        const start = performance.now()

        const [{ TOOL_MAP }, { GENERATED_TOOL_MAP }] = await Promise.all([
            import('@/tools'),
            import('@/tools/generated'),
        ])

        const allFactories: Record<string, () => ToolBase<ZodObjectAny>> = {
            ...TOOL_MAP,
            ...GENERATED_TOOL_MAP,
        }

        const v1Defs = getToolDefinitions(1)
        const v2Defs = getToolDefinitions(2)

        for (const [name, factory] of Object.entries(allFactories)) {
            const base = factory()
            this._preBuilt.set(name, {
                base,
                definitions: {
                    v1: v1Defs[name],
                    v2: v2Defs[name],
                },
            })
        }

        this._warmedUp = true
        console.info(
            `[ToolCatalog] warmup complete: ${this._preBuilt.size} tools in ${(performance.now() - start).toFixed(0)}ms`
        )
    }

    getFilteredTools(options: ToolCatalogFilterOptions): Tool<ZodObjectAny>[] {
        const { scopes = [], excludeTools = [], ...filterOptions } = options
        const allowedToolNames = getToolsForFeatures(filterOptions).filter((name) => !excludeTools.includes(name))
        const effectiveVersion = filterOptions.version ?? 1

        const tools: Tool<ZodObjectAny>[] = []

        for (const name of allowedToolNames) {
            const preBuilt = this._preBuilt.get(name)
            if (!preBuilt) {
                continue
            }
            const { base } = preBuilt

            if (base.mcpVersion !== undefined && base.mcpVersion !== effectiveVersion) {
                continue
            }

            const definition = preBuilt.definitions[effectiveVersion === 2 ? 'v2' : 'v1'] ?? preBuilt.definitions.v1
            if (!definition) {
                continue
            }

            if (!hasScopes(scopes, definition.required_scopes ?? [])) {
                continue
            }

            tools.push({
                ...base,
                title: definition.title,
                description: definition.description,
                scopes: definition.required_scopes ?? [],
                annotations: definition.annotations,
            })
        }

        return tools
    }
}
