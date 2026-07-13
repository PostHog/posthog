import { describe, expect, it } from 'vitest'

import {
    buildPlan,
    createClassifier,
    createPlanTransport,
    createSentinelFactory,
    type MutationOutcome,
    type Plan,
    renderPlanText,
    renderReceiptText,
} from '@/lib/code-exec'

import { failingFetch, FIXTURE_TABLE, jsonInit } from './fixtures'

const HOST = 'https://us.posthog.com'

async function planWithDeleteCreateUpdate(): Promise<Plan> {
    const recorder = createPlanTransport({
        realFetch: failingFetch,
        classifier: createClassifier(FIXTURE_TABLE),
        sentinels: createSentinelFactory('exec-1'),
    })
    await recorder.fetch(`${HOST}/api/projects/2/feature_flags/9/`, jsonInit('PATCH', { key: 'legacy', deleted: true }))
    await recorder.fetch(`${HOST}/api/projects/2/feature_flags/`, jsonInit('POST', { key: 'checkout-v2' }))
    await recorder.fetch(`${HOST}/api/projects/2/feature_flags/5/`, jsonInit('PATCH', { rollout_percentage: 25 }))
    return buildPlan(recorder.getMutations(), 'source')
}

describe('plan rendering', () => {
    it('renders a soft delete as a delete, first and loud', async () => {
        const text = renderPlanText(await planWithDeleteCreateUpdate())
        const lines = text.split('\n').filter((l) => /^(DELETE|CREATE|UPDATE) /.test(l))
        // Deletes render before creates and updates.
        expect(lines[0]).toBe('DELETE feature flag "legacy"')
        expect(lines).toContain('CREATE new feature flag #1')
        expect(lines.some((l) => l.startsWith('UPDATE feature flag'))).toBe(true)
    })

    it('shows field-level diffs when a current object snapshot is supplied', async () => {
        const plan = await planWithDeleteCreateUpdate()
        const text = renderPlanText(plan, { 2: { rollout_percentage: 10 } })
        expect(text).toContain('rollout_percentage: 10 → 25')
    })

    it('renders receipt outcomes including skipped entries', () => {
        const outcomes: MutationOutcome[] = [
            {
                sequence: 0,
                operationId: 'x',
                method: 'POST',
                path: '/api/projects/2/feature_flags/',
                status: 'applied',
            },
            {
                sequence: 1,
                operationId: 'y',
                method: 'PATCH',
                path: '/api/projects/2/feature_flags/5/',
                status: 'skipped',
            },
        ]
        const text = renderReceiptText(outcomes)
        expect(text).toContain('[applied] POST /api/projects/2/feature_flags/')
        expect(text).toContain('[skipped] PATCH /api/projects/2/feature_flags/5/')
    })
})
