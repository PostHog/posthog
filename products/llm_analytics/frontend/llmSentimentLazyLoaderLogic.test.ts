import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'

import { initKeaTests } from '~/test/init'

import { SentimentResult, llmSentimentLazyLoaderLogic } from './llmSentimentLazyLoaderLogic'

describe('llmSentimentLazyLoaderLogic', () => {
    let logic: ReturnType<typeof llmSentimentLazyLoaderLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = llmSentimentLazyLoaderLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    describe('initial state', () => {
        it('should have empty sentiment cache', () => {
            expect(logic.values.sentimentByTraceId).toEqual({})
        })

        it('should have empty loading set', () => {
            expect(logic.values.loadingTraceIds).toEqual(new Set())
        })
    })

    describe('ensureSentimentLoaded action', () => {
        it('should add trace ID to loading set', async () => {
            await expectLogic(logic, () => {
                logic.actions.ensureSentimentLoaded('trace-1')
            }).toMatchValues({
                loadingTraceIds: new Set(['trace-1']),
            })
        })

        it('should handle multiple trace IDs', async () => {
            logic.actions.ensureSentimentLoaded('trace-1')
            logic.actions.ensureSentimentLoaded('trace-2')
            logic.actions.ensureSentimentLoaded('trace-3')

            expect(logic.values.loadingTraceIds).toEqual(new Set(['trace-1', 'trace-2', 'trace-3']))
        })

        it('should not add duplicate trace IDs to loading set', async () => {
            logic.actions.ensureSentimentLoaded('trace-1')
            logic.actions.ensureSentimentLoaded('trace-1')
            logic.actions.ensureSentimentLoaded('trace-1')

            expect(logic.values.loadingTraceIds).toEqual(new Set(['trace-1']))
        })
    })

    describe('loadSentimentBatchSuccess action', () => {
        it('should store sentiment results', async () => {
            const mockResult: SentimentResult = {
                label: 'positive',
                score: 0.95,
                scores: { positive: 0.95, negative: 0.03, neutral: 0.02 },
                messages: {},
                message_count: 2,
            }

            await expectLogic(logic, () => {
                logic.actions.loadSentimentBatchSuccess({ 'trace-1': mockResult }, ['trace-1'])
            }).toMatchValues({
                sentimentByTraceId: {
                    'trace-1': mockResult,
                },
            })
        })

        it('should remove trace IDs from loading set', async () => {
            logic.actions.ensureSentimentLoaded('trace-1')
            logic.actions.ensureSentimentLoaded('trace-2')

            const mockResult: SentimentResult = {
                label: 'positive',
                score: 0.8,
                scores: { positive: 0.8, negative: 0.1, neutral: 0.1 },
                messages: {},
                message_count: 1,
            }

            await expectLogic(logic, () => {
                logic.actions.loadSentimentBatchSuccess({ 'trace-1': mockResult }, ['trace-1'])
            }).toMatchValues({
                loadingTraceIds: new Set(['trace-2']),
            })
        })

        it('should store null for traces without results', async () => {
            await expectLogic(logic, () => {
                logic.actions.loadSentimentBatchSuccess({}, ['trace-1', 'trace-2'])
            }).toMatchValues({
                sentimentByTraceId: {
                    'trace-1': null,
                    'trace-2': null,
                },
            })
        })

        it('should handle multiple results in batch', async () => {
            const result1: SentimentResult = {
                label: 'positive',
                score: 0.9,
                scores: { positive: 0.9, negative: 0.05, neutral: 0.05 },
                messages: {},
                message_count: 1,
            }

            const result2: SentimentResult = {
                label: 'negative',
                score: 0.85,
                scores: { positive: 0.1, negative: 0.85, neutral: 0.05 },
                messages: {},
                message_count: 3,
            }

            await expectLogic(logic, () => {
                logic.actions.loadSentimentBatchSuccess({ 'trace-1': result1, 'trace-2': result2 }, [
                    'trace-1',
                    'trace-2',
                ])
            }).toMatchValues({
                sentimentByTraceId: {
                    'trace-1': result1,
                    'trace-2': result2,
                },
            })
        })

        it('should preserve existing results when adding new ones', async () => {
            const result1: SentimentResult = {
                label: 'positive',
                score: 0.9,
                scores: { positive: 0.9, negative: 0.05, neutral: 0.05 },
                messages: {},
                message_count: 1,
            }

            const result2: SentimentResult = {
                label: 'negative',
                score: 0.8,
                scores: { positive: 0.1, negative: 0.8, neutral: 0.1 },
                messages: {},
                message_count: 1,
            }

            logic.actions.loadSentimentBatchSuccess({ 'trace-1': result1 }, ['trace-1'])
            logic.actions.loadSentimentBatchSuccess({ 'trace-2': result2 }, ['trace-2'])

            expect(logic.values.sentimentByTraceId).toEqual({
                'trace-1': result1,
                'trace-2': result2,
            })
        })
    })

    describe('loadSentimentBatchFailure action', () => {
        it('should set null for failed traces', async () => {
            await expectLogic(logic, () => {
                logic.actions.loadSentimentBatchFailure(['trace-1', 'trace-2'])
            }).toMatchValues({
                sentimentByTraceId: {
                    'trace-1': null,
                    'trace-2': null,
                },
            })
        })

        it('should remove trace IDs from loading set', async () => {
            logic.actions.ensureSentimentLoaded('trace-1')
            logic.actions.ensureSentimentLoaded('trace-2')
            logic.actions.ensureSentimentLoaded('trace-3')

            await expectLogic(logic, () => {
                logic.actions.loadSentimentBatchFailure(['trace-1', 'trace-2'])
            }).toMatchValues({
                loadingTraceIds: new Set(['trace-3']),
            })
        })

        it('should preserve existing results when failing new ones', async () => {
            const existingResult: SentimentResult = {
                label: 'positive',
                score: 0.9,
                scores: { positive: 0.9, negative: 0.05, neutral: 0.05 },
                messages: {},
                message_count: 1,
            }

            logic.actions.loadSentimentBatchSuccess({ 'trace-1': existingResult }, ['trace-1'])
            logic.actions.loadSentimentBatchFailure(['trace-2', 'trace-3'])

            expect(logic.values.sentimentByTraceId).toEqual({
                'trace-1': existingResult,
                'trace-2': null,
                'trace-3': null,
            })
        })
    })

    describe('isTraceLoading selector', () => {
        it('should return false when trace is not loading', () => {
            expect(logic.values.isTraceLoading('trace-1')).toBe(false)
        })

        it('should return true when trace is loading', () => {
            logic.actions.ensureSentimentLoaded('trace-1')
            expect(logic.values.isTraceLoading('trace-1')).toBe(true)
        })

        it('should return false after successful load', () => {
            logic.actions.ensureSentimentLoaded('trace-1')

            const mockResult: SentimentResult = {
                label: 'positive',
                score: 0.9,
                scores: { positive: 0.9, negative: 0.05, neutral: 0.05 },
                messages: {},
                message_count: 1,
            }

            logic.actions.loadSentimentBatchSuccess({ 'trace-1': mockResult }, ['trace-1'])
            expect(logic.values.isTraceLoading('trace-1')).toBe(false)
        })

        it('should return false after failed load', () => {
            logic.actions.ensureSentimentLoaded('trace-1')
            logic.actions.loadSentimentBatchFailure(['trace-1'])
            expect(logic.values.isTraceLoading('trace-1')).toBe(false)
        })

        it.each([
            ['trace-1', 'trace-2', false, true],
            ['trace-2', 'trace-1', false, true],
            ['trace-3', 'trace-4', false, true],
        ])(
            'should handle multiple traces independently (%s loading, checking %s)',
            (loadingId, checkId, expectedCheck, expectedLoading) => {
                logic.actions.ensureSentimentLoaded(loadingId)
                expect(logic.values.isTraceLoading(checkId)).toBe(expectedCheck)
                expect(logic.values.isTraceLoading(loadingId)).toBe(expectedLoading)
            }
        )
    })

    describe('getTraceSentiment selector', () => {
        it('should return undefined when sentiment is not cached', () => {
            expect(logic.values.getTraceSentiment('trace-1')).toBeUndefined()
        })

        it('should return cached sentiment result', () => {
            const mockResult: SentimentResult = {
                label: 'positive',
                score: 0.9,
                scores: { positive: 0.9, negative: 0.05, neutral: 0.05 },
                messages: {},
                message_count: 1,
            }

            logic.actions.loadSentimentBatchSuccess({ 'trace-1': mockResult }, ['trace-1'])
            expect(logic.values.getTraceSentiment('trace-1')).toEqual(mockResult)
        })

        it('should return null for failed traces', () => {
            logic.actions.loadSentimentBatchFailure(['trace-1'])
            expect(logic.values.getTraceSentiment('trace-1')).toBeNull()
        })

        it('should return undefined while trace is loading', () => {
            logic.actions.ensureSentimentLoaded('trace-1')
            expect(logic.values.getTraceSentiment('trace-1')).toBeUndefined()
        })

        it.each([
            ['positive', 0.95, { positive: 0.95, negative: 0.03, neutral: 0.02 }],
            ['negative', 0.88, { positive: 0.05, negative: 0.88, neutral: 0.07 }],
            ['neutral', 0.75, { positive: 0.15, negative: 0.1, neutral: 0.75 }],
        ])('should handle different sentiment labels (%s)', (label, score, scores) => {
            const mockResult: SentimentResult = {
                label,
                score,
                scores,
                messages: {},
                message_count: 1,
            }

            logic.actions.loadSentimentBatchSuccess({ 'trace-1': mockResult }, ['trace-1'])
            const result = logic.values.getTraceSentiment('trace-1')
            expect(result?.label).toBe(label)
            expect(result?.score).toBe(score)
            expect(result?.scores).toEqual(scores)
        })
    })

    describe('edge cases', () => {
        it('should handle empty batch success', async () => {
            await expectLogic(logic, () => {
                logic.actions.loadSentimentBatchSuccess({}, [])
            }).toMatchValues({
                sentimentByTraceId: {},
                loadingTraceIds: new Set(),
            })
        })

        it('should handle empty batch failure', async () => {
            await expectLogic(logic, () => {
                logic.actions.loadSentimentBatchFailure([])
            }).toMatchValues({
                sentimentByTraceId: {},
                loadingTraceIds: new Set(),
            })
        })

        it('should overwrite existing sentiment when loading same trace again', () => {
            const result1: SentimentResult = {
                label: 'positive',
                score: 0.8,
                scores: { positive: 0.8, negative: 0.1, neutral: 0.1 },
                messages: {},
                message_count: 1,
            }

            const result2: SentimentResult = {
                label: 'negative',
                score: 0.9,
                scores: { positive: 0.05, negative: 0.9, neutral: 0.05 },
                messages: {},
                message_count: 1,
            }

            logic.actions.loadSentimentBatchSuccess({ 'trace-1': result1 }, ['trace-1'])
            expect(logic.values.getTraceSentiment('trace-1')).toEqual(result1)

            logic.actions.loadSentimentBatchSuccess({ 'trace-1': result2 }, ['trace-1'])
            expect(logic.values.getTraceSentiment('trace-1')).toEqual(result2)
        })

        it('should cap concurrent in-flight sentiment batches at 2', async () => {
            // Fake timers isolate this test from setTimeout leaks in prior cases
            // (the listener doesn't cancel its batch timer on unmount).
            jest.useFakeTimers()
            let createSpy: jest.SpyInstance | undefined
            try {
                // Fifteen trace IDs at BATCH_MAX_SIZE=5 → three chunks. With the
                // concurrency cap of 2, at most two api.create calls should be
                // in flight at once; the third chunk must wait for a slot.
                const release: Array<() => void> = []
                let inFlight = 0
                let peakInFlight = 0

                createSpy = jest.spyOn(api, 'create').mockImplementation(
                    () =>
                        new Promise((resolve) => {
                            inFlight++
                            peakInFlight = Math.max(peakInFlight, inFlight)
                            release.push(() => {
                                inFlight--
                                resolve({ results: {} } as any)
                            })
                        })
                )

                const traceIds = Array.from({ length: 15 }, (_, i) => `trace-${i}`)
                for (const id of traceIds) {
                    logic.actions.ensureSentimentLoaded(id)
                }

                // Fire the listener's setTimeout(0) and let the first two
                // runners start their api.create calls.
                jest.advanceTimersByTime(0)
                await Promise.resolve()
                await Promise.resolve()

                expect(peakInFlight).toBe(2)
                expect(createSpy).toHaveBeenCalledTimes(2)

                // Releasing the first in-flight promise frees a slot so the
                // third chunk can start. Peak must remain at 2.
                release.shift()!()
                await Promise.resolve()
                await Promise.resolve()
                expect(peakInFlight).toBe(2)
                expect(createSpy).toHaveBeenCalledTimes(3)

                while (release.length > 0) {
                    release.shift()!()
                    await Promise.resolve()
                }
            } finally {
                createSpy?.mockRestore()
                jest.useRealTimers()
            }
        })

        it('should handle partial batch success with some nulls', () => {
            const result1: SentimentResult = {
                label: 'positive',
                score: 0.9,
                scores: { positive: 0.9, negative: 0.05, neutral: 0.05 },
                messages: {},
                message_count: 1,
            }

            logic.actions.loadSentimentBatchSuccess({ 'trace-1': result1 }, ['trace-1', 'trace-2', 'trace-3'])

            expect(logic.values.sentimentByTraceId).toEqual({
                'trace-1': result1,
                'trace-2': null,
                'trace-3': null,
            })
        })
    })
})
