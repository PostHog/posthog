import { describe, expect, it } from 'vitest'
import { z } from 'zod'

import { GENERATED_TOOLS } from '@/tools/generated/signals'
import { resolveSchemaPath, summarizeSchema } from '@/tools/schema-utils'

const METRIC_GOAL_FIELDS = ['goal_value', 'goal_direction', 'goal_grain', 'decision_window_days', 'minimum_data_points']

// The emit-report schema overflows the exec output budget, so callers read the compact summary.
// A long summary gets cut off, so the conditional rule must sit before the per-field properties.
describe('scout-emit-report schema summary', () => {
    it.each(['scout-emit-report', 'signals-scout-emit-report'])(
        'lists the required fields and priority_explanation with priority before the properties in %s',
        (toolName) => {
            const tool = GENERATED_TOOLS[toolName]!()
            const jsonSchema = z.toJSONSchema(tool.schema, { io: 'input' }) as Record<string, unknown>

            const summary = summarizeSchema(jsonSchema, toolName)

            expect(summary.required).toEqual(
                expect.arrayContaining(['title', 'summary', 'evidence', 'actionability_explanation', 'actionability'])
            )
            expect(summary.requiredWhenSet).toEqual({ priority: ['priority_explanation'] })
            const keys = Object.keys(summary)
            expect(keys.indexOf('requiredWhenSet')).toBeLessThan(keys.indexOf('properties'))
        }
    )

    // The report writer rejects metric goals, so the published schema must not offer them.
    it.each(['scout-emit-report', 'scout-edit-report'])('does not advertise metric goal fields in %s', (toolName) => {
        const tool = GENERATED_TOOLS[toolName]!()
        const jsonSchema = z.toJSONSchema(tool.schema, { io: 'input' }) as Record<string, unknown>

        expect(resolveSchemaPath(jsonSchema, 'metrics.query')).not.toBeNull()
        for (const field of METRIC_GOAL_FIELDS) {
            expect(resolveSchemaPath(jsonSchema, `metrics.${field}`)).toBeNull()
        }
    })
})
