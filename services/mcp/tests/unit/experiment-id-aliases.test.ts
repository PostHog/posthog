import { describe, expect, it } from 'vitest'

import { ExperimentResultsGetSchema } from '@/schema/tool-inputs'
import { GENERATED_TOOLS as EXPERIMENT_TOOLS } from '@/tools/generated/experiments'
import { GENERATED_TOOLS as FEATURE_FLAG_TOOLS } from '@/tools/generated/feature_flags'

// Production traces show the dominant validation failure on the experiment tools is the
// experiment id arriving as `experimentId` / `experiment_id` where the schema requires
// `id` (the same mismatch the insight and flag tools already absorb). Every alias must
// normalize to `id` on every tool that takes an experiment id, or those failures come back.
describe('experiment id aliases', () => {
    const EXPERIMENT_ID_TOOLS = [
        'experiment-activity',
        'experiment-archive',
        'experiment-cleanup-task',
        'experiment-copy-to-project',
        'experiment-delete',
        'experiment-duplicate',
        'experiment-end',
        'experiment-freeze-exposure',
        'experiment-get',
        'experiment-launch',
        'experiment-metrics-recalculation-create',
        'experiment-metrics-recalculation-latest-retrieve',
        'experiment-metrics-recalculation-retrieve',
        'experiment-pause',
        'experiment-reset',
        'experiment-resume',
        'experiment-ship-variant',
        'experiment-timeseries-results',
        'experiment-unarchive',
        'experiment-unfreeze-exposure',
        'experiment-update',
        'experiments-session-event-deltas-create',
    ] as const

    const ALIAS_KEYS = ['experimentId', 'experiment_id'] as const

    // Only the id is under test: the other required params of each tool are filled with
    // stand-in values so the parse exercises the alias rewrite rather than their validation.
    const REQUIRED_EXTRAS: Record<string, Record<string, unknown>> = {
        'experiment-copy-to-project': { target_team_id: 2 },
        'experiment-duplicate': { name: 'copy', feature_flag_key: 'copy-flag' },
        'experiment-metrics-recalculation-retrieve': { recalculation_id: '0199a1c0-0000-7000-8000-000000000000' },
        'experiment-ship-variant': { variant_key: 'test' },
        'experiment-timeseries-results': { fingerprint: 'abc', metric_uuid: '0199a1c0-0000-7000-8000-000000000001' },
    }

    describe.each(EXPERIMENT_ID_TOOLS.map((name) => [name]))('%s normalizes aliases to `id`', (toolName) => {
        const factory = EXPERIMENT_TOOLS[toolName]
        const extras = REQUIRED_EXTRAS[toolName] ?? {}

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
    }

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
