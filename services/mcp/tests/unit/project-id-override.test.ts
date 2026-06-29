import { describe, expect, it } from 'vitest'
import { z } from 'zod'

import { popProjectIdOverride, withProjectIdOverride } from '@/tools/project-id-override'
import type { ToolBase, ZodObjectAny } from '@/tools/types'

function makeTool(schema: ZodObjectAny): ToolBase<ZodObjectAny> {
    return { name: 'tool', schema, handler: async () => null }
}

describe('project-id-override', () => {
    describe('withProjectIdOverride', () => {
        it('adds an optional projectId to a normal project-scoped tool', () => {
            const result = withProjectIdOverride('insight-get', makeTool(z.object({ insightId: z.number() })))

            // The override rides alongside the tool's own args, and stays optional.
            expect(result.schema.safeParse({ insightId: 1, projectId: 99 }).success).toBe(true)
            expect(result.schema.safeParse({ insightId: 1 }).success).toBe(true)
            // Extending must not drop the tool's existing required fields.
            expect(result.schema.safeParse({ projectId: 99 }).success).toBe(false)
        })

        it('leaves context-switch and explicit-project tools untouched (no colliding param)', () => {
            for (const name of ['switch-project', 'switch-organization', 'get-llm-total-costs-for-project']) {
                const base = makeTool(z.object({ projectId: z.number() }))
                expect(withProjectIdOverride(name, base).schema).toBe(base.schema)
            }
        })

        it('skips schemas that are not plain objects (cannot be extended)', () => {
            const base = makeTool(z.string() as unknown as ZodObjectAny)
            expect(withProjectIdOverride('some-union-tool', base).schema).toBe(base.schema)
        })
    })

    describe('popProjectIdOverride', () => {
        it('extracts the id as a string and strips it from the input', () => {
            const input: Record<string, unknown> = { insightId: 1, projectId: 99 }
            expect(popProjectIdOverride(input)).toBe('99')
            // Must not leak into the handler / downstream request body.
            expect(input).toEqual({ insightId: 1 })
        })

        it('returns undefined and leaves input intact when no override is set', () => {
            const input: Record<string, unknown> = { insightId: 1 }
            expect(popProjectIdOverride(input)).toBeUndefined()
            expect(input).toEqual({ insightId: 1 })
        })
    })
})
