/**
 * Regression tests for narrow string→int casts on experiment tool schemas.
 *
 * Production traces showed agents intermittently sending stringified ids
 * (`"123"` instead of `123`) on `experiment-get` / `-update` / `-list` /
 * `-duplicate` and friends, which the MCP layer then rejected with
 * `MCP error -32602: Invalid input: expected number, received string`.
 * (`experiment-results-get` sees the same shape but is handwritten via
 * `services/mcp/src/schema/tool-inputs.ts` and not covered by this PR.)
 *
 * The fix is declarative — `param_overrides: { id: { cast: 'string-int' } }`
 * in `products/experiments/mcp/tools.yaml` — wired through the codegen to
 * wrap the field's existing zod schema with `z.preprocess(castStringToInt, ...)`.
 *
 * These tests pin the runtime behavior end-to-end so the override can't
 * silently regress when the codegen, the YAML, or the schema source changes.
 * They also assert the safety properties: no surprising `true → 1` /
 * `null → 0` behavior, only true stringified-int casts.
 */
import { describe, expect, it } from 'vitest'
import { z } from 'zod'

import { GENERATED_TOOLS } from '@/tools/generated/experiments'
import type { ToolBase, ZodObjectAny } from '@/tools/types'

const PROJECT_ID = '2'

/** Resolve a generated tool's input schema. Cast through `unknown` so individual
 *  test cases can assert on parsed fields without TypeScript widening to `unknown`. */
function getToolSchema(toolName: keyof typeof GENERATED_TOOLS): z.ZodTypeAny {
    const factory = GENERATED_TOOLS[toolName] as () => ToolBase<ZodObjectAny>
    return factory().schema as z.ZodTypeAny
}

/** Wrapper around `schema.parse` that returns a record so tests don't have to
 *  cast on every access. The underlying schema runtime guarantees an object
 *  shape for each generated tool's params. */
function parseWith(schema: z.ZodTypeAny, input: unknown): Record<string, unknown> {
    return schema.parse(input) as Record<string, unknown>
}

describe('experiment tool schemas — id/limit cast', () => {
    describe('experiment-get', () => {
        const schema = getToolSchema('experiment-get')

        it('accepts id as a stringified integer and casts it', () => {
            const parsed = parseWith(schema, { id: '123', project_id: PROJECT_ID })
            expect(parsed.id).toBe(123)
            expect(typeof parsed.id).toBe('number')
        })

        it('still accepts id as a plain number', () => {
            const parsed = parseWith(schema, { id: 123, project_id: PROJECT_ID })
            expect(parsed.id).toBe(123)
        })

        // Safety: we explicitly DO NOT want `z.coerce.number()` semantics, where
        // `true → 1`, `null → 0`, etc. These should still reject so genuine
        // type errors surface honestly instead of silently 404-ing the API.
        it.each([
            ['boolean true', true],
            ['null', null],
            ['empty string', ''],
            ['decimal string', '1.5'],
            ['non-numeric string', 'abc'],
        ] as const)('rejects unsafe input: %s', (_label, badId) => {
            expect(() => schema.parse({ id: badId, project_id: PROJECT_ID })).toThrow()
        })
    })

    describe('experiment-update', () => {
        const schema = getToolSchema('experiment-update')

        it('accepts id as a stringified integer', () => {
            const parsed = parseWith(schema, { id: '456', project_id: PROJECT_ID })
            expect(parsed.id).toBe(456)
            expect(typeof parsed.id).toBe('number')
        })
    })

    describe('experiment-duplicate', () => {
        const schema = getToolSchema('experiment-duplicate')

        it('accepts id as a stringified integer', () => {
            // Duplicate requires `name` and `feature_flag_key` on top of the id.
            const parsed = parseWith(schema, {
                id: '789',
                project_id: PROJECT_ID,
                name: 'A duplicate',
                feature_flag_key: 'duplicated-flag',
            })
            expect(parsed.id).toBe(789)
            expect(typeof parsed.id).toBe('number')
        })
    })

    describe('experiment-list', () => {
        const schema = getToolSchema('experiment-list')

        it('accepts limit as a stringified integer', () => {
            const parsed = parseWith(schema, { limit: '50' })
            expect(parsed.limit).toBe(50)
            expect(typeof parsed.limit).toBe('number')
        })

        it('accepts offset as a stringified integer', () => {
            const parsed = parseWith(schema, { offset: '100' })
            expect(parsed.offset).toBe(100)
        })

        it('accepts created_by_id as a stringified integer', () => {
            const parsed = parseWith(schema, { created_by_id: '42' })
            expect(parsed.created_by_id).toBe(42)
        })

        it('accepts feature_flag_id as a stringified integer', () => {
            const parsed = parseWith(schema, { feature_flag_id: '7' })
            expect(parsed.feature_flag_id).toBe(7)
        })
    })
})
