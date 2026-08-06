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

/**
 * One row per lifecycle tool that has `param_overrides: { id: { cast: 'string-int' } }`
 * in tools.yaml. The `extras` map captures each tool's *additional* required-input
 * fields beyond `id`/`project_id`, so the parameterised assertion can build a minimal
 * valid input for every shape. Adding a new cast'd lifecycle tool means appending
 * one row here — the test will then cover it automatically.
 */
const LIFECYCLE_TOOLS_WITH_ID_CAST = [
    ['experiment-archive', {}],
    ['experiment-copy-to-project', { target_team_id: 5 }],
    ['experiment-delete', {}],
    ['experiment-duplicate', { name: 'A duplicate', feature_flag_key: 'duplicated-flag' }],
    ['experiment-end', {}],
    ['experiment-get', {}],
    ['experiment-launch', {}],
    ['experiment-pause', {}],
    ['experiment-reset', {}],
    ['experiment-resume', {}],
    ['experiment-ship-variant', { variant_key: 'test' }],
    ['experiment-timeseries-results', { metric_uuid: 'metric-uuid', fingerprint: 'fp' }],
    ['experiment-unarchive', {}],
    ['experiment-update', {}],
] as const satisfies ReadonlyArray<readonly [keyof typeof GENERATED_TOOLS, Record<string, unknown>]>

describe('experiment lifecycle tools — id cast', () => {
    it.each(LIFECYCLE_TOOLS_WITH_ID_CAST)('%s accepts a stringified id', (toolName, extras) => {
        const parsed = parseWith(getToolSchema(toolName), { id: '123', project_id: PROJECT_ID, ...extras })
        expect(parsed.id).toBe(123)
        expect(typeof parsed.id).toBe('number')
    })

    it.each(LIFECYCLE_TOOLS_WITH_ID_CAST)('%s still accepts a plain numeric id', (toolName, extras) => {
        const parsed = parseWith(getToolSchema(toolName), { id: 123, project_id: PROJECT_ID, ...extras })
        expect(parsed.id).toBe(123)
    })
})

describe('experiment-get — safety: must still reject non-int input', () => {
    // We explicitly DO NOT want `z.coerce.number()` semantics, where `true → 1`,
    // `null → 0`, etc. These should still reject so genuine type errors surface
    // honestly instead of silently 404-ing the API. Asserted on `experiment-get`
    // since the cast helper is shared, so one tool's safety contract covers all.
    const schema = getToolSchema('experiment-get')
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

describe('experiment-list — query-param casts', () => {
    const schema = getToolSchema('experiment-list')

    it.each([
        ['limit', '50', 50],
        ['offset', '100', 100],
        ['feature_flag_id', '7', 7],
    ] as const)('casts stringified %s', (field, raw, expected) => {
        const parsed = parseWith(schema, { [field]: raw })
        expect(parsed[field]).toBe(expected)
        expect(typeof parsed[field]).toBe('number')
    })

    // `created_by_id` accepts a single user ID or a comma-separated / JSON-encoded
    // list, so it stays a string rather than casting to a number.
    it.each([
        ['single id', '42'],
        ['comma-separated list', '42,7'],
    ] as const)('passes through created_by_id as a string: %s', (_label, raw) => {
        const parsed = parseWith(schema, { created_by_id: raw })
        expect(parsed.created_by_id).toBe(raw)
        expect(typeof parsed.created_by_id).toBe('string')
    })
})
