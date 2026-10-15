import { describe, expect, it } from 'vitest'
import { z } from 'zod'

import { ExperimentResultsGetSchema } from '@/schema/tool-inputs'
import { GENERATED_TOOLS as EXPERIMENT_TOOLS } from '@/tools/generated/experiments'
import { GENERATED_TOOLS as FEATURE_FLAG_TOOLS } from '@/tools/generated/feature_flags'

import { EXPERIMENT_ID_TOOLS } from '../fixtures/experiment-id-tools'

// Production traces show the dominant validation failure on the experiment tools is the
// experiment id arriving as `experimentId` / `experiment_id` where the schema requires
// `id` (the same mismatch the insight and flag tools already absorb). Every alias must
// normalize to `id` on every tool that takes an experiment id, or those failures come back.
/** Tool names whose advertised input schema has a top-level `id` property. */
function toolsWithIdParam(tools: Record<string, () => { schema: z.ZodTypeAny }>): string[] {
    return Object.entries(tools)
        .filter(([, factory]) => {
            const json = z.toJSONSchema(factory().schema, { io: 'input', reused: 'inline' }) as {
                properties?: Record<string, unknown>
            }
            return Boolean(json.properties?.id)
        })
        .map(([name]) => name)
        .sort()
}

describe('experiment id aliases', () => {
    const ALIAS_KEYS = ['experimentId', 'experiment_id'] as const

    // `id` on these is a holdout or saved-metric id, not an experiment id.
    const NON_EXPERIMENT_ID_TOOLS = new Set([
        'experiment-holdouts-retrieve',
        'experiment-holdouts-partial-update',
        'experiment-holdouts-destroy',
        'experiment-saved-metrics-retrieve',
        'experiment-saved-metrics-partial-update',
        'experiment-saved-metrics-destroy',
    ])

    // The alias list is hand-maintained; this keeps it in step with the generated tools so
    // a new id-taking experiment tool cannot ship without the aliases.
    it('covers every generated experiment tool that takes an experiment id', () => {
        const idTools = toolsWithIdParam(EXPERIMENT_TOOLS).filter((name) => !NON_EXPERIMENT_ID_TOOLS.has(name))
        expect(idTools).toEqual(EXPERIMENT_ID_TOOLS.map(([name]) => name).sort())
    })

    describe.each(EXPERIMENT_ID_TOOLS)('%s normalizes aliases to `id`', (toolName, extras) => {
        const factory = EXPERIMENT_TOOLS[toolName]

        it('is a generated tool', () => {
            expect(factory).not.toBeUndefined()
        })

        it.each([
            ['id (numeric)', { id: 123 }, 123],
            ['id (numeric string)', { id: '123' }, 123],
            ['experimentId', { experimentId: 123 }, 123],
            ['experiment_id', { experiment_id: 123 }, 123],
            ['experiment_id (numeric string)', { experiment_id: '123' }, 123],
            ['id over aliases on conflict', { id: 1, experimentId: 2, experiment_id: 3 }, 1],
            ['first-listed alias on alias conflict', { experimentId: 2, experiment_id: 3 }, 2],
        ])('accepts %s', (_label, input, expected) => {
            const schema = factory!().schema
            const result = schema.safeParse({ ...extras, ...input })
            expect(result.success, JSON.stringify(result.error?.issues)).toBe(true)
            const data = result.data as Record<string, unknown>
            expect(data.id).toEqual(expected)
            for (const alias of ALIAS_KEYS) {
                expect(data).not.toHaveProperty(alias)
            }
        })

        it('still rejects a call with no identifier', () => {
            expect(factory!().schema.safeParse({ ...extras }).success).toBe(false)
        })
    })

    describe('experiment-metrics-recalculation-retrieve normalizes run id aliases to `recalculation_id`', () => {
        const schema = EXPERIMENT_TOOLS['experiment-metrics-recalculation-retrieve']!().schema
        const runId = '0199a1c0-0000-7000-8000-000000000000'

        it.each([
            ['recalculation_id', { id: 1, recalculation_id: runId }],
            ['run_id', { id: 1, run_id: runId }],
            ['runId', { id: 1, runId: runId }],
            ['recalculationId', { experimentId: 1, recalculationId: runId }],
            ['recalculation_id over aliases on conflict', { id: 1, recalculation_id: runId, run_id: 'stale' }],
        ])('accepts %s', (_label, input) => {
            const result = schema.safeParse(input)
            expect(result.success, JSON.stringify(result.error?.issues)).toBe(true)
            const data = result.data as Record<string, unknown>
            expect(data.id).toBe(1)
            expect(data.recalculation_id).toBe(runId)
            for (const alias of ['run_id', 'runId', 'recalculationId']) {
                expect(data).not.toHaveProperty(alias)
            }
        })

        it('still rejects a call with no run id', () => {
            expect(schema.safeParse({ id: 1 }).success).toBe(false)
        })
    })

    describe('experiment-results-get (hand-written) normalizes aliases to `id`', () => {
        it.each([
            ['id (numeric)', { id: 123 }, 123],
            ['id (numeric string)', { id: '123' }, 123],
            ['experimentId', { experimentId: 123 }, 123],
            ['experiment_id', { experiment_id: '123' }, 123],
            ['id over aliases on conflict', { id: 1, experimentId: 2 }, 1],
        ])('accepts %s', (_label, input, expected) => {
            const result = ExperimentResultsGetSchema.safeParse(input)
            expect(result.success, JSON.stringify(result.error?.issues)).toBe(true)
            expect(result.data?.id).toBe(expected)
            expect(result.data?.refresh).toBe(false)
            for (const alias of ALIAS_KEYS) {
                expect(result.data).not.toHaveProperty(alias)
            }
        })

        it('still rejects a call with no identifier', () => {
            expect(ExperimentResultsGetSchema.safeParse({}).success).toBe(false)
        })
    })
})

// The flag tools only gained aliases on the by-key lookup; the id-based tools kept failing on
// `flagId` / `flag_id` at the same rate, so they take the numeric-id aliases too.
describe('feature flag id aliases', () => {
    const FLAG_ID_TOOLS = [
        'delete-feature-flag',
        'feature-flag-archive',
        'feature-flag-disable',
        'feature-flag-enable',
        'feature-flag-get-definition',
        'feature-flag-roll-out-to-everyone',
        'feature-flag-set-release-condition-rollout',
        'feature-flag-unarchive',
        'feature-flags-activity-retrieve',
        'feature-flags-dependent-flags-retrieve',
        'feature-flags-status-retrieve',
        'feature-flags-test-evaluation-create',
        'update-feature-flag',
    ] as const

    const ALIAS_KEYS = ['flagId', 'flag_id', 'feature_flag_id', 'featureFlagId'] as const

    const REQUIRED_EXTRAS: Record<string, Record<string, unknown>> = {
        'feature-flags-test-evaluation-create': { distinct_id: 'user-1' },
        'feature-flag-roll-out-to-everyone': { version: 3 },
        'feature-flag-set-release-condition-rollout': { condition_index: 0, rollout_percentage: 25, version: 3 },
    }

    // `id` on these is a scheduled change id, not a flag id.
    const NON_FLAG_ID_TOOLS = new Set(['scheduled-changes-delete', 'scheduled-changes-get', 'scheduled-changes-update'])

    it('covers every generated flag tool that takes a flag id', () => {
        const idTools = toolsWithIdParam(FEATURE_FLAG_TOOLS).filter((name) => !NON_FLAG_ID_TOOLS.has(name))
        expect(idTools).toEqual([...FLAG_ID_TOOLS].sort())
    })

    describe.each(FLAG_ID_TOOLS.map((name) => [name]))('%s normalizes aliases to `id`', (toolName) => {
        const factory = FEATURE_FLAG_TOOLS[toolName]
        const extras = REQUIRED_EXTRAS[toolName] ?? {}

        it.each([
            ['id (numeric)', { id: 7 }, 7],
            ['flagId', { flagId: 7 }, 7],
            ['flag_id', { flag_id: '7' }, 7],
            ['feature_flag_id', { feature_flag_id: 7 }, 7],
            ['featureFlagId', { featureFlagId: 7 }, 7],
            ['id over aliases on conflict', { id: 1, flagId: 2 }, 1],
        ])('accepts %s', (_label, input, expected) => {
            const result = factory!().schema.safeParse({ ...extras, ...input })
            expect(result.success, JSON.stringify(result.error?.issues)).toBe(true)
            const data = result.data as Record<string, unknown>
            expect(data.id).toEqual(expected)
            for (const alias of ALIAS_KEYS) {
                expect(data).not.toHaveProperty(alias)
            }
        })

        it('still rejects a call with no identifier', () => {
            expect(factory!().schema.safeParse({ ...extras }).success).toBe(false)
        })
    })
})
