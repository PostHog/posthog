import { describe, expect, it } from 'vitest'

import { buildPlan, computeScriptHash, type RecordedMutation, stableStringify } from '@/lib/code-exec'

function mutation(body: unknown): RecordedMutation {
    return {
        sequence: 0,
        operationId: 'featureFlags.update',
        method: 'PATCH',
        path: '/api/projects/2/feature_flags/5/',
        body,
        softDelete: false,
        destructive: false,
        objectType: 'feature flag',
        sentinels: [],
    }
}

describe('plan hashing', () => {
    it('is stable across object key order', () => {
        // The plan hash must bind the confirmed content, not its serialization —
        // reordering keys in a body must not invalidate a confirmed plan.
        const a = buildPlan([mutation({ rollout: 25, key: 'checkout-v2', filters: { active: true, groups: [] } })], 's')
        const b = buildPlan([mutation({ filters: { groups: [], active: true }, key: 'checkout-v2', rollout: 25 })], 's')
        expect(a.planHash).toBe(b.planHash)
    })

    it('changes when a mutated value changes', () => {
        const a = buildPlan([mutation({ rollout: 25 })], 's')
        const b = buildPlan([mutation({ rollout: 50 })], 's')
        expect(a.planHash).not.toBe(b.planHash)
    })

    it('distinguishes string from numeric values (no type coercion in the pre-image)', () => {
        expect(stableStringify({ x: 5 })).not.toBe(stableStringify({ x: '5' }))
    })

    it('hashes the exact script source', () => {
        expect(computeScriptHash('a')).toBe(computeScriptHash('a'))
        expect(computeScriptHash('a')).not.toBe(computeScriptHash('a '))
    })
})
