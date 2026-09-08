import { describe, expect, it } from 'vitest'
import { z } from 'zod'

import { TOOL_MAP } from '@/tools'
import { GENERATED_TOOL_MAP } from '@/tools/generated'
import { getToolDefinitions } from '@/tools/toolDefinitions'
import type { ToolBase, ZodObjectAny } from '@/tools/types'

/**
 * A tool whose whole payload sits under a required `query` object is the shape
 * callers flatten: they send `{dateRange, limit}` where `{query: {dateRange,
 * limit}}` was wanted, and the call is rejected before it reaches the API.
 *
 * The guard is one valid example in the tool's own description. These tests keep
 * every such tool carrying one, and keep each example a payload the tool would
 * actually accept — a documented example that stopped parsing teaches the
 * flattening mistake it was written to prevent.
 */

type JsonSchema = Record<string, unknown>

function isRecord(value: unknown): value is JsonSchema {
    return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function inputJsonSchema(tool: ToolBase<ZodObjectAny>): JsonSchema | undefined {
    if (tool.rawInputSchema) {
        return tool.rawInputSchema
    }
    try {
        return z.toJSONSchema(tool.schema, { io: 'input' }) as JsonSchema
    } catch {
        return undefined
    }
}

/** Whether `query` is a required top-level object (or union of object variants). */
function requiresNestedQuery(schema: JsonSchema | undefined): boolean {
    const required = schema?.['required']
    if (!Array.isArray(required) || !required.includes('query')) {
        return false
    }
    const properties = schema?.['properties']
    const query = isRecord(properties) ? properties['query'] : undefined
    if (!isRecord(query)) {
        return false
    }
    if (query['type'] === 'object' && query['properties']) {
        return true
    }
    const variants = query['anyOf'] ?? query['oneOf']
    return (
        Array.isArray(variants) &&
        variants.length > 0 &&
        variants.every((variant) => isRecord(variant) && variant['type'] === 'object')
    )
}

/** Every fenced ```json block in a description, parsed; unparseable blocks are
 *  skipped because a description may show a fragment rather than a whole call. */
function jsonExamples(description: string): unknown[] {
    const examples: unknown[] = []
    for (const match of description.matchAll(/```json\n([\s\S]*?)```/g)) {
        try {
            examples.push(JSON.parse(match[1]!))
        } catch {
            continue
        }
    }
    return examples
}

const allFactories: Record<string, () => ToolBase<ZodObjectAny>> = { ...TOOL_MAP, ...GENERATED_TOOL_MAP }
const definitions = getToolDefinitions()

const wrapperTools = Object.entries(allFactories).flatMap(([name, factory]) => {
    const tool = factory()
    return requiresNestedQuery(inputJsonSchema(tool)) ? [[name, tool] as const] : []
})

describe('tools that require a nested query object', () => {
    it('finds the wrapper tools to check', () => {
        // Guards the discovery itself: a refactor that stops matching any tool would
        // otherwise turn every case below into a silent no-op.
        expect(wrapperTools.length).toBeGreaterThan(15)
        expect(wrapperTools.map(([name]) => name)).toEqual(
            expect.arrayContaining(['query-logs', 'query-apm-spans', 'read-data-schema'])
        )
    })

    it.each(wrapperTools.map(([name]) => name))('%s documents an example its own schema accepts', (name) => {
        const tool = allFactories[name]!()
        const description = definitions[name]?.description ?? ''
        const accepted = jsonExamples(description).filter(
            (example) => isRecord(example) && 'query' in example && tool.schema.safeParse(example).success
        )

        expect(
            accepted.length,
            `${name} needs a \`\`\`json example wrapping its parameters in "query" that its schema accepts`
        ).toBeGreaterThan(0)
    })
})
