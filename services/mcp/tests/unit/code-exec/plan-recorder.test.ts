import { describe, expect, it } from 'vitest'

import {
    buildPlan,
    createClassifier,
    createPlanTransport,
    createSentinelFactory,
    isPlanRef,
    type NormalizedMutation,
    type PlanTransport,
    type RecordedMutation,
} from '@/lib/code-exec'

import { failingFetch, FIXTURE_TABLE, jsonInit, stubFetch } from './fixtures'

const HOST = 'https://us.posthog.com'

function makeRecorder(): PlanTransport {
    return createPlanTransport({
        realFetch: failingFetch,
        classifier: createClassifier(FIXTURE_TABLE),
        sentinels: createSentinelFactory('exec-1'),
    })
}

function normalizedFor(sequence: number, mutations: RecordedMutation[]): NormalizedMutation {
    return buildPlan(mutations, 'source').normalizedMutations.find((m) => m.sequence === sequence)!
}

describe('plan recorder', () => {
    it('passes reads through and records nothing (read-only sequence)', async () => {
        const passthrough = stubFetch({
            'GET /api/projects/2/feature_flags/': { body: { results: [{ id: 1 }] } },
            'POST /api/environments/2/query/': { body: { results: [[42]] } },
        })
        const recorder = createPlanTransport({
            realFetch: passthrough.fetch,
            classifier: createClassifier(FIXTURE_TABLE),
            sentinels: createSentinelFactory('exec-1'),
        })

        await recorder.fetch(`${HOST}/api/projects/2/feature_flags/`, jsonInit('GET'))
        await recorder.fetch(`${HOST}/api/environments/2/query/`, jsonInit('POST', { query: { kind: 'HogQLQuery' } }))

        expect(recorder.getMutations()).toHaveLength(0)
        // The query POST is a read, so it was forwarded, not synthesized.
        expect(passthrough.calls.map((c) => c.method)).toEqual(['GET', 'POST'])
    })

    it('never forwards a mutation and answers it synthetically with a 201 and a sentinel id', async () => {
        const recorder = makeRecorder()
        const response = await recorder.fetch(
            `${HOST}/api/projects/2/feature_flags/`,
            jsonInit('POST', { key: 'checkout-v2' })
        )
        expect(response.status).toBe(201)
        const bodyJson = (await response.json()) as { key: string; id: number }
        // Echoes the request body and adds a schema-correct numeric sentinel.
        expect(bodyJson.key).toBe('checkout-v2')
        expect(bodyJson.id).toBe(-900001)

        const mutations = recorder.getMutations()
        expect(mutations).toHaveLength(1)
        expect(mutations[0]).toMatchObject({
            sequence: 0,
            operationId: 'featureFlags.create',
            method: 'POST',
            objectType: 'feature flag',
            sentinels: [{ field: 'id', value: -900001 }],
        })
    })

    it('issues a string sentinel for a string-typed id field', async () => {
        const recorder = makeRecorder()
        const response = await recorder.fetch(`${HOST}/api/projects/2/surveys/`, jsonInit('POST', { name: 'nps' }))
        const bodyJson = (await response.json()) as { id: string }
        expect(bodyJson.id).toBe('__ph_plan_0_id__')
    })

    it('records the created-id binding when it reappears in a later path and body string', async () => {
        const recorder = makeRecorder()
        await recorder.fetch(`${HOST}/api/projects/2/feature_flags/`, jsonInit('POST', { key: 'checkout-v2' }))
        // The created id (-900001) reappears in the URL path, as an exact numeric
        // body field, and embedded inside a longer body string.
        await recorder.fetch(
            `${HOST}/api/projects/2/feature_flags/-900001/`,
            jsonInit('PATCH', { linked_flag: -900001, note: 'flag -900001 bumped' })
        )

        const mutations = recorder.getMutations()
        const normalized = normalizedFor(1, mutations)
        // Path segment became a $planRef marker (path no longer contains the literal).
        expect(normalized.path).not.toContain('-900001')
        const body = normalized.body as { linked_flag: unknown; note: string }
        // Exact numeric match → structured $planRef object.
        expect(isPlanRef(body.linked_flag)).toBe(true)
        // Embedded in a string → textual marker, literal gone.
        expect(body.note).not.toContain('-900001')
    })

    it.each([
        {
            name: 'update PATCH is a mutation, not a soft delete',
            body: { rollout_percentage: 25 },
            expectedSoftDelete: false,
        },
        {
            name: 'PATCH with deleted:true is a soft delete',
            body: { deleted: true },
            expectedSoftDelete: true,
        },
    ])('classifies $name', async ({ body, expectedSoftDelete }) => {
        const recorder = makeRecorder()
        const response = await recorder.fetch(`${HOST}/api/projects/2/feature_flags/5/`, jsonInit('PATCH', body))
        const mutations = recorder.getMutations()
        expect(mutations[0]!.softDelete).toBe(expectedSoftDelete)
        if (expectedSoftDelete) {
            const json = (await response.json()) as { deleted: boolean }
            expect(json.deleted).toBe(true)
        }
    })

    it('fails closed: an unclassified POST is a mutation with a null operationId', async () => {
        const recorder = makeRecorder()
        await recorder.fetch(`${HOST}/api/projects/2/unknown_resource/`, jsonInit('POST', { foo: 'bar' }))
        const mutations = recorder.getMutations()
        expect(mutations).toHaveLength(1)
        expect(mutations[0]).toMatchObject({ operationId: null, objectType: null, method: 'POST' })
        // A default numeric id sentinel is still issued so create chains keep working.
        expect(mutations[0]!.sentinels).toEqual([{ field: 'id', value: -900001 }])
    })
})
