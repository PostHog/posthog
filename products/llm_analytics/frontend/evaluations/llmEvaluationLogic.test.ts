import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { LLMProviderKey, llmProviderKeysLogic } from '../settings/llmProviderKeysLogic'
import { llmEvaluationLogic } from './llmEvaluationLogic'
import { EvaluationConfig, EvaluationRun } from './types'

const mockProviderKeys: LLMProviderKey[] = [
    {
        id: 'key-1',
        provider: 'openai',
        name: 'Production Key',
        state: 'ok',
        error_message: null,
        api_key_masked: 'sk-...1234',
        created_at: '2024-01-01T00:00:00Z',
        created_by: null,
        last_used_at: null,
    },
    {
        id: 'key-2',
        provider: 'anthropic',
        name: 'Anthropic Key',
        state: 'ok',
        error_message: null,
        api_key_masked: 'sk-ant-...5678',
        created_at: '2024-01-02T00:00:00Z',
        created_by: null,
        last_used_at: null,
    },
]

const mockEvaluation: EvaluationConfig = {
    id: 'eval-123',
    name: 'Test Evaluation',
    description: 'A test evaluation',
    enabled: true,
    evaluation_type: 'llm_judge',
    evaluation_config: { prompt: 'Is this response helpful?' },
    output_type: 'boolean',
    output_config: { allows_na: false },
    conditions: [{ id: 'cond-1', rollout_percentage: 50, properties: [] }],
    model_configuration: {
        provider: 'openai',
        model: 'gpt-5-mini',
        provider_key_id: 'key-1',
    },
    total_runs: 10,
    created_at: '2024-01-01T00:00:00Z',
    updated_at: '2024-01-01T00:00:00Z',
}

const mockRuns: EvaluationRun[] = [
    {
        id: 'run-1',
        evaluation_id: 'eval-123',
        evaluation_name: 'Test Evaluation',
        generation_id: 'gen-1',
        trace_id: 'trace-1',
        timestamp: '2024-01-01T12:00:00Z',
        result: true,
        applicable: true,
        reasoning: 'The response was helpful',
        status: 'completed',
    },
    {
        id: 'run-2',
        evaluation_id: 'eval-123',
        evaluation_name: 'Test Evaluation',
        generation_id: 'gen-2',
        trace_id: 'trace-2',
        timestamp: '2024-01-01T13:00:00Z',
        result: false,
        applicable: true,
        reasoning: 'The response was not helpful',
        status: 'completed',
    },
    {
        id: 'run-3',
        evaluation_id: 'eval-123',
        evaluation_name: 'Test Evaluation',
        generation_id: 'gen-3',
        trace_id: 'trace-3',
        timestamp: '2024-01-01T14:00:00Z',
        result: null,
        applicable: false,
        reasoning: 'Not applicable',
        status: 'completed',
    },
]

describe('llmEvaluationLogic', () => {
    let logic: ReturnType<typeof llmEvaluationLogic.build>
    let keysLogic: ReturnType<typeof llmProviderKeysLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/environments/:teamId/llm_analytics/provider_keys/': { results: mockProviderKeys },
                '/api/environments/:teamId/llm_analytics/evaluation_config/': {
                    trial_eval_limit: 100,
                    trial_evals_used: 0,
                    trial_evals_remaining: 100,
                    active_provider_key: null,
                    created_at: '2024-01-01T00:00:00Z',
                    updated_at: '2024-01-01T00:00:00Z',
                },
                '/api/environments/:teamId/evaluations/:id/': mockEvaluation,
                '/api/environments/:teamId/llm_analytics/models/': {
                    models: [
                        { id: 'gpt-5-mini', posthog_available: true },
                        { id: 'gpt-5', posthog_available: false },
                    ],
                },
            },
        })
        initKeaTests()
        keysLogic = llmProviderKeysLogic()
        keysLogic.mount()
    })

    afterEach(() => {
        logic?.unmount()
        keysLogic?.unmount()
    })

    describe('reducers', () => {
        beforeEach(() => {
            logic = llmEvaluationLogic({ evaluationId: 'new' })
            logic.mount()
        })

        it('setEvaluationName updates evaluation name', async () => {
            await expectLogic(logic).toDispatchActions(['loadEvaluationSuccess'])

            logic.actions.setEvaluationName('New Name')

            await expectLogic(logic).toMatchValues({
                evaluation: expect.objectContaining({ name: 'New Name' }),
                hasUnsavedChanges: true,
            })
        })

        it('setEvaluationPrompt updates evaluation prompt', async () => {
            await expectLogic(logic).toDispatchActions(['loadEvaluationSuccess'])

            logic.actions.setEvaluationPrompt('New prompt')

            await expectLogic(logic).toMatchValues({
                evaluation: expect.objectContaining({
                    evaluation_config: { prompt: 'New prompt' },
                }),
            })
        })

        it('setAllowsNA updates output config', async () => {
            await expectLogic(logic).toDispatchActions(['loadEvaluationSuccess'])

            logic.actions.setAllowsNA(true)

            await expectLogic(logic).toMatchValues({
                evaluation: expect.objectContaining({
                    output_config: { allows_na: true },
                }),
            })
        })

        it('setTriggerConditions updates conditions', async () => {
            await expectLogic(logic).toDispatchActions(['loadEvaluationSuccess'])

            const newConditions = [{ id: 'new-cond', rollout_percentage: 100, properties: [] }]
            logic.actions.setTriggerConditions(newConditions)

            await expectLogic(logic).toMatchValues({
                evaluation: expect.objectContaining({ conditions: newConditions }),
            })
        })

        it('setModelConfiguration updates model config', async () => {
            await expectLogic(logic).toDispatchActions(['loadEvaluationSuccess'])

            const newConfig = { provider: 'anthropic' as const, model: 'claude-3-5-haiku', provider_key_id: 'key-2' }
            logic.actions.setModelConfiguration(newConfig)

            await expectLogic(logic).toMatchValues({
                evaluation: expect.objectContaining({ model_configuration: newConfig }),
            })
        })

        it('hasUnsavedChanges resets on save success', async () => {
            await expectLogic(logic).toDispatchActions(['loadEvaluationSuccess'])

            logic.actions.setEvaluationName('Changed Name')

            await expectLogic(logic).toMatchValues({ hasUnsavedChanges: true })

            logic.actions.saveEvaluationSuccess(mockEvaluation)

            await expectLogic(logic).toMatchValues({ hasUnsavedChanges: false })
        })
    })

    describe('selectors', () => {
        describe('formValid', () => {
            beforeEach(() => {
                logic = llmEvaluationLogic({ evaluationId: 'new' })
                logic.mount()
            })

            it('returns false when evaluation is null', async () => {
                expect(logic.values.formValid).toBe(false)
            })

            it('returns false when name is empty', async () => {
                await expectLogic(logic).toDispatchActions(['loadEvaluationSuccess'])

                await expectLogic(logic).toMatchValues({ formValid: false })
            })

            it('returns false when prompt is empty', async () => {
                await expectLogic(logic).toDispatchActions(['loadEvaluationSuccess'])
                logic.actions.setEvaluationName('Valid Name')
                logic.actions.setTriggerConditions([{ id: 'c1', rollout_percentage: 50, properties: [] }])

                await expectLogic(logic).toMatchValues({ formValid: false })
            })

            it('returns false when no conditions have rollout > 0', async () => {
                await expectLogic(logic).toDispatchActions(['loadEvaluationSuccess'])
                logic.actions.setEvaluationName('Valid Name')
                logic.actions.setEvaluationPrompt('Valid prompt')

                await expectLogic(logic).toMatchValues({ formValid: false })
            })

            it('returns true when all fields valid', async () => {
                await expectLogic(logic).toDispatchActions(['loadEvaluationSuccess'])
                logic.actions.setEvaluationName('Valid Name')
                logic.actions.setEvaluationPrompt('Valid prompt')
                logic.actions.setTriggerConditions([{ id: 'c1', rollout_percentage: 50, properties: [] }])

                await expectLogic(logic).toMatchValues({ formValid: true })
            })
        })

        describe('providerKeysByProvider', () => {
            beforeEach(() => {
                logic = llmEvaluationLogic({ evaluationId: 'new' })
                logic.mount()
            })

            it('groups keys by provider', async () => {
                await expectLogic(keysLogic).toDispatchActions(['loadProviderKeysSuccess'])

                const byProvider = logic.values.providerKeysByProvider
                expect(byProvider.openai).toHaveLength(1)
                expect(byProvider.openai[0].id).toBe('key-1')
                expect(byProvider.anthropic).toHaveLength(1)
                expect(byProvider.anthropic[0].id).toBe('key-2')
                expect(byProvider.gemini).toHaveLength(0)
            })
        })

        describe('runsSummary', () => {
            beforeEach(() => {
                logic = llmEvaluationLogic({ evaluationId: 'eval-123' })
                logic.mount()
            })

            it('returns null when no runs', async () => {
                expect(logic.values.runsSummary).toBeNull()
            })

            it('calculates summary correctly', async () => {
                logic.actions.loadEvaluationRunsSuccess(mockRuns)

                await expectLogic(logic).toMatchValues({
                    runsSummary: {
                        total: 3,
                        successful: 1,
                        failed: 1,
                        errors: 0,
                        successRate: 50,
                        applicabilityRate: 67,
                    },
                })
            })
        })
    })

    describe('async flows', () => {
        describe('loadEvaluation', () => {
            it('initializes new evaluation with default values', async () => {
                logic = llmEvaluationLogic({ evaluationId: 'new' })
                logic.mount()

                await expectLogic(logic).toDispatchActions(['loadEvaluationSuccess'])

                await expectLogic(logic).toMatchValues({
                    isNewEvaluation: true,
                    evaluation: expect.objectContaining({
                        id: '',
                        name: '',
                        enabled: true,
                        evaluation_type: 'llm_judge',
                        output_type: 'boolean',
                    }),
                })
            })

            it('loads existing evaluation', async () => {
                logic = llmEvaluationLogic({ evaluationId: 'eval-123' })
                logic.mount()

                await expectLogic(logic).toDispatchActions(['loadEvaluationSuccess'])

                await expectLogic(logic).toMatchValues({
                    isNewEvaluation: false,
                    evaluation: expect.objectContaining({
                        id: 'eval-123',
                        name: 'Test Evaluation',
                    }),
                })
            })

            it('applies template when provided', async () => {
                logic = llmEvaluationLogic({ evaluationId: 'new', templateKey: 'factuality' })
                logic.mount()

                await expectLogic(logic).toDispatchActions(['loadEvaluationSuccess'])

                await expectLogic(logic).toMatchValues({
                    evaluation: expect.objectContaining({
                        name: expect.any(String),
                        evaluation_config: expect.objectContaining({
                            prompt: expect.any(String),
                        }),
                    }),
                })
            })
        })

        describe('resetEvaluation', () => {
            it('resets new evaluation to defaults', async () => {
                logic = llmEvaluationLogic({ evaluationId: 'new' })
                logic.mount()

                await expectLogic(logic).toDispatchActions(['loadEvaluationSuccess'])

                logic.actions.setEvaluationName('Changed Name')
                logic.actions.resetEvaluation()

                await expectLogic(logic).toMatchValues({
                    evaluation: expect.objectContaining({ name: '' }),
                    hasUnsavedChanges: false,
                })
            })

            it('resets existing evaluation to original', async () => {
                logic = llmEvaluationLogic({ evaluationId: 'eval-123' })
                logic.mount()

                await expectLogic(logic).toDispatchActions(['loadEvaluationSuccess'])

                logic.actions.setEvaluationName('Changed Name')
                logic.actions.resetEvaluation()

                await expectLogic(logic).toMatchValues({
                    evaluation: expect.objectContaining({ name: 'Test Evaluation' }),
                    hasUnsavedChanges: false,
                })
            })
        })
    })

    describe('provider selection', () => {
        beforeEach(() => {
            logic = llmEvaluationLogic({ evaluationId: 'new' })
            logic.mount()
        })

        it('setSelectedProvider dispatches loadAvailableModels', async () => {
            await expectLogic(logic).toDispatchActions(['loadEvaluationSuccess'])

            logic.actions.setSelectedProvider('anthropic')

            await expectLogic(logic).toMatchValues({
                selectedProvider: 'anthropic',
            })
        })

        it('setSelectedKeyId resets model selection', async () => {
            await expectLogic(logic).toDispatchActions(['loadEvaluationSuccess'])

            logic.actions.setSelectedModel('gpt-5-mini')

            await expectLogic(logic).toMatchValues({ selectedModel: 'gpt-5-mini' })

            logic.actions.setSelectedKeyId('key-1')

            await expectLogic(logic).toMatchValues({ selectedModel: '' })
        })

        it('setSelectedModel updates model configuration', async () => {
            await expectLogic(logic).toDispatchActions(['loadEvaluationSuccess'])

            logic.actions.setSelectedModel('gpt-5-mini')

            await expectLogic(logic).toMatchValues({
                selectedModel: 'gpt-5-mini',
                evaluation: expect.objectContaining({
                    model_configuration: expect.objectContaining({
                        model: 'gpt-5-mini',
                    }),
                }),
            })
        })
    })
})
