import { z } from 'zod'

import { isStaffOnlyTool } from '@/lib/staff-only-tools'
import { GENERATED_TOOL_MAP } from '@/tools/generated'
import { getToolDefinition } from '@/tools/toolDefinitions'

import catalogToolsJson from '../../../schema/cli-catalog-tools.json'
import { hookVersion } from './hook-versions'
import {
    CATALOG_MIN_HOG_VERSION,
    CATALOG_SCHEMA_VERSION,
    type CatalogEntry,
    CatalogHttpToolSchema,
    type CatalogHttpTool,
} from './schema'

export interface BuiltCatalog {
    schemaVersion: number
    minHogVersion: string
    build: string | null
    tools: CatalogEntry[]
}

function versionedHook(capability: string): string {
    if (!capability.startsWith('hook:')) {
        return capability
    }
    const name = capability.slice('hook:'.length)
    const version = hookVersion(name)
    if (version === undefined) {
        throw new Error(`The hook ${name} has no version in hook-versions.ts.`)
    }
    return `${capability}@${version}`
}

export function buildCliCatalog(build: string | null): BuiltCatalog {
    const plans = catalogToolsJson as Record<string, unknown>
    const tools: CatalogEntry[] = []
    for (const [name, rawPlan] of Object.entries(plans)) {
        const factory = GENERATED_TOOL_MAP[name]
        if (!factory) {
            continue
        }
        const definition = getToolDefinition(name)
        // The catalog is public. Staff-only tools stay compiled in, the way MCP sessions hide them.
        if (isStaffOnlyTool(definition.required_scopes ?? [])) {
            continue
        }
        const plan: CatalogHttpTool = CatalogHttpToolSchema.parse(rawPlan)
        tools.push({
            ...plan,
            requires: plan.requires.map(versionedHook),
            definition,
            // The spread drops the non-enumerable `~standard` handle, which keeps the zod schema alive.
            inputSchema: { ...z.toJSONSchema(factory().schema, { io: 'input' }) } as Record<string, unknown>,
        })
    }
    return { schemaVersion: CATALOG_SCHEMA_VERSION, minHogVersion: CATALOG_MIN_HOG_VERSION, build, tools }
}
