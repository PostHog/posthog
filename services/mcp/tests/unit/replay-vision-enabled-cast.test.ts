/**
 * Regression test for the boolean→string cast on `vision-scanners-list`.
 *
 * A filter named `enabled` reads as a boolean to an agent, so production
 * traces show `enabled: true` on almost every scout run, which the MCP
 * layer rejected with `parameter "enabled" must be of type string`. The
 * backend filter already accepts `true` / `false`, so the fix is the
 * declarative `param_overrides: { enabled: { cast: 'boolean-string' } }`
 * in `products/replay_vision/mcp/tools.yaml`.
 */
import { describe, expect, it } from 'vitest'
import type { z } from 'zod'

import { GENERATED_TOOLS } from '@/tools/generated/replay_vision'
import type { ToolBase, ZodObjectAny } from '@/tools/types'

describe('vision-scanners-list enabled filter', () => {
    const schema = (GENERATED_TOOLS['vision-scanners-list'] as () => ToolBase<ZodObjectAny>)().schema as z.ZodTypeAny
    const parse = (input: unknown): Record<string, unknown> => schema.parse(input) as Record<string, unknown>

    it.each([
        [true, 'true'],
        [false, 'false'],
    ] as const)('casts the boolean %s the backend accepts as a string', (input, expected) => {
        expect(parse({ enabled: input }).enabled).toBe(expected)
    })

    // z.preprocess() does not carry the inner .optional() into the advertised schema,
    // so the codegen re-applies it. A filter that became required would break every caller.
    it('stays optional', () => {
        expect(parse({}).enabled).toBeUndefined()
    })
})
