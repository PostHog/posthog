import { z } from 'zod'

import { GENERATED_TOOL_MAP } from '@/tools/generated'
import { getToolDefinition } from '@/tools/toolDefinitions'

import catalogToolsJson from '../../../schema/cli-catalog-tools.json'
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

export function buildCliCatalog(build: string | null): BuiltCatalog {
    const plans = catalogToolsJson as Record<string, unknown>
    const tools: CatalogEntry[] = []
    for (const [name, rawPlan] of Object.entries(plans)) {
        const factory = GENERATED_TOOL_MAP[name]
        if (!factory) {
            continue
        }
        const plan: CatalogHttpTool = CatalogHttpToolSchema.parse(rawPlan)
        tools.push({
            ...plan,
            definition: getToolDefinition(name),
            // The spread drops the non-enumerable `~standard` handle, which keeps the zod schema alive.
            inputSchema: { ...z.toJSONSchema(factory().schema, { io: 'input' }) } as Record<string, unknown>,
        })
    }
    return { schemaVersion: CATALOG_SCHEMA_VERSION, minHogVersion: CATALOG_MIN_HOG_VERSION, build, tools }
}
