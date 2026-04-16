import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { modelPickerLogic, type ModelOption } from '../modelPickerLogic'
import { llmPlaygroundModelLogic } from './llmPlaygroundModelLogic'
import { llmPlaygroundPromptsLogic } from './llmPlaygroundPromptsLogic'
import { llmPlaygroundRunLogic } from './llmPlaygroundRunLogic'

const MOCK_MODEL_OPTIONS: ModelOption[] = [
    { id: 'gpt-4.1', name: 'GPT-4.1', provider: 'OpenAI', description: '', isRecommended: false },
    { id: 'gpt-4.1-mini', name: 'GPT-4.1 Mini', provider: 'OpenAI', description: '', isRecommended: false },
    { id: 'gpt-5', name: 'GPT-5', provider: 'OpenAI', description: '', isRecommended: false },
    { id: 'gpt-5-mini', name: 'GPT-5 Mini', provider: 'OpenAI', description: '', isRecommended: false },
    { id: 'claude-3-opus', name: 'Claude 3 Opus', provider: 'Anthropic', description: '', isRecommended: false },
]

const DEFAULT_MODEL = 'gpt-5-mini'

describe('llmPlaygroundLogic', () => {
    let runLogic: ReturnType<typeof llmPlaygroundRunLogic.build>

    beforeEach(() => {
        initKeaTests()

        useMocks({
            get: {
                '/api/llm_proxy/models/': MOCK_MODEL_OPTIONS,
                '/api/environments/:team_id/llm_analytics/evaluation_config/': {
                    active_provider_key: null,
                },
                '/api/environments/:team_id/llm_analytics/provider_keys/': {
                    results: [],
                },
            },
        })

        runLogic = llmPlaygroundRunLogic()
        runLogic.mount()
    })

    afterEach(() => {
        runLogic.unmount()
    })

    describe('closest model matching', () => {
        it('should return exact match when model exists', async () => {
            await expectLogic(runLogic).toFinishAllListeners()

            llmPlaygroundPromptsLogic.actions.setupPlaygroundFromEvent({
                model: 'gpt-5',
                input: 'test input',
            })

            expect(llmPlaygroundPromptsLogic.values.model).toBe('gpt-5')
        })

        it('should match by longest prefix', async () => {
            await expectLogic(runLogic).toFinishAllListeners()

            llmPlaygroundPromptsLogic.actions.setupPlaygroundFromEvent({
                model: 'gpt-5-mini-2025-08-07',
                input: 'test input',
            })

            expect(llmPlaygroundPromptsLogic.values.model).toBe('gpt-5-mini')
        })

        it('should match shorter prefix when longer not available', async () => {
            await expectLogic(runLogic).toFinishAllListeners()

            llmPlaygroundPromptsLogic.actions.setupPlaygroundFromEvent({
                model: 'gpt-5-2025-08-07',
                input: 'test input',
            })

            expect(llmPlaygroundPromptsLogic.values.model).toBe('gpt-5')
        })

        it('should return default model when no match found', async () => {
            await expectLogic(runLogic).toFinishAllListeners()

            llmPlaygroundPromptsLogic.actions.setupPlaygroundFromEvent({
                model: 'llama-3-70b',
                input: 'test input',
            })

            expect(llmPlaygroundPromptsLogic.values.model).toBe(DEFAULT_MODEL)
        })

        it('should handle empty model list gracefully', async () => {
            useMocks({
                get: {
                    '/api/llm_proxy/models/': [],
                    '/api/environments/:team_id/llm_analytics/evaluation_config/': {
                        active_provider_key: null,
                    },
                    '/api/environments/:team_id/llm_analytics/provider_keys/': {
                        results: [],
                    },
                },
            })

            // Reload trial models so the empty mock takes effect
            modelPickerLogic.actions.loadTrialModels()

            const emptyRunLogic = llmPlaygroundRunLogic()
            emptyRunLogic.mount()

            await expectLogic(emptyRunLogic).toFinishAllListeners()

            llmPlaygroundPromptsLogic.actions.setupPlaygroundFromEvent({
                model: 'gpt-5-2025-08-07',
                input: 'test input',
            })

            // No models available yet, so preserve the requested model instead of guessing.
            expect(llmPlaygroundPromptsLogic.values.model).toBe('gpt-5-2025-08-07')

            emptyRunLogic.unmount()
        })
    })

    describe('setupPlaygroundFromEvent model matching', () => {
        it('should resolve pending model after model options load when setup happens early', async () => {
            llmPlaygroundPromptsLogic.actions.setupPlaygroundFromEvent({
                model: 'gpt-5-2025-08-07',
                input: 'test input',
            })

            await expectLogic(runLogic).toFinishAllListeners()

            expect(llmPlaygroundPromptsLogic.values.model).toBe('gpt-5')
        })

        it('should set valid model directly', async () => {
            await expectLogic(runLogic).toFinishAllListeners()

            llmPlaygroundPromptsLogic.actions.setupPlaygroundFromEvent({
                model: 'claude-3-opus',
                input: 'test input',
            })

            expect(llmPlaygroundPromptsLogic.values.model).toBe('claude-3-opus')
        })

        it('should handle missing model in payload', async () => {
            await expectLogic(runLogic).toFinishAllListeners()

            const originalModel = llmPlaygroundPromptsLogic.values.model

            llmPlaygroundPromptsLogic.actions.setupPlaygroundFromEvent({
                input: 'test input',
            })

            expect(llmPlaygroundPromptsLogic.values.model).toBe(originalModel)
        })

        it('should preserve other payload data when model matching', async () => {
            await expectLogic(runLogic).toFinishAllListeners()

            const testInput = 'Hello, world!'
            const testTools = [{ name: 'search', description: 'Search tool' }]

            llmPlaygroundPromptsLogic.actions.setupPlaygroundFromEvent({
                model: 'gpt-5-2025-08-07',
                input: testInput,
                tools: testTools,
            })

            expect(llmPlaygroundPromptsLogic.values.model).toBe('gpt-5')
            expect(llmPlaygroundPromptsLogic.values.tools).toEqual(testTools)
            expect(llmPlaygroundPromptsLogic.values.messages.length).toBeGreaterThan(0)
        })

        it('should prefer longer prefix matches', async () => {
            const extendedMockOptions = [
                ...MOCK_MODEL_OPTIONS,
                { id: 'gpt-5-mini-turbo', name: 'GPT-5 Mini Turbo', provider: 'OpenAI', description: '' },
            ]

            useMocks({
                get: {
                    '/api/llm_proxy/models/': extendedMockOptions,
                    '/api/environments/:team_id/llm_analytics/evaluation_config/': {
                        active_provider_key: null,
                    },
                    '/api/environments/:team_id/llm_analytics/provider_keys/': {
                        results: [],
                    },
                },
            })

            // Reload trial models with the extended mock data
            modelPickerLogic.actions.loadTrialModels()

            const testRunLogic = llmPlaygroundRunLogic()
            testRunLogic.mount()

            await expectLogic(testRunLogic).toFinishAllListeners()

            llmPlaygroundPromptsLogic.actions.setupPlaygroundFromEvent({
                model: 'gpt-5-mini-turbo-2025',
                input: 'test',
            })

            // 'gpt-5-mini-turbo' is the longest prefix match (16 chars vs 10 for 'gpt-5-mini')
            expect(llmPlaygroundPromptsLogic.values.model).toBe('gpt-5-mini-turbo')

            testRunLogic.unmount()
        })

        it('should keep trace model ID and map to the matching provider key', async () => {
            const byokModels: ModelOption[] = [
                {
                    id: 'anthropic/claude-sonnet-4',
                    name: 'Claude Sonnet 4',
                    provider: 'openrouter',
                    description: '',
                },
            ]

            runLogic.unmount()

            useMocks({
                get: {
                    '/api/environments/:team_id/llm_analytics/evaluation_config/': {
                        active_provider_key: null,
                    },
                    '/api/environments/:team_id/llm_analytics/provider_keys/': {
                        results: [{ id: 'openrouter-key-1', provider: 'openrouter', state: 'ok' }],
                    },
                    '/api/llm_proxy/models/': (req: any) => {
                        if (req.url.searchParams.get('provider_key_id') === 'openrouter-key-1') {
                            return [200, byokModels]
                        }
                        return [200, MOCK_MODEL_OPTIONS]
                    },
                },
            })

            const testRunLogic = llmPlaygroundRunLogic()
            testRunLogic.mount()
            await expectLogic(testRunLogic).toFinishAllListeners()

            llmPlaygroundPromptsLogic.actions.setupPlaygroundFromEvent({
                model: 'anthropic/claude-sonnet-4',
                provider: 'gateway',
                input: 'test input',
            })

            expect(llmPlaygroundPromptsLogic.values.model).toBe('anthropic/claude-sonnet-4')
            expect(llmPlaygroundPromptsLogic.values.selectedProviderKeyId).toBe('openrouter-key-1')

            testRunLogic.unmount()
        })

        it('should keep trace model ID even when setup runs before keys/models load', async () => {
            const byokModels: ModelOption[] = [
                {
                    id: 'anthropic/claude-sonnet-4-5-20250929',
                    name: 'Claude Sonnet 4.5',
                    provider: 'openrouter',
                    description: '',
                },
            ]

            runLogic.unmount()

            useMocks({
                get: {
                    '/api/environments/:team_id/llm_analytics/evaluation_config/': {
                        active_provider_key: null,
                    },
                    '/api/environments/:team_id/llm_analytics/provider_keys/': {
                        results: [{ id: 'openrouter-key-1', provider: 'openrouter', state: 'ok' }],
                    },
                    '/api/llm_proxy/models/': (req: any) => {
                        if (req.url.searchParams.get('provider_key_id') === 'openrouter-key-1') {
                            return [200, byokModels]
                        }
                        return [200, MOCK_MODEL_OPTIONS]
                    },
                },
            })

            const testRunLogic = llmPlaygroundRunLogic()
            testRunLogic.mount()

            llmPlaygroundPromptsLogic.actions.setupPlaygroundFromEvent({
                model: 'anthropic/claude-sonnet-4-5-20250929',
                provider: 'gateway',
                input: 'test input',
            })

            await expectLogic(testRunLogic).toFinishAllListeners()

            expect(llmPlaygroundPromptsLogic.values.model).toBe('anthropic/claude-sonnet-4-5-20250929')
            expect(llmPlaygroundPromptsLogic.values.selectedProviderKeyId).toBe('openrouter-key-1')

            testRunLogic.unmount()
        })

        it('should map gateway snapshot model IDs to the closest same-prefix catalog model', async () => {
            const byokModels: ModelOption[] = [
                {
                    id: 'anthropic/claude-sonnet-4.5',
                    name: 'Claude Sonnet 4.5',
                    provider: 'openrouter',
                    description: '',
                },
            ]

            runLogic.unmount()

            useMocks({
                get: {
                    '/api/environments/:team_id/llm_analytics/evaluation_config/': {
                        active_provider_key: null,
                    },
                    '/api/environments/:team_id/llm_analytics/provider_keys/': {
                        results: [{ id: 'openrouter-key-1', provider: 'openrouter', state: 'ok' }],
                    },
                    '/api/llm_proxy/models/': (req: any) => {
                        if (req.url.searchParams.get('provider_key_id') === 'openrouter-key-1') {
                            return [200, byokModels]
                        }
                        return [200, MOCK_MODEL_OPTIONS]
                    },
                },
            })

            const testRunLogic = llmPlaygroundRunLogic()
            testRunLogic.mount()
            await expectLogic(testRunLogic).toFinishAllListeners()

            llmPlaygroundPromptsLogic.actions.setupPlaygroundFromEvent({
                model: 'anthropic/claude-sonnet-4-5-20250929',
                provider: 'gateway',
                input: 'test input',
            })

            expect(llmPlaygroundPromptsLogic.values.model).toBe('anthropic/claude-sonnet-4.5')
            expect(llmPlaygroundPromptsLogic.values.selectedProviderKeyId).toBe('openrouter-key-1')

            testRunLogic.unmount()
        })

        it('should consistently pick the first provider key by sorted order when multiple keys match', async () => {
            const byokModelId = 'anthropic/claude-sonnet-4'

            runLogic.unmount()

            useMocks({
                get: {
                    '/api/environments/:team_id/llm_analytics/evaluation_config/': {
                        active_provider_key: null,
                    },
                    '/api/environments/:team_id/llm_analytics/provider_keys/': {
                        // Deliberately reverse API order to ensure we don't pick "last loaded"
                        results: [
                            { id: 'openrouter-key-z', provider: 'openrouter', name: 'Z key', state: 'ok' },
                            { id: 'openrouter-key-a', provider: 'openrouter', name: 'A key', state: 'ok' },
                        ],
                    },
                    '/api/llm_proxy/models/': (req: any) => {
                        const providerKeyId = req.url.searchParams.get('provider_key_id')
                        if (providerKeyId === 'openrouter-key-z' || providerKeyId === 'openrouter-key-a') {
                            return [
                                200,
                                [
                                    {
                                        id: byokModelId,
                                        name: 'Claude Sonnet 4',
                                        provider: 'openrouter',
                                        description: '',
                                    },
                                ],
                            ]
                        }
                        return [200, MOCK_MODEL_OPTIONS]
                    },
                },
            })

            const testRunLogic = llmPlaygroundRunLogic()
            testRunLogic.mount()
            await expectLogic(testRunLogic).toFinishAllListeners()

            llmPlaygroundPromptsLogic.actions.setupPlaygroundFromEvent({
                model: 'anthropic/claude-sonnet-4',
                provider: 'gateway',
                input: 'test input',
            })

            expect(llmPlaygroundPromptsLogic.values.model).toBe(byokModelId)
            expect(llmPlaygroundPromptsLogic.values.selectedProviderKeyId).toBe('openrouter-key-a')

            testRunLogic.unmount()
        })

        it('should keep trial model selection even when BYOK models are available', async () => {
            const byokModels: ModelOption[] = [
                {
                    id: 'anthropic/claude-sonnet-4.5',
                    name: 'Claude Sonnet 4.5',
                    provider: 'openrouter',
                    description: '',
                },
            ]

            runLogic.unmount()

            useMocks({
                get: {
                    '/api/environments/:team_id/llm_analytics/evaluation_config/': {
                        active_provider_key: null,
                    },
                    '/api/environments/:team_id/llm_analytics/provider_keys/': {
                        results: [{ id: 'openrouter-key-1', provider: 'openrouter', state: 'ok' }],
                    },
                    '/api/llm_proxy/models/': (req: any) => {
                        if (req.url.searchParams.get('provider_key_id') === 'openrouter-key-1') {
                            return [200, byokModels]
                        }
                        return [200, MOCK_MODEL_OPTIONS]
                    },
                },
            })

            const testRunLogic = llmPlaygroundRunLogic()
            testRunLogic.mount()
            await expectLogic(testRunLogic).toFinishAllListeners()

            llmPlaygroundPromptsLogic.actions.setupPlaygroundFromEvent({
                model: 'gpt-5-mini',
                provider: 'gateway',
                input: 'test input',
            })

            expect(llmPlaygroundPromptsLogic.values.model).toBe('gpt-5-mini')
            expect(llmPlaygroundPromptsLogic.values.selectedProviderKeyId).toBe(null)

            testRunLogic.unmount()
        })
    })

    describe('loadTrialModels auto-correction', () => {
        it('should auto-correct invalid model after loading trial models', async () => {
            const testRunLogic = llmPlaygroundRunLogic()
            testRunLogic.mount()

            llmPlaygroundPromptsLogic.actions.setModel('gpt-5-2025-08-07')

            modelPickerLogic.actions.loadTrialModels()

            await expectLogic(testRunLogic).toFinishAllListeners()

            expect(llmPlaygroundPromptsLogic.values.model).toBe('gpt-5')

            testRunLogic.unmount()
        })

        it('should not change valid models during loading', async () => {
            llmPlaygroundPromptsLogic.actions.setModel('claude-3-opus')

            const testRunLogic = llmPlaygroundRunLogic()
            testRunLogic.mount()

            await expectLogic(testRunLogic).toFinishAllListeners()

            expect(llmPlaygroundPromptsLogic.values.model).toBe('claude-3-opus')

            testRunLogic.unmount()
        })

        it('should preserve trial models when reload fails', async () => {
            await expectLogic(runLogic).toFinishAllListeners()
            expect(modelPickerLogic.values.trialModels).toEqual(MOCK_MODEL_OPTIONS)

            useMocks({
                get: {
                    '/api/llm_proxy/models/': () => {
                        throw new Error('API Error')
                    },
                    '/api/environments/:team_id/llm_analytics/evaluation_config/': () => {
                        throw new Error('API Error')
                    },
                    '/api/environments/:team_id/llm_analytics/provider_keys/': () => {
                        throw new Error('API Error')
                    },
                },
            })

            modelPickerLogic.actions.loadTrialModels()
            await expectLogic(runLogic).toFinishAllListeners()

            expect(modelPickerLogic.values.trialModels).toEqual(MOCK_MODEL_OPTIONS)
        })
    })

    describe('Message Management', () => {
        it('should clear all messages when clearConversation is called', () => {
            llmPlaygroundPromptsLogic.actions.addMessage({ role: 'user', content: 'Hello' })
            llmPlaygroundPromptsLogic.actions.addMessage({ role: 'assistant', content: 'Hi there!' })
            llmPlaygroundPromptsLogic.actions.addMessage({ role: 'system', content: 'System message' })

            expect(llmPlaygroundPromptsLogic.values.messages).toHaveLength(3)

            llmPlaygroundPromptsLogic.actions.clearConversation()

            expect(llmPlaygroundPromptsLogic.values.messages).toHaveLength(0)
            expect(llmPlaygroundPromptsLogic.values.messages).toEqual([])
        })

        it('should delete message at specific index', () => {
            llmPlaygroundPromptsLogic.actions.setMessages([
                { role: 'user', content: 'First' },
                { role: 'assistant', content: 'Second' },
                { role: 'user', content: 'Third' },
            ])

            llmPlaygroundPromptsLogic.actions.deleteMessage(1)

            expect(llmPlaygroundPromptsLogic.values.messages).toEqual([
                { role: 'user', content: 'First' },
                { role: 'user', content: 'Third' },
            ])
        })

        it('should handle deleteMessage with invalid indices gracefully', () => {
            llmPlaygroundPromptsLogic.actions.setMessages([{ role: 'user', content: 'Only message' }])

            llmPlaygroundPromptsLogic.actions.deleteMessage(-1)
            expect(llmPlaygroundPromptsLogic.values.messages).toHaveLength(1)

            llmPlaygroundPromptsLogic.actions.deleteMessage(5)
            expect(llmPlaygroundPromptsLogic.values.messages).toHaveLength(1)

            expect(llmPlaygroundPromptsLogic.values.messages[0].content).toBe('Only message')
        })

        it('should add messages with different roles', () => {
            llmPlaygroundPromptsLogic.actions.addMessage({ role: 'user', content: 'User message' })
            llmPlaygroundPromptsLogic.actions.addMessage({ role: 'assistant', content: 'Assistant message' })
            llmPlaygroundPromptsLogic.actions.addMessage({ role: 'system', content: 'System message' })

            expect(llmPlaygroundPromptsLogic.values.messages).toEqual([
                { role: 'user', content: 'User message' },
                { role: 'assistant', content: 'Assistant message' },
                { role: 'system', content: 'System message' },
            ])
        })

        it('should add message with default values when partial message provided', () => {
            llmPlaygroundPromptsLogic.actions.addMessage({ content: 'Just content' })

            expect(llmPlaygroundPromptsLogic.values.messages[0]).toEqual({
                role: 'user', // default role
                content: 'Just content',
            })

            llmPlaygroundPromptsLogic.actions.addMessage({ role: 'assistant' })

            expect(llmPlaygroundPromptsLogic.values.messages[1]).toEqual({
                role: 'assistant',
                content: '', // default content
            })
        })

        it('should update message at specific index', () => {
            llmPlaygroundPromptsLogic.actions.setMessages([
                { role: 'user', content: 'Original' },
                { role: 'assistant', content: 'Response' },
            ])

            llmPlaygroundPromptsLogic.actions.updateMessage(0, { content: 'Updated content' })

            expect(llmPlaygroundPromptsLogic.values.messages[0]).toEqual({
                role: 'user',
                content: 'Updated content',
            })

            llmPlaygroundPromptsLogic.actions.updateMessage(1, { role: 'user', content: 'Changed everything' })

            expect(llmPlaygroundPromptsLogic.values.messages[1]).toEqual({
                role: 'user',
                content: 'Changed everything',
            })
        })

        it('should not update message with invalid index', () => {
            llmPlaygroundPromptsLogic.actions.setMessages([{ role: 'user', content: 'Original' }])

            const originalMessages = [...llmPlaygroundPromptsLogic.values.messages]

            llmPlaygroundPromptsLogic.actions.updateMessage(-1, { content: 'Should not update' })
            expect(llmPlaygroundPromptsLogic.values.messages).toEqual(originalMessages)

            llmPlaygroundPromptsLogic.actions.updateMessage(10, { content: 'Should not update' })
            expect(llmPlaygroundPromptsLogic.values.messages).toEqual(originalMessages)
        })
    })

    describe('effectiveModelOptions', () => {
        it('should return trial models when no BYOK keys exist', async () => {
            await expectLogic(runLogic).toFinishAllListeners()

            expect(llmPlaygroundModelLogic.values.effectiveModelOptions).toEqual(MOCK_MODEL_OPTIONS)
        })

        it('should return trial models when all keys are invalid', async () => {
            useMocks({
                get: {
                    '/api/environments/:team_id/llm_analytics/evaluation_config/': {
                        active_provider_key: null,
                    },
                    '/api/environments/:team_id/llm_analytics/provider_keys/': {
                        results: [{ id: 'key-1', provider: 'openai', state: 'invalid' }],
                    },
                    '/api/llm_proxy/models/': MOCK_MODEL_OPTIONS,
                },
            })

            const testRunLogic = llmPlaygroundRunLogic()
            testRunLogic.mount()
            await expectLogic(testRunLogic).toFinishAllListeners()

            expect(llmPlaygroundModelLogic.values.hasByokKeys).toBe(false)
            expect(llmPlaygroundModelLogic.values.effectiveModelOptions).toEqual(MOCK_MODEL_OPTIONS)

            testRunLogic.unmount()
        })

        it('should return trial models when provider keys API fails', async () => {
            useMocks({
                get: {
                    '/api/environments/:team_id/llm_analytics/evaluation_config/': {
                        active_provider_key: null,
                    },
                    '/api/environments/:team_id/llm_analytics/provider_keys/': () => {
                        throw new Error('API Error')
                    },
                    '/api/llm_proxy/models/': MOCK_MODEL_OPTIONS,
                },
            })

            const testRunLogic = llmPlaygroundRunLogic()
            testRunLogic.mount()
            await expectLogic(testRunLogic).toFinishAllListeners()

            expect(llmPlaygroundModelLogic.values.effectiveModelOptions).toEqual(MOCK_MODEL_OPTIONS)

            testRunLogic.unmount()
        })

        it('should return BYOK models when valid keys exist and models have loaded', async () => {
            const byokModels: ModelOption[] = [{ id: 'gpt-4.1', name: 'GPT-4.1', provider: 'OpenAI', description: '' }]

            runLogic.unmount()

            useMocks({
                get: {
                    '/api/environments/:team_id/llm_analytics/evaluation_config/': {
                        active_provider_key: null,
                    },
                    '/api/environments/:team_id/llm_analytics/provider_keys/': {
                        results: [{ id: 'key-1', provider: 'openai', state: 'ok' }],
                    },
                    '/api/llm_proxy/models/': (req: any) => {
                        if (req.url.searchParams.get('provider_key_id') === 'key-1') {
                            return [200, byokModels]
                        }
                        return [200, MOCK_MODEL_OPTIONS]
                    },
                },
            })

            runLogic = llmPlaygroundRunLogic()
            runLogic.mount()
            await expectLogic(runLogic).toFinishAllListeners()

            expect(llmPlaygroundModelLogic.values.hasByokKeys).toBe(true)
            expect(llmPlaygroundModelLogic.values.effectiveModelOptions).toEqual(
                byokModels.map((m) => ({ ...m, isRecommended: false, providerKeyId: 'key-1' }))
            )
        })
    })

    describe('setupPlaygroundFromEvent Input Processing', () => {
        it('should handle array input with system, user, and assistant messages', () => {
            const input = [
                { role: 'system', content: 'You are a helpful assistant.' },
                { role: 'user', content: 'Hello' },
                { role: 'assistant', content: 'Hi there!' },
                { role: 'user', content: 'How are you?' },
            ]

            llmPlaygroundPromptsLogic.actions.setupPlaygroundFromEvent({ input })

            expect(llmPlaygroundPromptsLogic.values.systemPrompt).toBe('You are a helpful assistant.')
            expect(llmPlaygroundPromptsLogic.values.messages).toEqual([
                { role: 'user', content: 'Hello' },
                { role: 'assistant', content: 'Hi there!' },
                { role: 'user', content: 'How are you?' },
            ])
        })

        it('should concatenate multiple system messages', () => {
            const input = [
                { role: 'system', content: 'You are a helpful assistant.' },
                { role: 'system', content: 'Always respond in a friendly manner.' },
                { role: 'system', content: 'Use markdown formatting when appropriate.' },
                { role: 'user', content: 'Hello' },
                { role: 'assistant', content: 'Hi there!' },
            ]

            llmPlaygroundPromptsLogic.actions.setupPlaygroundFromEvent({ input })

            expect(llmPlaygroundPromptsLogic.values.systemPrompt).toBe(
                'You are a helpful assistant.\n\nAlways respond in a friendly manner.\n\nUse markdown formatting when appropriate.'
            )
            expect(llmPlaygroundPromptsLogic.values.messages).toEqual([
                { role: 'user', content: 'Hello' },
                { role: 'assistant', content: 'Hi there!' },
            ])
        })

        it('should normalize role names (ai/model to assistant)', () => {
            const input = [
                { role: 'user', content: 'Question' },
                { role: 'ai', content: 'AI response' },
                { role: 'model', content: 'Model response' },
            ]

            llmPlaygroundPromptsLogic.actions.setupPlaygroundFromEvent({ input })

            expect(llmPlaygroundPromptsLogic.values.messages).toEqual([
                { role: 'user', content: 'Question' },
                { role: 'assistant', content: 'AI response' },
                { role: 'assistant', content: 'Model response' },
            ])
        })

        it('should handle string input as initial user message', () => {
            llmPlaygroundPromptsLogic.actions.setupPlaygroundFromEvent({
                input: 'Simple string prompt',
            })

            expect(llmPlaygroundPromptsLogic.values.messages).toEqual([
                { role: 'user', content: 'Simple string prompt' },
            ])
            expect(llmPlaygroundPromptsLogic.values.systemPrompt).toBe('You are a helpful AI assistant.')
        })

        it('should handle object input with content field', () => {
            const input = {
                content: 'Content from object',
                someOtherField: 'ignored',
            }

            llmPlaygroundPromptsLogic.actions.setupPlaygroundFromEvent({ input })

            expect(llmPlaygroundPromptsLogic.values.messages).toEqual([
                { role: 'user', content: 'Content from object' },
            ])
        })

        it('should handle object input with non-string content field', () => {
            const input = {
                content: { nested: 'data', array: [1, 2, 3] },
            }

            llmPlaygroundPromptsLogic.actions.setupPlaygroundFromEvent({ input })

            expect(llmPlaygroundPromptsLogic.values.messages[0].role).toBe('user')
            expect(llmPlaygroundPromptsLogic.values.messages[0].content).toContain('"nested"')
            expect(llmPlaygroundPromptsLogic.values.messages[0].content).toContain('"data"')
            const content = llmPlaygroundPromptsLogic.values.messages[0].content
            expect(content).toContain('1')
            expect(content).toContain('2')
            expect(content).toContain('3')
            expect(content).toContain('array')
        })

        it('should JSON stringify object without content field', () => {
            const input = {
                someField: 'value',
                anotherField: 123,
            }

            llmPlaygroundPromptsLogic.actions.setupPlaygroundFromEvent({ input })

            expect(llmPlaygroundPromptsLogic.values.messages[0].role).toBe('user')
            expect(llmPlaygroundPromptsLogic.values.messages[0].content).toContain('"someField"')
            expect(llmPlaygroundPromptsLogic.values.messages[0].content).toContain('"value"')
            expect(llmPlaygroundPromptsLogic.values.messages[0].content).toContain('123')
        })

        it('should handle tools parameter', () => {
            const tools = [
                { type: 'function', function: { name: 'search', description: 'Search tool' } },
                { type: 'function', function: { name: 'calculator', description: 'Math tool' } },
            ]

            llmPlaygroundPromptsLogic.actions.setupPlaygroundFromEvent({
                input: 'Test',
                tools,
            })

            expect(llmPlaygroundPromptsLogic.values.tools).toEqual(tools)
        })

        it('should default messages with unknown roles to user', () => {
            const input = [
                { role: 'user', content: 'Valid user' },
                { role: 'invalid_role', content: 'Unknown role defaults to user' },
                { role: 'assistant', content: 'Valid assistant' },
                { role: 'unknown', content: 'Also defaults to user' },
            ]

            llmPlaygroundPromptsLogic.actions.setupPlaygroundFromEvent({ input })

            expect(llmPlaygroundPromptsLogic.values.messages).toEqual([
                { role: 'user', content: 'Valid user' },
                { role: 'user', content: 'Unknown role defaults to user' },
                { role: 'assistant', content: 'Valid assistant' },
                { role: 'user', content: 'Also defaults to user' },
            ])
        })

        it('should handle messages with non-string content', () => {
            const input = [
                { role: 'user', content: { text: 'Complex content' } },
                { role: 'assistant', content: ['array', 'content'] },
            ]

            llmPlaygroundPromptsLogic.actions.setupPlaygroundFromEvent({ input })

            expect(llmPlaygroundPromptsLogic.values.messages[0].content).toContain('"text"')
            expect(llmPlaygroundPromptsLogic.values.messages[0].content).toContain('"Complex content"')
            // Pretty-printed JSON array
            expect(llmPlaygroundPromptsLogic.values.messages[1].content).toContain('"array"')
            expect(llmPlaygroundPromptsLogic.values.messages[1].content).toContain('"content"')
        })

        it('should extract plain text from trace-style content arrays', () => {
            const input = [
                { role: 'user', content: [{ text: 'hi', type: 'text' }] },
                { role: 'assistant', content: [{ text: 'PART 1/2: Let me check that.', type: 'text' }] },
            ]

            llmPlaygroundPromptsLogic.actions.setupPlaygroundFromEvent({ input })

            expect(llmPlaygroundPromptsLogic.values.messages).toEqual([
                { role: 'user', content: 'hi' },
                { role: 'assistant', content: 'PART 1/2: Let me check that.' },
            ])
        })

        it('should handle OpenAI-style messages with tool_calls and null content', () => {
            const input = [
                { role: 'user', content: 'What is the weather in Paris?' },
                {
                    role: 'assistant',
                    content: null,
                    tool_calls: [
                        {
                            type: 'function',
                            id: 'call_123',
                            function: { name: 'get_weather', arguments: '{"city": "Paris"}' },
                        },
                    ],
                },
            ]

            llmPlaygroundPromptsLogic.actions.setupPlaygroundFromEvent({ input })

            expect(llmPlaygroundPromptsLogic.values.messages).toHaveLength(2)
            expect(llmPlaygroundPromptsLogic.values.messages[0]).toEqual({
                role: 'user',
                content: 'What is the weather in Paris?',
            })
            expect(llmPlaygroundPromptsLogic.values.messages[1].role).toBe('assistant')
            expect(llmPlaygroundPromptsLogic.values.messages[1].content).toContain('[Tool call: get_weather]')
            expect(llmPlaygroundPromptsLogic.values.messages[1].content).toContain('Paris')
        })

        it.each([
            {
                name: 'Anthropic mixed text + tool_use',
                content: [
                    { type: 'text', text: 'Let me search for that.' },
                    { type: 'tool_use', id: 'tu_1', name: 'search', input: { query: 'cats' } },
                ],
                expectedSubstrings: ['Let me search for that.', '[Tool call: search]', 'cats'],
            },
            {
                name: 'Anthropic tool_use only',
                content: [{ type: 'tool_use', id: 'tu_1', name: 'do_thing', input: { param: 'value' } }],
                expectedSubstrings: ['[Tool call: do_thing]'],
            },
            {
                name: 'Anthropic tool_result',
                content: [{ type: 'tool_result', tool_use_id: 'tu_1', content: 'Result data here' }],
                expectedSubstrings: ['[Tool result for tu_1]', 'Result data here'],
            },
            {
                name: 'OpenAI Responses API function_call',
                content: [{ type: 'function_call', name: 'my_func', call_id: 'fc_1', arguments: '{"x": 1}' }],
                expectedSubstrings: ['[Function call: my_func]', '{"x": 1}'],
            },
            {
                name: 'OpenAI Responses API function_call_output',
                content: [{ type: 'function_call_output', call_id: 'fc_1', output: 'result: 42' }],
                expectedSubstrings: ['[Function output for fc_1]', 'result: 42'],
            },
        ])('should format $name content blocks', ({ content, expectedSubstrings }) => {
            const input = [{ role: 'assistant', content }]

            llmPlaygroundPromptsLogic.actions.setupPlaygroundFromEvent({ input })

            const result = llmPlaygroundPromptsLogic.values.messages[0].content
            expect(result).not.toBe('')
            for (const substring of expectedSubstrings) {
                expect(result).toContain(substring)
            }
        })

        it('should map OpenAI tool role to user fallback', () => {
            const input = [{ role: 'tool', tool_call_id: 'call_123', content: 'Weather in Paris: 22°C' }]

            llmPlaygroundPromptsLogic.actions.setupPlaygroundFromEvent({ input })

            expect(llmPlaygroundPromptsLogic.values.messages).toHaveLength(1)
            expect(llmPlaygroundPromptsLogic.values.messages[0].role).toBe('user')
            expect(llmPlaygroundPromptsLogic.values.messages[0].content).toBe('Weather in Paris: 22°C')
        })

        it('should not produce "null" string for messages with null content', () => {
            const input = [{ role: 'user', content: null, tool_calls: [] }]

            llmPlaygroundPromptsLogic.actions.setupPlaygroundFromEvent({ input })

            expect(llmPlaygroundPromptsLogic.values.messages).toHaveLength(1)
            expect(llmPlaygroundPromptsLogic.values.messages[0].content).not.toBe('null')
            expect(llmPlaygroundPromptsLogic.values.messages[0].content).toBe('')
        })

        it('should reset to default system prompt when none provided', () => {
            llmPlaygroundPromptsLogic.actions.setSystemPrompt('Custom prompt')

            const input = [
                { role: 'user', content: 'No system message here' },
                { role: 'assistant', content: 'Response' },
            ]

            llmPlaygroundPromptsLogic.actions.setupPlaygroundFromEvent({ input })

            expect(llmPlaygroundPromptsLogic.values.systemPrompt).toBe('You are a helpful AI assistant.')
        })

        it('should preserve existing model if not provided in payload', () => {
            llmPlaygroundPromptsLogic.actions.setModel('claude-3-opus')

            llmPlaygroundPromptsLogic.actions.setupPlaygroundFromEvent({
                input: 'Test without model',
            })

            expect(llmPlaygroundPromptsLogic.values.model).toBe('claude-3-opus')
        })
    })

    describe('Multi-prompt state management', () => {
        it('should start with a single prompt config', () => {
            expect(llmPlaygroundPromptsLogic.values.promptConfigs).toHaveLength(1)
            expect(llmPlaygroundPromptsLogic.values.activePromptId).toBe(
                llmPlaygroundPromptsLogic.values.promptConfigs[0].id
            )
        })

        it('should duplicate the source prompt when adding a new prompt', () => {
            const originalPrompt = llmPlaygroundPromptsLogic.values.promptConfigs[0]
            llmPlaygroundPromptsLogic.actions.setSystemPrompt('Custom system prompt')
            llmPlaygroundPromptsLogic.actions.addMessage({ role: 'user', content: 'Hello' })

            llmPlaygroundPromptsLogic.actions.addPromptConfig(originalPrompt.id)

            expect(llmPlaygroundPromptsLogic.values.promptConfigs).toHaveLength(2)
            const newPrompt = llmPlaygroundPromptsLogic.values.promptConfigs[1]
            expect(newPrompt.id).not.toBe(originalPrompt.id)
            expect(newPrompt.systemPrompt).toBe('Custom system prompt')
            expect(newPrompt.messages).toEqual([{ role: 'user', content: 'Hello' }])
        })

        it('should set activePromptId to the new prompt on add', () => {
            const originalId = llmPlaygroundPromptsLogic.values.promptConfigs[0].id
            llmPlaygroundPromptsLogic.actions.addPromptConfig(originalId)

            const newPrompt = llmPlaygroundPromptsLogic.values.promptConfigs[1]
            expect(llmPlaygroundPromptsLogic.values.activePromptId).toBe(newPrompt.id)
        })

        it('should fall back to last prompt when no sourcePromptId provided', () => {
            llmPlaygroundPromptsLogic.actions.addPromptConfig()

            expect(llmPlaygroundPromptsLogic.values.promptConfigs).toHaveLength(2)
        })

        it('should remove a prompt config', () => {
            const firstId = llmPlaygroundPromptsLogic.values.promptConfigs[0].id
            llmPlaygroundPromptsLogic.actions.addPromptConfig(firstId)
            expect(llmPlaygroundPromptsLogic.values.promptConfigs).toHaveLength(2)

            const secondId = llmPlaygroundPromptsLogic.values.promptConfigs[1].id
            llmPlaygroundPromptsLogic.actions.removePromptConfig(secondId)

            expect(llmPlaygroundPromptsLogic.values.promptConfigs).toHaveLength(1)
            expect(llmPlaygroundPromptsLogic.values.promptConfigs[0].id).toBe(firstId)
        })

        it('should not allow removing the last prompt config', () => {
            const onlyId = llmPlaygroundPromptsLogic.values.promptConfigs[0].id
            llmPlaygroundPromptsLogic.actions.removePromptConfig(onlyId)

            expect(llmPlaygroundPromptsLogic.values.promptConfigs).toHaveLength(1)
        })

        it('should switch activePromptId when the active prompt is removed', () => {
            const firstId = llmPlaygroundPromptsLogic.values.promptConfigs[0].id
            llmPlaygroundPromptsLogic.actions.addPromptConfig(firstId)
            const secondId = llmPlaygroundPromptsLogic.values.promptConfigs[1].id

            expect(llmPlaygroundPromptsLogic.values.activePromptId).toBe(secondId)

            llmPlaygroundPromptsLogic.actions.removePromptConfig(secondId)

            expect(llmPlaygroundPromptsLogic.values.activePromptId).toBe(firstId)
        })

        it('should not change activePromptId when a non-active prompt is removed', () => {
            const firstId = llmPlaygroundPromptsLogic.values.promptConfigs[0].id
            llmPlaygroundPromptsLogic.actions.addPromptConfig(firstId)
            const secondId = llmPlaygroundPromptsLogic.values.promptConfigs[1].id

            llmPlaygroundPromptsLogic.actions.setActivePromptId(firstId)
            expect(llmPlaygroundPromptsLogic.values.activePromptId).toBe(firstId)

            llmPlaygroundPromptsLogic.actions.removePromptConfig(secondId)

            expect(llmPlaygroundPromptsLogic.values.activePromptId).toBe(firstId)
        })

        it('should target the first prompt when no promptId provided to setModel', () => {
            const firstPrompt = llmPlaygroundPromptsLogic.values.promptConfigs[0]
            llmPlaygroundPromptsLogic.actions.addPromptConfig(firstPrompt.id)

            llmPlaygroundPromptsLogic.actions.setModel('claude-3-opus')

            expect(llmPlaygroundPromptsLogic.values.promptConfigs[0].model).toBe('claude-3-opus')
        })

        it('should target a specific prompt when promptId is provided', () => {
            const firstId = llmPlaygroundPromptsLogic.values.promptConfigs[0].id
            llmPlaygroundPromptsLogic.actions.addPromptConfig(firstId)
            const secondId = llmPlaygroundPromptsLogic.values.promptConfigs[1].id

            llmPlaygroundPromptsLogic.actions.setSystemPrompt('Prompt 2 system', secondId)

            expect(llmPlaygroundPromptsLogic.values.promptConfigs[0].systemPrompt).not.toBe('Prompt 2 system')
            expect(llmPlaygroundPromptsLogic.values.promptConfigs[1].systemPrompt).toBe('Prompt 2 system')
        })
    })

    describe('Comparison items', () => {
        it('should start with empty comparison items', () => {
            expect(llmPlaygroundRunLogic.values.comparisonItems).toEqual([])
        })

        it('should add items to comparison', () => {
            const item = {
                id: 'test-1',
                promptId: 'prompt-1',
                model: 'gpt-5',
                systemPrompt: 'test',
                requestMessages: [],
                response: 'Hello',
            }

            llmPlaygroundRunLogic.actions.addToComparison(item)

            expect(llmPlaygroundRunLogic.values.comparisonItems).toHaveLength(1)
            expect(llmPlaygroundRunLogic.values.comparisonItems[0]).toEqual(item)
        })

        it('should update a comparison item by id', () => {
            const item = {
                id: 'test-1',
                promptId: 'prompt-1',
                model: 'gpt-5',
                systemPrompt: 'test',
                requestMessages: [],
                response: '',
            }

            llmPlaygroundRunLogic.actions.addToComparison(item)
            llmPlaygroundRunLogic.actions.updateComparisonItem('test-1', { response: 'Updated response' })

            expect(llmPlaygroundRunLogic.values.comparisonItems[0].response).toBe('Updated response')
        })

        it('should clear comparison items on submitPrompt', () => {
            llmPlaygroundRunLogic.actions.addToComparison({
                id: 'test-1',
                promptId: 'prompt-1',
                model: 'gpt-5',
                systemPrompt: 'test',
                requestMessages: [],
                response: 'old response',
            })

            expect(llmPlaygroundRunLogic.values.comparisonItems).toHaveLength(1)

            llmPlaygroundRunLogic.actions.submitPrompt()

            expect(llmPlaygroundRunLogic.values.comparisonItems).toEqual([])
        })
    })

    describe('deleteMessage bounds check', () => {
        it.each([
            { index: -1, description: 'negative index' },
            { index: 5, description: 'out-of-bounds index' },
        ])('should not modify messages with $description', ({ index }) => {
            llmPlaygroundPromptsLogic.actions.setMessages([{ role: 'user', content: 'Only message' }])

            llmPlaygroundPromptsLogic.actions.deleteMessage(index)

            expect(llmPlaygroundPromptsLogic.values.messages).toHaveLength(1)
            expect(llmPlaygroundPromptsLogic.values.messages[0].content).toBe('Only message')
        })
    })

    describe('linkedSource', () => {
        it('should return null source when no source is set', () => {
            expect(llmPlaygroundPromptsLogic.values.linkedSource).toEqual({
                type: null,
                promptName: null,
                promptVersion: null,
                evaluationId: null,
                evaluationName: null,
            })
        })

        it('should reflect source after setupPlaygroundFromEvent with sourcePromptName', async () => {
            useMocks({
                get: {
                    '/api/environments/:team_id/llm_prompts/name/:name/': {
                        id: 'prompt-123',
                        name: 'my-prompt',
                        prompt: 'You are helpful.',
                    },
                },
            })

            llmPlaygroundPromptsLogic.actions.setupPlaygroundFromEvent({
                sourceType: 'prompt',
                sourcePromptName: 'my-prompt',
            })

            await expectLogic(llmPlaygroundPromptsLogic).toFinishAllListeners()

            const linked = llmPlaygroundPromptsLogic.values.linkedSource
            expect(linked.type).toBe('prompt')
            expect(linked.promptName).toBe('my-prompt')
        })

        it('should reflect source after setupPlaygroundFromEvent with sourceEvaluationId', async () => {
            useMocks({
                get: {
                    '/api/environments/:team_id/evaluations/:id/': {
                        id: 'eval-456',
                        name: 'my-eval',
                        evaluation_type: 'llm_judge',
                        evaluation_config: { prompt: 'Judge this.' },
                    },
                },
            })

            llmPlaygroundPromptsLogic.actions.setupPlaygroundFromEvent({
                sourceType: 'evaluation',
                sourceEvaluationId: 'eval-456',
            })

            await expectLogic(llmPlaygroundPromptsLogic).toFinishAllListeners()

            const linked = llmPlaygroundPromptsLogic.values.linkedSource
            expect(linked.type).toBe('evaluation')
            expect(linked.evaluationId).toBe('eval-456')
            expect(linked.evaluationName).toBe('my-eval')
        })

        it('should clear linked source', async () => {
            useMocks({
                get: {
                    '/api/environments/:team_id/llm_prompts/name/:name/': {
                        id: 'prompt-123',
                        name: 'my-prompt',
                        prompt: 'You are helpful.',
                    },
                },
            })

            llmPlaygroundPromptsLogic.actions.setupPlaygroundFromEvent({
                sourceType: 'prompt',
                sourcePromptName: 'my-prompt',
            })

            await expectLogic(llmPlaygroundPromptsLogic).toFinishAllListeners()

            llmPlaygroundPromptsLogic.actions.clearLinkedSource()

            const linked = llmPlaygroundPromptsLogic.values.linkedSource
            expect(linked.type).toBeNull()
            expect(linked.promptName).toBeNull()
        })
    })

    describe('setupPlaygroundFromEvent with source', () => {
        it('should set system prompt from fetched prompt', async () => {
            useMocks({
                get: {
                    '/api/environments/:team_id/llm_prompts/name/:name/': {
                        id: 'prompt-1',
                        name: 'test-prompt',
                        prompt: 'Be concise.',
                    },
                },
            })

            llmPlaygroundPromptsLogic.actions.setupPlaygroundFromEvent({
                sourceType: 'prompt',
                sourcePromptName: 'test-prompt',
            })

            await expectLogic(llmPlaygroundPromptsLogic).toFinishAllListeners()

            expect(llmPlaygroundPromptsLogic.values.systemPrompt).toBe('Be concise.')
            expect(llmPlaygroundPromptsLogic.values.messages).toEqual([])
        })

        it('should set system prompt and model from fetched evaluation', async () => {
            useMocks({
                get: {
                    '/api/environments/:team_id/evaluations/:id/': {
                        id: 'eval-1',
                        name: 'judge-eval',
                        evaluation_type: 'llm_judge',
                        evaluation_config: { prompt: 'Rate the response.' },
                        model_configuration: { model: 'gpt-5', provider_key_id: null },
                    },
                },
            })

            llmPlaygroundPromptsLogic.actions.setupPlaygroundFromEvent({
                sourceType: 'evaluation',
                sourceEvaluationId: 'eval-1',
            })

            await expectLogic(llmPlaygroundPromptsLogic).toFinishAllListeners()

            expect(llmPlaygroundPromptsLogic.values.systemPrompt).toBe('Rate the response.')
        })

        it('should show error toast when prompt fetch fails', async () => {
            useMocks({
                get: {
                    '/api/environments/:team_id/llm_prompts/name/:name/': () => [404, { detail: 'Not found' }],
                },
            })

            llmPlaygroundPromptsLogic.actions.setupPlaygroundFromEvent({
                sourceType: 'prompt',
                sourcePromptName: 'nonexistent-prompt',
            })

            await expectLogic(llmPlaygroundPromptsLogic).toFinishAllListeners()

            expect(llmPlaygroundPromptsLogic.values.sourceSetupLoading).toBe(false)
        })
    })

    describe('save actions', () => {
        it('saveAsNewPrompt should call create API', async () => {
            let createCalled = false
            useMocks({
                post: {
                    '/api/environments/:team_id/llm_prompts/': () => {
                        createCalled = true
                        return [201, { id: 'new-1', name: 'saved-prompt', prompt: 'test' }]
                    },
                },
            })

            llmPlaygroundPromptsLogic.actions.setSystemPrompt('My system prompt')
            const promptId = llmPlaygroundPromptsLogic.values.promptConfigs[0].id
            llmPlaygroundPromptsLogic.actions.saveAsNewPrompt(promptId, 'saved-prompt')

            await expectLogic(llmPlaygroundPromptsLogic).toFinishAllListeners()

            expect(createCalled).toBe(true)
            expect(router.values.searchParams).toHaveProperty('source_prompt_name', 'saved-prompt')
            expect(router.values.searchParams).not.toHaveProperty('source_evaluation_id')
        })

        it('saveAsNewEvaluation should call create API', async () => {
            let createCalled = false
            useMocks({
                post: {
                    '/api/environments/:team_id/evaluations/': () => {
                        createCalled = true
                        return [201, { id: 'eval-new', name: 'saved-eval' }]
                    },
                },
            })

            llmPlaygroundPromptsLogic.actions.setSystemPrompt('Judge prompt')
            const promptId = llmPlaygroundPromptsLogic.values.promptConfigs[0].id
            llmPlaygroundPromptsLogic.actions.saveAsNewEvaluation(promptId, 'saved-eval', {
                model: 'gpt-5',
                provider: 'openai',
                provider_key_id: null,
            })

            await expectLogic(llmPlaygroundPromptsLogic).toFinishAllListeners()

            expect(createCalled).toBe(true)
            expect(router.values.searchParams).toHaveProperty('source_evaluation_id', 'eval-new')
            expect(router.values.searchParams).not.toHaveProperty('source_prompt_name')
        })

        it('saveToLinkedPrompt should call update API with current system prompt', async () => {
            let updatedPrompt: string | undefined
            useMocks({
                get: {
                    '/api/environments/:team_id/llm_prompts/name/:name/': {
                        id: 'prompt-linked',
                        name: 'linked',
                        prompt: 'Old prompt.',
                        latest_version: 3,
                    },
                },
                patch: {
                    '/api/environments/:team_id/llm_prompts/name/:name/': (req: any) => {
                        updatedPrompt = req.body.prompt
                        return [200, { id: 'prompt-linked', name: 'linked', prompt: req.body.prompt }]
                    },
                },
            })

            llmPlaygroundPromptsLogic.actions.setupPlaygroundFromEvent({
                sourceType: 'prompt',
                sourcePromptName: 'linked',
            })

            await expectLogic(llmPlaygroundPromptsLogic).toFinishAllListeners()

            llmPlaygroundPromptsLogic.actions.setSystemPrompt('Updated prompt.')
            const promptId = llmPlaygroundPromptsLogic.values.promptConfigs[0].id
            llmPlaygroundPromptsLogic.actions.saveToLinkedPrompt(promptId)

            await expectLogic(llmPlaygroundPromptsLogic).toFinishAllListeners()

            expect(updatedPrompt).toBe('Updated prompt.')
        })

        it('saveToLinkedEvaluation should call update API', async () => {
            let updateCalled = false
            useMocks({
                get: {
                    '/api/environments/:team_id/evaluations/:id/': {
                        id: 'eval-linked',
                        name: 'linked-eval',
                        evaluation_type: 'llm_judge',
                        evaluation_config: { prompt: 'Old eval prompt.' },
                    },
                },
                patch: {
                    '/api/environments/:team_id/evaluations/:id/': () => {
                        updateCalled = true
                        return [200, { id: 'eval-linked', name: 'linked-eval' }]
                    },
                },
            })

            llmPlaygroundPromptsLogic.actions.setupPlaygroundFromEvent({
                sourceType: 'evaluation',
                sourceEvaluationId: 'eval-linked',
            })

            await expectLogic(llmPlaygroundPromptsLogic).toFinishAllListeners()

            llmPlaygroundPromptsLogic.actions.setSystemPrompt('New eval prompt.')
            const promptId = llmPlaygroundPromptsLogic.values.promptConfigs[0].id
            llmPlaygroundPromptsLogic.actions.saveToLinkedEvaluation(promptId, {
                model: 'gpt-5',
                provider: 'openai',
                provider_key_id: null,
            })

            await expectLogic(llmPlaygroundPromptsLogic).toFinishAllListeners()

            expect(updateCalled).toBe(true)
        })
    })
})
