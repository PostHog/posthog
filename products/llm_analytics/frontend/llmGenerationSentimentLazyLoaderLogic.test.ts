import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { llmGenerationSentimentLazyLoaderLogic } from './llmGenerationSentimentLazyLoaderLogic'
import type { GenerationSentiment, MessageSentiment } from './llmSentimentLazyLoaderLogic'

describe('llmGenerationSentimentLazyLoaderLogic', () => {
    let logic: ReturnType<typeof llmGenerationSentimentLazyLoaderLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = llmGenerationSentimentLazyLoaderLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    describe('initial state', () => {
        it('should have empty sentiment cache', () => {
            expect(logic.values.sentimentByGenerationId).toEqual({})
        })

        it('should have empty loading set', () => {
            expect(logic.values.loadingGenerationIds).toEqual(new Set())
        })
    })

    describe('ensureGenerationSentimentLoaded action', () => {
        it('should add generation ID to loading set', async () => {
            await expectLogic(logic, () => {
                logic.actions.ensureGenerationSentimentLoaded('gen-1')
            }).toMatchValues({
                loadingGenerationIds: new Set(['gen-1']),
            })
        })

        it('should handle multiple generation IDs', async () => {
            logic.actions.ensureGenerationSentimentLoaded('gen-1')
            logic.actions.ensureGenerationSentimentLoaded('gen-2')
            logic.actions.ensureGenerationSentimentLoaded('gen-3')

            expect(logic.values.loadingGenerationIds).toEqual(new Set(['gen-1', 'gen-2', 'gen-3']))
        })

        it('should not add duplicate generation IDs to loading set', async () => {
            logic.actions.ensureGenerationSentimentLoaded('gen-1')
            logic.actions.ensureGenerationSentimentLoaded('gen-1')
            logic.actions.ensureGenerationSentimentLoaded('gen-1')

            expect(logic.values.loadingGenerationIds).toEqual(new Set(['gen-1']))
        })
    })

    describe('loadGenerationSentimentBatchSuccess action', () => {
        it('should store sentiment results', async () => {
            const mockResult: GenerationSentiment = {
                label: 'positive',
                score: 0.95,
                scores: { positive: 0.95, negative: 0.03, neutral: 0.02 },
                messages: {},
            }

            await expectLogic(logic, () => {
                logic.actions.loadGenerationSentimentBatchSuccess({ 'gen-1': mockResult }, ['gen-1'])
            }).toMatchValues({
                sentimentByGenerationId: {
                    'gen-1': mockResult,
                },
            })
        })

        it('should remove generation IDs from loading set', async () => {
            logic.actions.ensureGenerationSentimentLoaded('gen-1')
            logic.actions.ensureGenerationSentimentLoaded('gen-2')

            const mockResult: GenerationSentiment = {
                label: 'positive',
                score: 0.8,
                scores: { positive: 0.8, negative: 0.1, neutral: 0.1 },
                messages: {},
            }

            await expectLogic(logic, () => {
                logic.actions.loadGenerationSentimentBatchSuccess({ 'gen-1': mockResult }, ['gen-1'])
            }).toMatchValues({
                loadingGenerationIds: new Set(['gen-2']),
            })
        })

        it('should store null for generations without results', async () => {
            await expectLogic(logic, () => {
                logic.actions.loadGenerationSentimentBatchSuccess({}, ['gen-1', 'gen-2'])
            }).toMatchValues({
                sentimentByGenerationId: {
                    'gen-1': null,
                    'gen-2': null,
                },
            })
        })

        it('should handle multiple results in batch', async () => {
            const result1: GenerationSentiment = {
                label: 'positive',
                score: 0.9,
                scores: { positive: 0.9, negative: 0.05, neutral: 0.05 },
                messages: {},
            }

            const result2: GenerationSentiment = {
                label: 'negative',
                score: 0.85,
                scores: { positive: 0.1, negative: 0.85, neutral: 0.05 },
                messages: {},
            }

            await expectLogic(logic, () => {
                logic.actions.loadGenerationSentimentBatchSuccess({ 'gen-1': result1, 'gen-2': result2 }, [
                    'gen-1',
                    'gen-2',
                ])
            }).toMatchValues({
                sentimentByGenerationId: {
                    'gen-1': result1,
                    'gen-2': result2,
                },
            })
        })

        it('should preserve existing results when adding new ones', async () => {
            const result1: GenerationSentiment = {
                label: 'positive',
                score: 0.9,
                scores: { positive: 0.9, negative: 0.05, neutral: 0.05 },
                messages: {},
            }

            const result2: GenerationSentiment = {
                label: 'negative',
                score: 0.8,
                scores: { positive: 0.1, negative: 0.8, neutral: 0.1 },
                messages: {},
            }

            logic.actions.loadGenerationSentimentBatchSuccess({ 'gen-1': result1 }, ['gen-1'])
            logic.actions.loadGenerationSentimentBatchSuccess({ 'gen-2': result2 }, ['gen-2'])

            expect(logic.values.sentimentByGenerationId).toEqual({
                'gen-1': result1,
                'gen-2': result2,
            })
        })
    })

    describe('loadGenerationSentimentBatchFailure action', () => {
        it('should set null for failed generations', async () => {
            await expectLogic(logic, () => {
                logic.actions.loadGenerationSentimentBatchFailure(['gen-1', 'gen-2'])
            }).toMatchValues({
                sentimentByGenerationId: {
                    'gen-1': null,
                    'gen-2': null,
                },
            })
        })

        it('should remove generation IDs from loading set', async () => {
            logic.actions.ensureGenerationSentimentLoaded('gen-1')
            logic.actions.ensureGenerationSentimentLoaded('gen-2')
            logic.actions.ensureGenerationSentimentLoaded('gen-3')

            await expectLogic(logic, () => {
                logic.actions.loadGenerationSentimentBatchFailure(['gen-1', 'gen-2'])
            }).toMatchValues({
                loadingGenerationIds: new Set(['gen-3']),
            })
        })

        it('should preserve existing results when failing new ones', async () => {
            const existingResult: GenerationSentiment = {
                label: 'positive',
                score: 0.9,
                scores: { positive: 0.9, negative: 0.05, neutral: 0.05 },
                messages: {},
            }

            logic.actions.loadGenerationSentimentBatchSuccess({ 'gen-1': existingResult }, ['gen-1'])
            logic.actions.loadGenerationSentimentBatchFailure(['gen-2', 'gen-3'])

            expect(logic.values.sentimentByGenerationId).toEqual({
                'gen-1': existingResult,
                'gen-2': null,
                'gen-3': null,
            })
        })
    })

    describe('isGenerationLoading selector', () => {
        it('should return false when generation is not loading', () => {
            expect(logic.values.isGenerationLoading('gen-1')).toBe(false)
        })

        it('should return true when generation is loading', () => {
            logic.actions.ensureGenerationSentimentLoaded('gen-1')
            expect(logic.values.isGenerationLoading('gen-1')).toBe(true)
        })

        it('should return false after successful load', () => {
            logic.actions.ensureGenerationSentimentLoaded('gen-1')

            const mockResult: GenerationSentiment = {
                label: 'positive',
                score: 0.9,
                scores: { positive: 0.9, negative: 0.05, neutral: 0.05 },
                messages: {},
            }

            logic.actions.loadGenerationSentimentBatchSuccess({ 'gen-1': mockResult }, ['gen-1'])
            expect(logic.values.isGenerationLoading('gen-1')).toBe(false)
        })

        it('should return false after failed load', () => {
            logic.actions.ensureGenerationSentimentLoaded('gen-1')
            logic.actions.loadGenerationSentimentBatchFailure(['gen-1'])
            expect(logic.values.isGenerationLoading('gen-1')).toBe(false)
        })

        it.each([
            ['gen-1', 'gen-2', false, true],
            ['gen-2', 'gen-1', false, true],
            ['gen-3', 'gen-4', false, true],
        ])(
            'should handle multiple generations independently (%s loading, checking %s)',
            (loadingId, checkId, expectedCheck, expectedLoading) => {
                logic.actions.ensureGenerationSentimentLoaded(loadingId)
                expect(logic.values.isGenerationLoading(checkId)).toBe(expectedCheck)
                expect(logic.values.isGenerationLoading(loadingId)).toBe(expectedLoading)
            }
        )
    })

    describe('getGenerationSentiment selector', () => {
        it('should return undefined when sentiment is not cached', () => {
            expect(logic.values.getGenerationSentiment('gen-1')).toBeUndefined()
        })

        it('should return cached sentiment result', () => {
            const mockResult: GenerationSentiment = {
                label: 'positive',
                score: 0.9,
                scores: { positive: 0.9, negative: 0.05, neutral: 0.05 },
                messages: {},
            }

            logic.actions.loadGenerationSentimentBatchSuccess({ 'gen-1': mockResult }, ['gen-1'])
            expect(logic.values.getGenerationSentiment('gen-1')).toEqual(mockResult)
        })

        it('should return null for failed generations', () => {
            logic.actions.loadGenerationSentimentBatchFailure(['gen-1'])
            expect(logic.values.getGenerationSentiment('gen-1')).toBeNull()
        })

        it('should return undefined while generation is loading', () => {
            logic.actions.ensureGenerationSentimentLoaded('gen-1')
            expect(logic.values.getGenerationSentiment('gen-1')).toBeUndefined()
        })

        it.each([
            ['positive', 0.95, { positive: 0.95, negative: 0.03, neutral: 0.02 }],
            ['negative', 0.88, { positive: 0.05, negative: 0.88, neutral: 0.07 }],
            ['neutral', 0.75, { positive: 0.15, negative: 0.1, neutral: 0.75 }],
        ])('should handle different sentiment labels (%s)', (label, score, scores) => {
            const mockResult: GenerationSentiment = {
                label,
                score,
                scores,
                messages: {},
            }

            logic.actions.loadGenerationSentimentBatchSuccess({ 'gen-1': mockResult }, ['gen-1'])
            const result = logic.values.getGenerationSentiment('gen-1')
            expect(result?.label).toBe(label)
            expect(result?.score).toBe(score)
            expect(result?.scores).toEqual(scores)
        })

        it('should handle message-level sentiment within generation', () => {
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

            logic.actions.loadGenerationSentimentBatchSuccess({ 'gen-1': generationSentiment }, ['gen-1'])
            const result = logic.values.getGenerationSentiment('gen-1')
            expect(result?.messages[0]).toEqual(message0)
            expect(result?.messages[1]).toEqual(message1)
            expect(result?.messages[2]).toBeUndefined()
        })
    })

    describe('edge cases', () => {
        it('should handle empty batch success', async () => {
            await expectLogic(logic, () => {
                logic.actions.loadGenerationSentimentBatchSuccess({}, [])
            }).toMatchValues({
                sentimentByGenerationId: {},
                loadingGenerationIds: new Set(),
            })
        })

        it('should handle empty batch failure', async () => {
            await expectLogic(logic, () => {
                logic.actions.loadGenerationSentimentBatchFailure([])
            }).toMatchValues({
                sentimentByGenerationId: {},
                loadingGenerationIds: new Set(),
            })
        })

        it('should overwrite existing sentiment when loading same generation again', () => {
            const result1: GenerationSentiment = {
                label: 'positive',
                score: 0.8,
                scores: { positive: 0.8, negative: 0.1, neutral: 0.1 },
                messages: {},
            }

            const result2: GenerationSentiment = {
                label: 'negative',
                score: 0.9,
                scores: { positive: 0.05, negative: 0.9, neutral: 0.05 },
                messages: {},
            }

            logic.actions.loadGenerationSentimentBatchSuccess({ 'gen-1': result1 }, ['gen-1'])
            expect(logic.values.getGenerationSentiment('gen-1')).toEqual(result1)

            logic.actions.loadGenerationSentimentBatchSuccess({ 'gen-1': result2 }, ['gen-1'])
            expect(logic.values.getGenerationSentiment('gen-1')).toEqual(result2)
        })

        it('should handle partial batch success with some nulls', () => {
            const result1: GenerationSentiment = {
                label: 'positive',
                score: 0.9,
                scores: { positive: 0.9, negative: 0.05, neutral: 0.05 },
                messages: {},
            }

            logic.actions.loadGenerationSentimentBatchSuccess({ 'gen-1': result1 }, ['gen-1', 'gen-2', 'gen-3'])

            expect(logic.values.sentimentByGenerationId).toEqual({
                'gen-1': result1,
                'gen-2': null,
                'gen-3': null,
            })
        })
    })
})
