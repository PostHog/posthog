import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { LLMProviderKey, llmProviderKeysLogic } from '../settings/llmProviderKeysLogic'
import { llmEvaluationsLogic } from './llmEvaluationsLogic'
import { EvaluationConfig } from './types'

const mockProviderKeys: LLMProviderKey[] = [
    {
        id: 'key-ok',
        provider: 'openai',
        name: 'OpenAI production',
        state: 'ok',
        error_message: null,
        api_key_masked: 'sk-...1111',
        created_at: '2024-01-01T00:00:00Z',
        created_by: null,
        last_used_at: null,
    },
    {
        id: 'key-invalid',
        provider: 'anthropic',
        name: 'Anthropic key',
        state: 'invalid',
        error_message: 'Invalid API key',
        api_key_masked: 'sk-ant-...2222',
        created_at: '2024-01-02T00:00:00Z',
        created_by: null,
        last_used_at: null,
    },
    {
        id: 'key-error',
        provider: 'openrouter',
        name: 'OpenRouter key',
        state: 'error',
        error_message: 'Quota exceeded',
        api_key_masked: 'sk-or-...3333',
        created_at: '2024-01-03T00:00:00Z',
        created_by: null,
        last_used_at: null,
    },
]

const evaluationWithKey = (id: string, providerKeyId: string | null): EvaluationConfig => ({
    id,
    name: `Evaluation ${id}`,
    description: '',
    enabled: true,
    evaluation_type: 'llm_judge',
    evaluation_config: { prompt: 'Prompt' },
    output_type: 'boolean',
    output_config: {},
    conditions: [{ id: `cond-${id}`, rollout_percentage: 100, properties: [] }],
    model_configuration: providerKeyId
        ? {
              provider: 'openai',
              model: 'gpt-5-mini',
              provider_key_id: providerKeyId,
          }
        : null,
    total_runs: 0,
    created_at: '2024-01-01T00:00:00Z',
    updated_at: '2024-01-01T00:00:00Z',
})

describe('llmEvaluationsLogic', () => {
    let logic: ReturnType<typeof llmEvaluationsLogic.build>
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
                '/api/environments/:teamId/evaluations/': {
                    results: [
                        evaluationWithKey('eval-ok', 'key-ok'),
                        evaluationWithKey('eval-invalid', 'key-invalid'),
                        evaluationWithKey('eval-error', 'key-error'),
                        evaluationWithKey('eval-invalid-duplicate', 'key-invalid'),
                        evaluationWithKey('eval-default', null),
                    ],
                },
            },
        })

        initKeaTests()
        keysLogic = llmProviderKeysLogic()
        keysLogic.mount()

        logic = llmEvaluationsLogic()
        logic.mount()
    })

    afterEach(() => {
        logic?.unmount()
        keysLogic?.unmount()
    })

    describe('unhealthyProviderKeysUsedByEvaluations', () => {
        it('returns unhealthy keys used by evaluations without duplicates', async () => {
            logic.actions.loadEvaluations()
            keysLogic.actions.loadProviderKeys()
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.unhealthyProviderKeysUsedByEvaluations).toEqual([
                expect.objectContaining({ id: 'key-invalid', state: 'invalid' }),
                expect.objectContaining({ id: 'key-error', state: 'error' }),
            ])
        })

        it('returns an empty array when all used keys are healthy', async () => {
            logic.actions.loadEvaluationsSuccess([
                evaluationWithKey('eval-ok-1', 'key-ok'),
                evaluationWithKey('eval-default', null),
            ])
            keysLogic.actions.loadProviderKeysSuccess([
                {
                    ...mockProviderKeys[0],
                    state: 'ok',
                    error_message: null,
                },
            ])

            await expectLogic(logic).toMatchValues({
                unhealthyProviderKeysUsedByEvaluations: [],
            })
        })
    })
})
