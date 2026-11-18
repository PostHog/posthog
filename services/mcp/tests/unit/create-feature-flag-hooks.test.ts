import { afterEach, describe, expect, it, vi } from 'vitest'

import createFeatureFlagHooks, {
    AUTO_RELEASE_NOTE,
    RELEASE_SUGGESTIONS_NOTE,
    RELEASE_SUGGESTIONS_TIMEOUT_MS,
} from '@/tools/featureFlags/createFeatureFlagHooks'
import type { Context } from '@/tools/types'

const FLAG = { id: 42, key: 'checkout-redesign', filters: { groups: [{ properties: [], rollout_percentage: 100 }] } }
const SUGGESTION = { id: 'release-1', name: 'Checkout redesign', matched_terms: ['checkout', 'redesign'] }

function contextWith(request: (opts: { signal?: AbortSignal }) => Promise<unknown>): {
    context: Context
    request: ReturnType<typeof vi.fn>
} {
    const requestMock = vi.fn(request)
    const context = {
        stateManager: { getProjectId: async () => '7' },
        api: { request: requestMock },
    } as unknown as Context
    return { context, request: requestMock }
}

describe('createFeatureFlagHooks.afterResponse', () => {
    afterEach(() => {
        vi.useRealTimers()
    })

    it.each([
        { autoRelease: false, note: RELEASE_SUGGESTIONS_NOTE },
        { autoRelease: true, note: RELEASE_SUGGESTIONS_NOTE + AUTO_RELEASE_NOTE },
    ])(
        'adds related releases and the instruction to ask the user, auto release $autoRelease',
        async ({ autoRelease, note }) => {
            const { context, request } = contextWith(async () => ({
                feature_flag_id: 42,
                auto_release: autoRelease,
                current: [],
                suggestions: [SUGGESTION],
            }))

            const result = (await createFeatureFlagHooks.afterResponse(context, {}, FLAG)) as Record<string, unknown>

            expect(request).toHaveBeenCalledWith({
                method: 'GET',
                path: '/api/projects/7/releases/flag_suggestions/',
                query: { feature_flag_id: 42 },
                signal: expect.any(AbortSignal),
            })
            expect(result.release_suggestions).toEqual([SUGGESTION])
            expect(result.release_suggestions_note).toBe(note)
            expect((result.filters as { groups: Record<string, unknown>[] }).groups[0]?.condition_id).toBeTruthy()
        }
    )

    it.each([
        {
            name: 'nothing matches',
            request: async () => ({ feature_flag_id: 42, auto_release: true, current: [], suggestions: [] }),
        },
        {
            name: 'the flag is already in a release',
            request: async () => ({
                feature_flag_id: 42,
                auto_release: true,
                current: [{ id: 'release-2', name: 'Checkout' }],
                suggestions: [SUGGESTION],
            }),
        },
        {
            name: 'releases are off for the project',
            request: async () => {
                throw new Error('Releases are not enabled for this project.')
            },
        },
    ])('adds nothing when $name', async ({ request }) => {
        const { context } = contextWith(request)

        const result = (await createFeatureFlagHooks.afterResponse(context, {}, FLAG)) as Record<string, unknown>

        expect(result).not.toHaveProperty('release_suggestions')
        expect(result.key).toBe(FLAG.key)
    })

    it('cancels the lookup and adds nothing when it outlasts the timeout', async () => {
        vi.useFakeTimers()
        let aborted = false
        const { context } = contextWith(
            ({ signal }) =>
                new Promise((_resolve, reject) =>
                    signal?.addEventListener('abort', () => {
                        aborted = true
                        reject(new Error('aborted'))
                    })
                )
        )

        const pending = createFeatureFlagHooks.afterResponse(context, {}, FLAG)
        await vi.advanceTimersByTimeAsync(RELEASE_SUGGESTIONS_TIMEOUT_MS)

        await expect(pending).resolves.not.toHaveProperty('release_suggestions')
        expect(aborted).toBe(true)
    })
})
