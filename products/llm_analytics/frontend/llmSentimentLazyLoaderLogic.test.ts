import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import {
    GenerationSentiment,
    MessageSentiment,
    SentimentResult,
    llmSentimentLazyLoaderLogic,
} from './llmSentimentLazyLoaderLogic'

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
                trace_id: 'trace-1',
                label: 'positive',
                score: 0.95,
                scores: { positive: 0.95, negative: 0.03, neutral: 0.02 },
                generations: {},
                generation_count: 1,
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
                trace_id: 'trace-1',
                label: 'positive',
                score: 0.8,
                scores: { positive: 0.8, negative: 0.1, neutral: 0.1 },
                generations: {},
                generation_count: 0,
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
                trace_id: 'trace-1',
                label: 'positive',
                score: 0.9,
                scores: { positive: 0.9, negative: 0.05, neutral: 0.05 },
                generations: {},
                generation_count: 1,
                message_count: 1,
            }

            const result2: SentimentResult = {
                trace_id: 'trace-2',
                label: 'negative',
                score: 0.85,
                scores: { positive: 0.1, negative: 0.85, neutral: 0.05 },
                generations: {},
                generation_count: 2,
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
                trace_id: 'trace-1',
                label: 'positive',
                score: 0.9,
                scores: { positive: 0.9, negative: 0.05, neutral: 0.05 },
                generations: {},
                generation_count: 1,
                message_count: 1,
            }

            const result2: SentimentResult = {
                trace_id: 'trace-2',
                label: 'negative',
                score: 0.8,
                scores: { positive: 0.1, negative: 0.8, neutral: 0.1 },
                generations: {},
                generation_count: 1,
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
                trace_id: 'trace-1',
                label: 'positive',
                score: 0.9,
                scores: { positive: 0.9, negative: 0.05, neutral: 0.05 },
                generations: {},
                generation_count: 1,
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
                trace_id: 'trace-1',
                label: 'positive',
                score: 0.9,
                scores: { positive: 0.9, negative: 0.05, neutral: 0.05 },
                generations: {},
                generation_count: 1,
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
                trace_id: 'trace-1',
                label: 'positive',
                score: 0.9,
                scores: { positive: 0.9, negative: 0.05, neutral: 0.05 },
                generations: {},
                generation_count: 1,
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
                trace_id: 'trace-1',
                label,
                score,
                scores,
                generations: {},
                generation_count: 1,
                message_count: 1,
            }

            logic.actions.loadSentimentBatchSuccess({ 'trace-1': mockResult }, ['trace-1'])
            const result = logic.values.getTraceSentiment('trace-1')
            expect(result?.label).toBe(label)
            expect(result?.score).toBe(score)
            expect(result?.scores).toEqual(scores)
        })
    })

    describe('getGenerationSentiment selector', () => {
        it('should return undefined when trace has no sentiment', () => {
            expect(logic.values.getGenerationSentiment('trace-1', 'gen-1')).toBeUndefined()
        })

        it('should return undefined when trace sentiment is null', () => {
            logic.actions.loadSentimentBatchFailure(['trace-1'])
            expect(logic.values.getGenerationSentiment('trace-1', 'gen-1')).toBeUndefined()
        })

        it('should return undefined when generation does not exist', () => {
            const mockResult: SentimentResult = {
                trace_id: 'trace-1',
                label: 'positive',
                score: 0.9,
                scores: { positive: 0.9, negative: 0.05, neutral: 0.05 },
                generations: {},
                generation_count: 0,
                message_count: 1,
            }

            logic.actions.loadSentimentBatchSuccess({ 'trace-1': mockResult }, ['trace-1'])
            expect(logic.values.getGenerationSentiment('trace-1', 'gen-1')).toBeUndefined()
        })

        it('should return generation sentiment when it exists', () => {
            const messageSentiment: MessageSentiment = {
                label: 'positive',
                score: 0.92,
                scores: { positive: 0.92, negative: 0.04, neutral: 0.04 },
            }

            const generationSentiment: GenerationSentiment = {
                label: 'positive',
                score: 0.9,
                scores: { positive: 0.9, negative: 0.05, neutral: 0.05 },
                messages: {
                    0: messageSentiment,
                },
            }

            const mockResult: SentimentResult = {
                trace_id: 'trace-1',
                label: 'positive',
                score: 0.9,
                scores: { positive: 0.9, negative: 0.05, neutral: 0.05 },
                generations: {
                    'gen-1': generationSentiment,
                },
                generation_count: 1,
                message_count: 1,
            }

            logic.actions.loadSentimentBatchSuccess({ 'trace-1': mockResult }, ['trace-1'])
            expect(logic.values.getGenerationSentiment('trace-1', 'gen-1')).toEqual(generationSentiment)
        })

        it('should handle multiple generations in a trace', () => {
            const gen1Sentiment: GenerationSentiment = {
                label: 'positive',
                score: 0.9,
                scores: { positive: 0.9, negative: 0.05, neutral: 0.05 },
                messages: {},
            }

            const gen2Sentiment: GenerationSentiment = {
                label: 'negative',
                score: 0.85,
                scores: { positive: 0.1, negative: 0.85, neutral: 0.05 },
                messages: {},
            }

            const mockResult: SentimentResult = {
                trace_id: 'trace-1',
                label: 'positive',
                score: 0.88,
                scores: { positive: 0.88, negative: 0.08, neutral: 0.04 },
                generations: {
                    'gen-1': gen1Sentiment,
                    'gen-2': gen2Sentiment,
                },
                generation_count: 2,
                message_count: 0,
            }

            logic.actions.loadSentimentBatchSuccess({ 'trace-1': mockResult }, ['trace-1'])
            expect(logic.values.getGenerationSentiment('trace-1', 'gen-1')).toEqual(gen1Sentiment)
            expect(logic.values.getGenerationSentiment('trace-1', 'gen-2')).toEqual(gen2Sentiment)
            expect(logic.values.getGenerationSentiment('trace-1', 'gen-3')).toBeUndefined()
        })

        it('should handle message-level sentiment within generations', () => {
            const message0: MessageSentiment = {
                label: 'positive',
                score: 0.95,
                scores: { positive: 0.95, negative: 0.03, neutral: 0.02 },
            }

            const message1: MessageSentiment = {
                label: 'neutral',
                score: 0.7,
                scores: { positive: 0.2, negative: 0.1, neutral: 0.7 },
            }

            const generationSentiment: GenerationSentiment = {
                label: 'positive',
                score: 0.85,
                scores: { positive: 0.85, negative: 0.08, neutral: 0.07 },
                messages: {
                    0: message0,
                    1: message1,
                },
            }

            const mockResult: SentimentResult = {
                trace_id: 'trace-1',
                label: 'positive',
                score: 0.85,
                scores: { positive: 0.85, negative: 0.08, neutral: 0.07 },
                generations: {
                    'gen-1': generationSentiment,
                },
                generation_count: 1,
                message_count: 2,
            }

            logic.actions.loadSentimentBatchSuccess({ 'trace-1': mockResult }, ['trace-1'])
            const result = logic.values.getGenerationSentiment('trace-1', 'gen-1')
            expect(result?.messages[0]).toEqual(message0)
            expect(result?.messages[1]).toEqual(message1)
            expect(result?.messages[2]).toBeUndefined()
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
                trace_id: 'trace-1',
                label: 'positive',
                score: 0.8,
                scores: { positive: 0.8, negative: 0.1, neutral: 0.1 },
                generations: {},
                generation_count: 1,
                message_count: 1,
            }

            const result2: SentimentResult = {
                trace_id: 'trace-1',
                label: 'negative',
                score: 0.9,
                scores: { positive: 0.05, negative: 0.9, neutral: 0.05 },
                generations: {},
                generation_count: 1,
                message_count: 1,
            }

            logic.actions.loadSentimentBatchSuccess({ 'trace-1': result1 }, ['trace-1'])
            expect(logic.values.getTraceSentiment('trace-1')).toEqual(result1)

            logic.actions.loadSentimentBatchSuccess({ 'trace-1': result2 }, ['trace-1'])
            expect(logic.values.getTraceSentiment('trace-1')).toEqual(result2)
        })

        it('should handle partial batch success with some nulls', () => {
            const result1: SentimentResult = {
                trace_id: 'trace-1',
                label: 'positive',
                score: 0.9,
                scores: { positive: 0.9, negative: 0.05, neutral: 0.05 },
                generations: {},
                generation_count: 1,
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
