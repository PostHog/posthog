import { expectLogic } from 'kea-test-utils'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { tracingIngestionLogic } from './tracingIngestionLogic'

jest.mock('lib/utils/async', () => {
    const actual = jest.requireActual<typeof import('lib/utils/async')>('lib/utils/async')
    return {
        ...actual,
        // Run the real retry loop with no inter-attempt backoff. Otherwise the 1000ms + 1500ms
        // delays burn ~2.5s of real time per failing test and flake the 5s expectLogic timeout in CI.
        retryWithBackoff: (
            fn: Parameters<typeof actual.retryWithBackoff>[0],
            options: Parameters<typeof actual.retryWithBackoff>[1] = {}
        ) => actual.retryWithBackoff(fn, { ...options, initialDelayMs: 0 }),
    }
})

describe('tracingIngestionLogic', () => {
    afterEach(resumeKeaLoadersErrors)
    let logic: ReturnType<typeof tracingIngestionLogic.build>

    beforeEach(() => {
        localStorage.clear()
        initKeaTests()
    })

    afterEach(() => {
        logic?.unmount()
        localStorage.clear()
    })

    describe('loadTeamHasSpans', () => {
        it.each([
            { hasSpans: true, label: 'spans exist' },
            { hasSpans: false, label: 'no spans exist' },
        ])('loads teamHasSpans as $hasSpans when $label', async ({ hasSpans }) => {
            useMocks({
                get: {
                    '/api/environments/:team_id/tracing/spans/has_spans/': () => [200, { hasSpans }],
                },
            })

            logic = tracingIngestionLogic()
            logic.mount()

            await expectLogic(logic).toDispatchActions(['loadTeamHasSpans', 'loadTeamHasSpansSuccess']).toMatchValues({
                teamHasSpans: hasSpans,
                teamHasSpansLoading: false,
                teamHasSpansCheckFailed: false,
            })
        })

        it('handles API failure and sets teamHasSpansCheckFailed', async () => {
            silenceKeaLoadersErrors()
            useMocks({
                get: {
                    '/api/environments/:team_id/tracing/spans/has_spans/': () => [500, { detail: 'Server error' }],
                },
            })

            logic = tracingIngestionLogic()
            logic.mount()

            // With retry logic (3 attempts), this will eventually fail
            await expectLogic(logic).toDispatchActions(['loadTeamHasSpans', 'loadTeamHasSpansFailure']).toMatchValues({
                teamHasSpans: null, // kea-loaders sets to null on failure
                teamHasSpansLoading: false,
                teamHasSpansCheckFailed: true,
            })
        })

        it('starts with loading state on mount', async () => {
            useMocks({
                get: {
                    '/api/environments/:team_id/tracing/spans/has_spans/': () => [200, { hasSpans: true }],
                },
            })

            logic = tracingIngestionLogic()
            logic.mount()

            // Immediately after mount, the loader should be in loading state
            expect(logic.values.teamHasSpansLoading).toBe(true)

            await expectLogic(logic).toDispatchActions(['loadTeamHasSpansSuccess'])
        })

        it('resets teamHasSpansCheckFailed on new load attempt', async () => {
            silenceKeaLoadersErrors()
            let callCount = 0
            useMocks({
                get: {
                    '/api/environments/:team_id/tracing/spans/has_spans/': () => {
                        callCount++
                        if (callCount <= 3) {
                            return [500, { detail: 'Server error' }]
                        }
                        return [200, { hasSpans: true }]
                    },
                },
            })

            logic = tracingIngestionLogic()
            logic.mount()

            // First attempt fails after retries
            await expectLogic(logic).toDispatchActions(['loadTeamHasSpans', 'loadTeamHasSpansFailure']).toMatchValues({
                teamHasSpansCheckFailed: true,
            })

            // Manual retry succeeds
            logic.actions.loadTeamHasSpans()

            await expectLogic(logic).toDispatchActions(['loadTeamHasSpans', 'loadTeamHasSpansSuccess']).toMatchValues({
                teamHasSpans: true,
                teamHasSpansCheckFailed: false,
            })
        })
    })

    describe('caching', () => {
        it('skips API call when cachedTeamHasSpans is true', async () => {
            const mockFn = jest.fn(() => [200, { hasSpans: true }])
            useMocks({
                get: { '/api/environments/:team_id/tracing/spans/has_spans/': mockFn },
            })

            logic = tracingIngestionLogic()
            logic.mount()

            await expectLogic(logic).toDispatchActions(['loadTeamHasSpans', 'loadTeamHasSpansSuccess'])
            expect(mockFn).toHaveBeenCalledTimes(1)

            logic.unmount()

            // Mount again - should skip API call due to cache
            logic = tracingIngestionLogic()
            logic.mount()

            await expectLogic(logic).toNotHaveDispatchedActions(['loadTeamHasSpans'])
            expect(mockFn).toHaveBeenCalledTimes(1)
            expect(logic.values.hasSpans).toBe(true)
        })

        it('makes API call when cachedTeamHasSpans is null', async () => {
            const mockFn = jest.fn(() => [200, { hasSpans: false }])
            useMocks({
                get: { '/api/environments/:team_id/tracing/spans/has_spans/': mockFn },
            })

            logic = tracingIngestionLogic()
            logic.mount()

            await expectLogic(logic).toDispatchActions(['loadTeamHasSpans', 'loadTeamHasSpansSuccess'])
            expect(mockFn).toHaveBeenCalledTimes(1)

            logic.unmount()

            // Mount again - should make API call since false is not cached
            logic = tracingIngestionLogic()
            logic.mount()

            await expectLogic(logic).toDispatchActions(['loadTeamHasSpans', 'loadTeamHasSpansSuccess'])
            expect(mockFn).toHaveBeenCalledTimes(2)
        })

        it('hasSpans selector falls back to cachedTeamHasSpans when teamHasSpans is undefined', async () => {
            useMocks({
                get: { '/api/environments/:team_id/tracing/spans/has_spans/': () => [200, { hasSpans: true }] },
            })

            logic = tracingIngestionLogic()
            logic.mount()

            await expectLogic(logic).toDispatchActions(['loadTeamHasSpansSuccess'])
            expect(logic.values.cachedTeamHasSpans).toBe(true)

            logic.unmount()

            // Remount - teamHasSpans starts undefined, hasSpans should use cached
            logic = tracingIngestionLogic()
            logic.mount()

            expect(logic.values.teamHasSpans).toBeFalsy()
            expect(logic.values.hasSpans).toBe(true)
        })
    })
})
