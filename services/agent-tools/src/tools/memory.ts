/**
 * Persistent cross-agent memory tools. Thin wrappers over the agent-memory
 * engine (services/agent-shared/src/memory) — each resolves the session scope
 * { teamId, applicationId } from the ToolContext and delegates. The engine
 * enforces the per-pattern allowlist + team_id wall; these tools just surface
 * the capability into the agent loop. See docs/agent-platform/plans/agent-memory-mnemion-slice.md.
 */

import { defineNativeTool, Type, type ToolContext } from '@posthog/agent-shared'

import { getMemory } from '../memory-broker'

function scope(ctx: ToolContext): { teamId: number; applicationId: string } {
    return { teamId: ctx.teamId, applicationId: ctx.applicationId }
}

// Result envelope is informational (returns schemas aren't runtime-enforced);
// the engine returns { ok, error?, data? } and we pass it straight through so
// the model sees structured outcomes (including "no read access").
const RESULT = Type.Object({
    ok: Type.Boolean(),
    error: Type.Optional(Type.String()),
    data: Type.Optional(Type.Unknown()),
})

const FACETS = Type.Record(Type.String(), Type.String(), {
    description: 'Facet name → string value for this entry.',
})

export const memoryPrimeV1 = defineNativeTool({
    id: '@posthog/memory-prime',
    description:
        'Auto-associative recall. Describe the current focus in 1–3 natural sentences; get back the most relevant remembered entries (across the patterns this agent may read) plus their one-hop links. Descriptive language works better than keyword lists.',
    args: Type.Object({
        context: Type.String({ minLength: 1, description: 'The current conversational focus, 1–3 sentences.' }),
        patterns: Type.Optional(Type.Array(Type.String(), { description: 'Restrict recall to these patterns.' })),
        limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 20 })),
    }),
    returns: RESULT,
    cost_hint: 'cheap',
    async run(args, ctx) {
        return getMemory().prime(scope(ctx), args.context, { patterns: args.patterns, limit: args.limit })
    },
})

export const memoryDefinePatternV1 = defineNativeTool({
    id: '@posthog/memory-define-pattern',
    description:
        'Create a memory pattern (like a table) this agent can write to. The agent gets creator-only access by default; sharing with other agents is a separate, approval-gated step.',
    args: Type.Object({
        name: Type.String({ description: 'lowercase, starts with a letter; a-z 0-9 _ -' }),
        doctrine: Type.Optional(Type.String({ description: 'How this pattern should be used.' })),
        facets: Type.Array(Type.Object({ name: Type.String(), type: Type.Literal('text') }), {
            minItems: 1,
            description: 'The dimensions of an entry. Slice keeps facets text-typed.',
        }),
    }),
    returns: RESULT,
    cost_hint: 'cheap',
    async run(args, ctx) {
        return getMemory().createPattern(scope(ctx), { name: args.name, doctrine: args.doctrine, facets: args.facets })
    },
})

export const memoryRememberV1 = defineNativeTool({
    id: '@posthog/memory-remember',
    description: 'Record a new entry in a pattern this agent can write to.',
    args: Type.Object({
        pattern: Type.String(),
        facets: FACETS,
    }),
    returns: RESULT,
    cost_hint: 'cheap',
    async run(args, ctx) {
        return getMemory().create(scope(ctx), args.pattern, args.facets)
    },
})

export const memoryQueryV1 = defineNativeTool({
    id: '@posthog/memory-query',
    description: 'Filtered, sorted reads from a single pattern this agent may read.',
    args: Type.Object({
        pattern: Type.String(),
        filters: Type.Optional(
            Type.Array(
                Type.Object({
                    field: Type.String(),
                    op: Type.Union([
                        Type.Literal('='),
                        Type.Literal('!='),
                        Type.Literal('~'),
                        Type.Literal('>'),
                        Type.Literal('<'),
                    ]),
                    value: Type.String(),
                })
            )
        ),
        limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 1000 })),
    }),
    returns: RESULT,
    cost_hint: 'cheap',
    async run(args, ctx) {
        return getMemory().query(scope(ctx), args.pattern, args.filters ?? [], args.limit)
    },
})

export const memorySearchV1 = defineNativeTool({
    id: '@posthog/memory-search',
    description:
        "Substring search across all the patterns this agent may read. Use when you don't know which pattern holds the answer.",
    args: Type.Object({
        term: Type.String({ minLength: 1 }),
        limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 1000 })),
    }),
    returns: RESULT,
    cost_hint: 'cheap',
    async run(args, ctx) {
        return getMemory().search(scope(ctx), args.term, args.limit)
    },
})
