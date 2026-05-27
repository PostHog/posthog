import { RESOURCE_URI_META_KEY } from '@modelcontextprotocol/ext-apps/server'
import { toJsonSchemaCompat } from '@modelcontextprotocol/sdk/server/zod-json-schema-compat.js'

import { hasScopes } from '@/lib/api'
import {
    type ToolDefinition,
    type ToolFilterOptions,
    getToolDefinitions,
    getToolsForFeatures,
} from '@/tools/toolDefinitions'
import type { Tool, ToolBase, ZodObjectAny } from '@/tools/types'

import type { Tool as McpTool } from '@modelcontextprotocol/sdk/types.js'

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

export type { PreBuiltTool }

const EMPTY_OBJECT_JSON_SCHEMA = { type: 'object' as const, properties: {} }

export class ToolCatalog {
    private _preBuilt: Map<string, PreBuiltTool> = new Map()
    private _entries: McpTool[] = []
    private _entriesByName = new Map<string, McpTool>()
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

        this._buildEntries()

        this._warmedUp = true
        console.info(
            `[ToolCatalog] warmup complete: ${this._preBuilt.size} tools in ${(performance.now() - start).toFixed(0)}ms`
        )
    }

    private _buildEntries(): void {
        this._entries = []
        this._entriesByName = new Map()

        for (const [name, preBuilt] of this._preBuilt) {
            const def = preBuilt.definitions.v1 ?? preBuilt.definitions.v2
            if (!def) {
                continue
            }

            let jsonSchema: Record<string, unknown>
            try {
                jsonSchema = toJsonSchemaCompat(preBuilt.base.schema, { strictUnions: true }) as Record<string, unknown>
                delete jsonSchema['$schema']
                delete jsonSchema['additionalProperties']
                // MCP requires inputSchema.type === 'object'. Top-level discriminated unions
                // (e.g. `oneOf` on a polymorphic request body) come back without a root `type`.
                // Add it so the schema satisfies the MCP tool contract; the union constraint
                // still applies via the nested anyOf/oneOf.
                if (
                    !jsonSchema['type'] &&
                    (Array.isArray(jsonSchema['anyOf']) || Array.isArray(jsonSchema['oneOf']))
                ) {
                    jsonSchema = { type: 'object', ...jsonSchema }
                }
            } catch {
                jsonSchema = EMPTY_OBJECT_JSON_SCHEMA
            }

            let meta = preBuilt.base._meta as Record<string, unknown> | undefined
            if (meta?.ui && typeof meta.ui === 'object' && 'resourceUri' in meta.ui && !meta[RESOURCE_URI_META_KEY]) {
                meta = {
                    ...meta,
                    [RESOURCE_URI_META_KEY]: (meta.ui as Record<string, unknown>).resourceUri,
                }
            }

            const entry: McpTool = {
                name,
                title: def.title,
                description: def.description,
                inputSchema: jsonSchema as McpTool['inputSchema'],
                annotations: def.annotations as McpTool['annotations'],
                ...(meta ? { _meta: meta } : {}),
            }
            this._entries.push(entry)
            this._entriesByName.set(name, entry)
        }
    }

    getAllPreBuilt(): ReadonlyMap<string, PreBuiltTool> {
        return this._preBuilt
    }

    getToolByName(name: string): PreBuiltTool | undefined {
        return this._preBuilt.get(name)
    }

    getPreBuiltEntries(): McpTool[] {
        return this._entries
    }

    getPreBuiltEntry(name: string): McpTool | undefined {
        return this._entriesByName.get(name)
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
