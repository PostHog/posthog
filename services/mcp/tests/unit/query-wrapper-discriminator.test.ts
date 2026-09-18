import { describe, expect, it } from 'vitest'
import { z } from 'zod'

import { GENERATED_TOOL_MAP } from '@/tools/generated'
import type { ZodObjectAny } from '@/tools/types'

/**
 * The `kind` discriminator a query wrapper publishes must be the one its validator
 * accepts. `exec info`/`schema` and the advertised `tools/list` entry all render the
 * schema with `z.toJSONSchema(schema, { io: 'input' })`, while `exec call` validates
 * with `schema.safeParse`. When those disagree — a wrapper pointed at the wrong
 * `Assistant*Query`, or `query-llm-traces-list` and `query-llm-trace` swapped — an
 * agent reads one discriminator, sends it, and the call is rejected.
 */

/** The top-level `kind` const the input schema advertises, or undefined when `kind` is not a single literal. */
function advertisedKind(schema: ZodObjectAny): string | undefined {
    const json = z.toJSONSchema(schema, { io: 'input' }) as {
        properties?: Record<string, { const?: unknown }>
    }
    const kind = json.properties?.kind?.const
    return typeof kind === 'string' ? kind : undefined
}

/** Validation issues that specifically reject the top-level `kind` field; other missing fields are ignored. */
function kindIssues(schema: ZodObjectAny, value: string): z.core.$ZodIssue[] {
    const result = schema.safeParse({ kind: value })
    if (result.success) {
        return []
    }
    return result.error.issues.filter((issue) => issue.path.length === 1 && issue.path[0] === 'kind')
}

describe('query wrapper discriminator contract', () => {
    const wrappers = Object.entries(GENERATED_TOOL_MAP)
        .map(([name, make]) => {
            const schema = make().schema
            return { name, schema, kind: advertisedKind(schema) }
        })
        .filter((tool): tool is { name: string; schema: ZodObjectAny; kind: string } => tool.kind !== undefined)

    it('covers the query wrappers, including the LLM trace tools', () => {
        const names = wrappers.map((w) => w.name)
        expect(names).toContain('query-llm-traces-list')
        expect(names).toContain('query-llm-trace')
        expect(names).toContain('query-trends')
    })

    it.each(wrappers.map((w) => [w.name, w] as const))(
        '%s validator accepts the discriminator it advertises and rejects others',
        (_name, wrapper) => {
            expect(kindIssues(wrapper.schema, wrapper.kind)).toHaveLength(0)
            expect(kindIssues(wrapper.schema, `${wrapper.kind}_not_a_kind`).length).toBeGreaterThan(0)
        }
    )

    it('does not swap query-llm-traces-list and query-llm-trace', () => {
        const list = GENERATED_TOOL_MAP['query-llm-traces-list']!().schema
        const single = GENERATED_TOOL_MAP['query-llm-trace']!().schema

        expect(advertisedKind(list)).toBe('TracesQuery')
        expect(advertisedKind(single)).toBe('TraceQuery')

        // Each tool must reject the other's discriminator, so the published value is the real contract.
        expect(kindIssues(list, 'TraceQuery').length).toBeGreaterThan(0)
        expect(kindIssues(single, 'TracesQuery').length).toBeGreaterThan(0)
    })
})
