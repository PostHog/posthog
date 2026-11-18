import { z } from 'zod'

import { normalizeParamAliases, readParamAliases } from '@/tools/cast-helpers'
import type { ToolBase, ZodObjectAny } from '@/tools/types'

const MAX_PIPE_DEPTH = 8

// A name such as `$set` or `filter_testAccounts` has no clear twin.
const PLAIN_PARAM_NAME = /^(?:[a-z][a-zA-Z0-9]*|[a-z][a-z0-9_]*)$/

function toSnakeCase(name: string): string {
    return name.replace(/[A-Z]/g, (letter) => `_${letter.toLowerCase()}`)
}

function toCamelCase(name: string): string {
    return name.replace(/_([a-z0-9])/g, (_match, letter: string) => letter.toUpperCase())
}

function innerObject(schema: z.ZodType): z.ZodObject | undefined {
    let current: unknown = schema
    for (let depth = 0; depth < MAX_PIPE_DEPTH && current instanceof z.ZodPipe; depth++) {
        // `z.preprocess` puts its transform on `.in`; `.transform()` puts it on `.out`.
        current = current.in instanceof z.ZodTransform ? current.out : current.in
    }
    return current instanceof z.ZodObject ? current : undefined
}

function casingAliasMap(schema: z.ZodType): Record<string, readonly string[]> | undefined {
    const object = innerObject(schema)
    if (!object) {
        return undefined
    }
    const declared = new Set(Object.keys(object.shape))
    const existing = readParamAliases(schema) ?? {}
    const existingAliases = new Set(Object.values(existing).flat())
    const aliasMap: Record<string, readonly string[]> = {}
    for (const name of declared) {
        if (!PLAIN_PARAM_NAME.test(name)) {
            continue
        }
        const twin = name.includes('_') ? toCamelCase(name) : toSnakeCase(name)
        if (twin !== name && !declared.has(twin) && !existingAliases.has(twin)) {
            // This layer runs before the tool's own aliases, so it repeats them first to keep them ahead of the twin.
            aliasMap[name] = [...(existing[name] ?? []), twin]
        }
    }
    return Object.keys(aliasMap).length > 0 ? aliasMap : undefined
}

// Factories often return a module-level schema, so one wrapped schema serves every call.
const WRAPPED_SCHEMAS = new WeakMap<z.ZodType, z.ZodType>()

/**
 * Tool params mix camelCase and snake_case, and agents guess the casing, so each param also
 * accepts its other casing. `normalizeParamAliases` keeps the advertised schema unchanged.
 */
export function withCasingAliases<T extends ZodObjectAny>(tool: ToolBase<T>): ToolBase<T> {
    let wrapped = WRAPPED_SCHEMAS.get(tool.schema)
    if (!wrapped) {
        const aliasMap = casingAliasMap(tool.schema)
        wrapped = aliasMap ? z.preprocess(normalizeParamAliases(aliasMap), tool.schema) : tool.schema
        WRAPPED_SCHEMAS.set(tool.schema, wrapped)
    }
    return wrapped === tool.schema ? tool : { ...tool, schema: wrapped as unknown as T }
}
