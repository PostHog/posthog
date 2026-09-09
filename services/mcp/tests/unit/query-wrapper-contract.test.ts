import { describe, expect, it } from 'vitest'
import { z } from 'zod'

import { formatInputValidationError, rewrapFlattenedArguments } from '@/tools/exec'
import { GENERATED_TOOL_MAP } from '@/tools/generated'
import { getToolDefinition } from '@/tools/toolDefinitions'
import type { ToolBase, ZodObjectAny } from '@/tools/types'

/**
 * Tools that take their whole payload under one required `query` object. Agents
 * flatten this shape often — they send `serviceNames` and `dateRange` at the top
 * level — and Zod then strips the misplaced keys, so the call fails on something
 * that reads nothing like the mistake that was made. The logs, APM, and metrics
 * read tools are all built this way.
 *
 * Discovered from the schemas rather than listed, so a new tool with the same
 * shape has to satisfy the contract too.
 */
function queryWrapperTools(): [string, ToolBase<ZodObjectAny>][] {
    const tools: [string, ToolBase<ZodObjectAny>][] = []
    for (const [name, factory] of Object.entries(GENERATED_TOOL_MAP)) {
        const tool = factory()
        let jsonSchema: Record<string, unknown>
        try {
            jsonSchema = z.toJSONSchema(tool.schema, { io: 'input' }) as Record<string, unknown>
        } catch {
            continue
        }
        const required = jsonSchema['required']
        const properties = jsonSchema['properties'] as Record<string, { type?: string }> | undefined
        if (Array.isArray(required) && required.length === 1 && required[0] === 'query') {
            if (properties?.['query']?.type === 'object') {
                tools.push([name, tool])
            }
        }
    }
    return tools
}

/** The first fenced JSON block in a description, parsed. */
function leadExample(
    description: string
): { json: Record<string, unknown>; source: string; offset: number } | undefined {
    const match = /```json\n([\s\S]*?)\n```/.exec(description)
    if (!match) {
        return undefined
    }
    const source = match[1]!
    try {
        return { json: JSON.parse(source) as Record<string, unknown>, source, offset: match.index }
    } catch {
        return undefined
    }
}

/**
 * How far into a description the wrapper example may sit. An agent that reads
 * the opening paragraph and starts composing a call has to have met the wrapper
 * by then — burying it under a workflow section is what the flattening comes
 * from.
 */
const LEAD_EXAMPLE_MAX_OFFSET = 700

/**
 * Every description ships to every MCP client that lists tools, so the example
 * is one line of the smallest call that works — not a tour of the parameters.
 * A longer one also wraps under `oxfmt`, which costs the copyable single line.
 */
const LEAD_EXAMPLE_MAX_LENGTH = 110

describe('tools whose payload sits under a required `query` object', () => {
    const tools = queryWrapperTools()

    it('finds the wrapper tools to check', () => {
        expect(tools.length).toBeGreaterThan(10)
    })

    describe.each(tools)('%s', (name, tool) => {
        const description = getToolDefinition(name).description
        const example = leadExample(description)

        it('leads with a wrapped example the caller can copy', () => {
            expect(example).not.toBeUndefined()
            expect(Object.keys(example!.json)).toContain('query')
            expect(example!.offset).toBeLessThan(LEAD_EXAMPLE_MAX_OFFSET)
            expect(example!.source).not.toContain('\n')
            expect(example!.source.length).toBeLessThanOrEqual(LEAD_EXAMPLE_MAX_LENGTH)
        })

        it('accepts that example', () => {
            const parsed = tool.schema.safeParse(example!.json)
            expect(parsed.error?.issues ?? []).toEqual([])
        })

        it('names the nesting mistake when that example is sent flattened', () => {
            const flattened = example!.json['query'] as Record<string, unknown>
            const rejected = tool.schema.safeParse(flattened, { reportInput: true })
            expect(rejected.success).toBe(false)

            const message = formatInputValidationError(name, rejected.error!, flattened, tool.schema)

            expect(message).toContain('missing required parameter: query')
            expect(message).toContain('the fields you sent belong inside it')
            expect(message).toContain('resend them as {"query": {')
        })

        it('rewraps that flattened example back into the call the caller meant', () => {
            const flattened = example!.json['query'] as Record<string, unknown>
            const rejected = tool.schema.safeParse(flattened, { reportInput: true })

            const rewrapped = rewrapFlattenedArguments(rejected.error!, flattened, tool.schema)

            expect(rewrapped).toEqual(example!.json)
        })
    })
})
