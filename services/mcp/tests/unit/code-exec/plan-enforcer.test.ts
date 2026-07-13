import { describe, expect, it } from 'vitest'

import {
    buildPlan,
    type Classifier,
    createClassifier,
    createEnforceTransport,
    createPlanTransport,
    createSentinelFactory,
    type Plan,
    PlanDivergenceError,
} from '@/lib/code-exec'

import { failingFetch, FIXTURE_TABLE, jsonInit, stubFetch } from './fixtures'

const HOST = 'https://us.posthog.com'
const classifier = (): Classifier => createClassifier(FIXTURE_TABLE)

/** Record a create-then-use plan: create a flag, then PATCH it referencing the created id. */
async function recordCreateThenUsePlan(): Promise<Plan> {
    const recorder = createPlanTransport({
        realFetch: failingFetch,
        classifier: classifier(),
        sentinels: createSentinelFactory('exec-1'),
    })
    await recorder.fetch(`${HOST}/api/projects/2/feature_flags/`, jsonInit('POST', { key: 'checkout-v2' }))
    await recorder.fetch(
        `${HOST}/api/projects/2/feature_flags/-900001/`,
        jsonInit('PATCH', { linked_flag: -900001, note: 'flag -900001 bumped' })
    )
    return buildPlan(recorder.getMutations(), 'source')
}

describe('plan enforcer', () => {
    it('binds the real created id into the later path and body at apply time', async () => {
        const plan = await recordCreateThenUsePlan()
        // The real create returns id 42; the enforcer must substitute 42 for the
        // sentinel everywhere it was recorded, and the PATCH must then match.
        const real = stubFetch({
            'POST /api/projects/2/feature_flags/': { status: 201, body: { id: 42, key: 'checkout-v2' } },
            'PATCH /api/projects/2/feature_flags/42/': { body: { id: 42 } },
        })
        const enforcer = createEnforceTransport({ realFetch: real.fetch, plan, classifier: classifier() })

        await enforcer.fetch(`${HOST}/api/projects/2/feature_flags/`, jsonInit('POST', { key: 'checkout-v2' }))
        await enforcer.fetch(
            `${HOST}/api/projects/2/feature_flags/42/`,
            jsonInit('PATCH', { linked_flag: 42, note: 'flag 42 bumped' })
        )

        // Both mutations were forwarded for real, in order.
        expect(real.calls.map((c) => c.method)).toEqual(['POST', 'PATCH'])
        const receipt = enforcer.getReceipt()
        expect(receipt.map((o) => o.status)).toEqual(['applied', 'applied'])
    })

    it('reads pass through in enforce mode without consuming plan entries', async () => {
        const plan = await recordCreateThenUsePlan()
        const real = stubFetch({
            'GET /api/projects/2/feature_flags/': { body: { results: [] } },
            'POST /api/projects/2/feature_flags/': { status: 201, body: { id: 42 } },
            'PATCH /api/projects/2/feature_flags/42/': { body: { id: 42 } },
        })
        const enforcer = createEnforceTransport({ realFetch: real.fetch, plan, classifier: classifier() })

        await enforcer.fetch(`${HOST}/api/projects/2/feature_flags/`, jsonInit('GET'))
        await enforcer.fetch(`${HOST}/api/projects/2/feature_flags/`, jsonInit('POST', { key: 'checkout-v2' }))

        expect(enforcer.getReceipt().map((o) => o.status)).toEqual(['applied', 'skipped'])
    })

    it('aborts on divergence, poisons the transport, and marks remaining entries skipped', async () => {
        const plan = await recordCreateThenUsePlan()
        const real = stubFetch({
            'POST /api/projects/2/feature_flags/': { status: 201, body: { id: 42 } },
            'DELETE /api/projects/2/feature_flags/42/': { body: {} },
            'GET /api/projects/2/feature_flags/': { body: { results: [] } },
        })
        const enforcer = createEnforceTransport({ realFetch: real.fetch, plan, classifier: classifier() })

        await enforcer.fetch(`${HOST}/api/projects/2/feature_flags/`, jsonInit('POST', { key: 'checkout-v2' }))

        // A DELETE was never planned (the plan had a PATCH) → divergence.
        await expect(
            enforcer.fetch(`${HOST}/api/projects/2/feature_flags/42/`, jsonInit('DELETE'))
        ).rejects.toBeInstanceOf(PlanDivergenceError)

        // The transport is poisoned: every later call fails fast, even a read.
        await expect(enforcer.fetch(`${HOST}/api/projects/2/feature_flags/`, jsonInit('GET'))).rejects.toBeInstanceOf(
            PlanDivergenceError
        )

        const receipt = enforcer.getReceipt()
        expect(receipt[0]!.status).toBe('applied')
        // The unconsumed PATCH entry is reported as skipped.
        expect(receipt[1]!.status).toBe('skipped')
    })

    it('the divergence error carries the attempted call and the closest unconsumed entry', async () => {
        const plan = await recordCreateThenUsePlan()
        const real = stubFetch({
            'POST /api/projects/2/feature_flags/': { status: 201, body: { id: 42 } },
        })
        const enforcer = createEnforceTransport({ realFetch: real.fetch, plan, classifier: classifier() })
        await enforcer.fetch(`${HOST}/api/projects/2/feature_flags/`, jsonInit('POST', { key: 'checkout-v2' }))

        const error = await enforcer
            .fetch(`${HOST}/api/projects/2/feature_flags/42/`, jsonInit('DELETE'))
            .then(() => null)
            .catch((e: unknown) => e)

        expect(error).toBeInstanceOf(PlanDivergenceError)
        const divergence = error as PlanDivergenceError
        expect(divergence.attempted).toMatchObject({ method: 'DELETE', path: '/api/projects/2/feature_flags/42/' })
        expect(divergence.closestPlanEntry?.sequence).toBe(1)
    })
})
