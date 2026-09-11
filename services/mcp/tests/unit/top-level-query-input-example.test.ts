import { describe, expect, it } from 'vitest'
import { z } from 'zod'

import { createExecTool } from '@/tools/exec'
import { GENERATED_TOOL_MAP } from '@/tools/generated'
import { getToolDefinitions } from '@/tools/toolDefinitions'
import type { Context, Tool, ToolBase, ZodObjectAny } from '@/tools/types'

/**
 * The mirror of `nested-query-input-example.test.ts`: a query wrapper takes the
 * query fields as its own top-level parameters, so an example written as a query
 * document teaches a call the tool rejects.
 *
 * Every documented example is checked through both routes a caller reaches the
 * tool by: the schema directly, and the `exec` CLI behind `call <tool> <json>`.
 */

const TOP_LEVEL_QUERY_TOOLS = [
    'query-trends',
    'query-funnel',
    'query-retention',
    'query-stickiness',
    'query-paths',
    'query-lifecycle',
] as const

const definitions = getToolDefinitions()

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

/** Every field the example sets that the parsed input no longer carries. */
function droppedFields(sent: unknown, accepted: unknown, trail = ''): string[] {
    if (Array.isArray(sent)) {
        return Array.isArray(accepted)
            ? sent.flatMap((item, index) => droppedFields(item, accepted[index], `${trail}[${index}]`))
            : [trail]
    }
    if (typeof sent !== 'object' || sent === null) {
        return []
    }
    if (typeof accepted !== 'object' || accepted === null) {
        return [trail]
    }
    return Object.entries(sent).flatMap(([key, value]) => {
        const path = trail ? `${trail}.${key}` : key
        const held = accepted as Record<string, unknown>
        return key in held ? droppedFields(value, held[key], path) : [path]
    })
}

const mockContext = { getDistinctId: async () => 'test-distinct-id' } as unknown as Context

/** The generated tool with its handler replaced, so a `call` exercises the
 *  validation gate without reaching the API. */
function asExecutableTool(name: string, base: ToolBase<ZodObjectAny>): Tool<ZodObjectAny> {
    return {
        ...base,
        title: name,
        description: definitions[name]?.description ?? '',
        scopes: [],
        annotations: { destructiveHint: false, idempotentHint: true, openWorldHint: false, readOnlyHint: true },
        handler: async () => ({ results: [] }),
    }
}

describe('tools that take their query fields at the top level', () => {
    it.each(TOP_LEVEL_QUERY_TOOLS)('%s takes no nested query parameter', (name) => {
        // Guards the premise: were one of these to grow a `query` wrapper, its
        // examples would have to nest, and the cases below would be backwards.
        const schema = z.toJSONSchema(GENERATED_TOOL_MAP[name]!().schema, { io: 'input' }) as Record<string, unknown>
        const properties = schema['properties'] as Record<string, unknown> | undefined

        expect(properties && 'query' in properties).toBeFalsy()
    })

    it.each(TOP_LEVEL_QUERY_TOOLS)('%s documents examples its own schema accepts', (name) => {
        const tool = GENERATED_TOOL_MAP[name]!()
        const examples = jsonExamples(definitions[name]?.description ?? '')

        expect(examples.length, `${name} needs at least one \`\`\`json example`).toBeGreaterThan(0)
        for (const example of examples) {
            const result = tool.schema.safeParse(example)
            expect(result.success, `${name} documents an example it rejects: ${JSON.stringify(result)}`).toBe(true)
        }
    })

    it.each(TOP_LEVEL_QUERY_TOOLS)('%s accepts its documented examples through the exec CLI', async (name) => {
        const exec = createExecTool(
            [asExecutableTool(name, GENERATED_TOOL_MAP[name]!())],
            mockContext,
            'test description',
            'test command reference',
            undefined
        )

        for (const example of jsonExamples(definitions[name]?.description ?? '')) {
            const output = await exec
                .handler(mockContext, { command: `call ${name} ${JSON.stringify(example)}` })
                .catch((error: Error) => `rejected: ${error.message}`)

            expect(String(output)).not.toContain('Invalid input')
        }
    })

    // Parsing alone does not prove an example works: these schemas drop fields
    // they do not declare, so an example naming one is accepted and then quietly
    // loses it. Scoped to trends — `query-funnel` documents `name` on a grouped
    // step's inner nodes, and its schema drops that.
    it('query-trends documents examples that keep every field they set', () => {
        const tool = GENERATED_TOOL_MAP['query-trends']!()

        for (const example of jsonExamples(definitions['query-trends']?.description ?? '')) {
            const result = tool.schema.safeParse(example)

            expect(result.success).toBe(true)
            expect(droppedFields(example, result.data)).toEqual([])
        }
    })

    it('documents both a single-series and a multi-series trends example', () => {
        const series = jsonExamples(definitions['query-trends']?.description ?? '')
            .filter((example): example is { series: unknown[] } => Array.isArray((example as any)?.series))
            .map((example) => example.series.length)

        expect(series).toContain(1)
        expect(series.some((count) => count > 1)).toBe(true)
    })
})
