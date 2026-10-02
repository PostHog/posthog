import { describe, expect, it } from 'vitest'
import { z } from 'zod'

import { GENERATED_TOOLS } from '@/tools/generated/signals'
import { summarizeSchema } from '@/tools/schema-utils'

// The emit-report schema overflows the exec output budget, so callers read the compact summary.
// A long summary gets cut off, so the conditional rule must sit before the per-field properties.
describe('scout-emit-report schema summary', () => {
    it.each(['scout-emit-report', 'signals-scout-emit-report'])(
        'lists priority_explanation as required with priority before the properties in %s',
        (toolName) => {
            const tool = GENERATED_TOOLS[toolName]!()
            const jsonSchema = z.toJSONSchema(tool.schema, { io: 'input' }) as Record<string, unknown>

            const summary = summarizeSchema(jsonSchema, toolName)

            expect(summary.requiredWhenSet).toEqual({ priority: ['priority_explanation'] })
            const keys = Object.keys(summary)
            expect(keys.indexOf('requiredWhenSet')).toBeLessThan(keys.indexOf('properties'))
        }
    )
})
