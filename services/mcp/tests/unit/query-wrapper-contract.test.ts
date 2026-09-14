import { describe, expect, it } from 'vitest'
import { z } from 'zod'

import { formatInputValidationError, rewrapFlattenedArguments } from '@/tools/exec'
import { GENERATED_TOOL_MAP } from '@/tools/generated'
import { getToolDefinition } from '@/tools/toolDefinitions'
import type { ToolBase, ZodObjectAny } from '@/tools/types'

/** Read from the schemas rather than listed, so a new tool with this shape has to satisfy the contract too. */
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

/** An example below this offset sits under a workflow section, which a caller reaches after it composed the call. */
const LEAD_EXAMPLE_MAX_OFFSET = 700

/** Every description ships on every tools/list, and a longer example also wraps under `oxfmt`. */
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
