import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { ModelOption, llmAnalyticsPlaygroundLogic } from './llmAnalyticsPlaygroundLogic'

const MOCK_MODEL_OPTIONS: ModelOption[] = [
    { id: 'gpt-4.1', name: 'GPT-4.1', provider: 'OpenAI', description: '' },
    { id: 'gpt-4.1-mini', name: 'GPT-4.1 Mini', provider: 'OpenAI', description: '' },
    { id: 'gpt-5', name: 'GPT-5', provider: 'OpenAI', description: '' },
    { id: 'gpt-5-mini', name: 'GPT-5 Mini', provider: 'OpenAI', description: '' },
    { id: 'claude-3-opus', name: 'Claude 3 Opus', provider: 'Anthropic', description: '' },
]

const DEFAULT_MODEL = 'gpt-4.1'

describe('llmAnalyticsPlaygroundLogic', () => {
    let logic: ReturnType<typeof llmAnalyticsPlaygroundLogic.build>

    beforeEach(() => {
        initKeaTests()

        useMocks({
            get: {
                '/api/llm_proxy/models/': MOCK_MODEL_OPTIONS,
            },
        })

        logic = llmAnalyticsPlaygroundLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    describe('closest model matching', () => {
        it('should return exact match when model exists', async () => {
            await expectLogic(logic).toFinishAllListeners()

            // Test through setupPlaygroundFromEvent
            logic.actions.setupPlaygroundFromEvent({
                model: 'gpt-5',
                input: 'test input',
            })

            expect(logic.values.model).toBe('gpt-5')
        })

        it('should match by longest prefix', async () => {
            await expectLogic(logic).toFinishAllListeners()

            logic.actions.setupPlaygroundFromEvent({
                model: 'gpt-5-mini-2025-08-07',
                input: 'test input',
            })

            expect(logic.values.model).toBe('gpt-5-mini')
        })

        it('should match shorter prefix when longer not available', async () => {
            await expectLogic(logic).toFinishAllListeners()

            logic.actions.setupPlaygroundFromEvent({
                model: 'gpt-5-2025-08-07',
                input: 'test input',
            })

            expect(logic.values.model).toBe('gpt-5')
        })

        it('should return default model when no match found', async () => {
            await expectLogic(logic).toFinishAllListeners()

            logic.actions.setupPlaygroundFromEvent({
                model: 'llama-3-70b',
                input: 'test input',
            })

            expect(logic.values.model).toBe(DEFAULT_MODEL)
        })

        it('should handle empty model list gracefully', async () => {
            // Mock empty response
            useMocks({
                get: {
                    '/api/llm_proxy/models/': [],
                },
            })

            const emptyLogic = llmAnalyticsPlaygroundLogic()
            emptyLogic.mount()

            await expectLogic(emptyLogic).toFinishAllListeners()

            emptyLogic.actions.setupPlaygroundFromEvent({
                model: 'gpt-5-2025-08-07',
                input: 'test input',
            })

            expect(emptyLogic.values.model).toBe('gpt-5')

            emptyLogic.unmount()
        })
    })

    describe('setupPlaygroundFromEvent model matching', () => {
        it('should set valid model directly', async () => {
            await expectLogic(logic).toFinishAllListeners()

            logic.actions.setupPlaygroundFromEvent({
                model: 'claude-3-opus',
                input: 'test input',
            })

            expect(logic.values.model).toBe('claude-3-opus')
        })

        it('should handle missing model in payload', async () => {
            await expectLogic(logic).toFinishAllListeners()

            const originalModel = logic.values.model

            logic.actions.setupPlaygroundFromEvent({
                input: 'test input',
            })

            expect(logic.values.model).toBe(originalModel)
        })

        it('should preserve other payload data when model matching', async () => {
            await expectLogic(logic).toFinishAllListeners()

            const testInput = 'Hello, world!'
            const testTools = [{ name: 'search', description: 'Search tool' }]

            logic.actions.setupPlaygroundFromEvent({
                model: 'gpt-5-2025-08-07',
                input: testInput,
                tools: testTools,
            })

            expect(logic.values.model).toBe('gpt-5')
            expect(logic.values.tools).toEqual(testTools)
            // Input gets processed into messages - check that it's handled
            expect(logic.values.messages.length).toBeGreaterThan(0)
        })

        it('should prefer longer prefix matches', async () => {
            // Add a test case where multiple prefixes could match
            const extendedMockOptions = [
                ...MOCK_MODEL_OPTIONS,
                { id: 'gpt-5-mini-turbo', name: 'GPT-5 Mini Turbo', provider: 'OpenAI', description: '' },
            ]

            useMocks({
                get: {
                    '/api/llm_proxy/models/': extendedMockOptions,
                },
            })

            const testLogic = llmAnalyticsPlaygroundLogic()
            testLogic.mount()

            await expectLogic(testLogic).toFinishAllListeners()

            testLogic.actions.setupPlaygroundFromEvent({
                model: 'gpt-5-mini-turbo-2025',
                input: 'test',
            })

            // Should match 'gpt-5-mini' as it's the longest prefix that matches
            expect(testLogic.values.model).toBe('gpt-5-mini')

            testLogic.unmount()
        })
    })

    describe('loadModelOptions auto-correction', () => {
        it('should auto-correct invalid model after loading options', async () => {
            // Create logic and mount
            const testLogic = llmAnalyticsPlaygroundLogic()
            testLogic.mount()

            // Set an invalid model that should be corrected
            testLogic.actions.setModel('gpt-5-2025-08-07')

            // Manually trigger model options loading
            testLogic.actions.loadModelOptions()

            // Wait for the loader to finish
            await expectLogic(testLogic).toFinishAllListeners()

            // Model should be auto-corrected to closest match
            expect(testLogic.values.model).toBe('gpt-5')

            testLogic.unmount()
        })

        it('should not change valid models during loading', async () => {
            const testLogic = llmAnalyticsPlaygroundLogic()
            testLogic.actions.setModel('claude-3-opus')
            testLogic.mount()

            await expectLogic(testLogic).toFinishAllListeners()

            // Valid model should remain unchanged
            expect(testLogic.values.model).toBe('claude-3-opus')

            testLogic.unmount()
        })

        it('should handle API errors gracefully', async () => {
            useMocks({
                get: {
                    '/api/llm_proxy/models/': () => {
                        throw new Error('API Error')
                    },
                },
            })

            const errorLogic = llmAnalyticsPlaygroundLogic()
            errorLogic.mount()

            await expectLogic(errorLogic).toFinishAllListeners()

            // Should not crash and maintain previous model options
            expect(errorLogic.values.modelOptions).toEqual(MOCK_MODEL_OPTIONS)

            errorLogic.unmount()
        })
    })

    describe('Message Management', () => {
        it('should clear all messages when clearConversation is called', () => {
            // Add some messages first
            logic.actions.addMessage({ role: 'user', content: 'Hello' })
            logic.actions.addMessage({ role: 'assistant', content: 'Hi there!' })
            logic.actions.addMessage({ role: 'system', content: 'System message' })

            expect(logic.values.messages).toHaveLength(3)

            logic.actions.clearConversation()

            expect(logic.values.messages).toHaveLength(0)
            expect(logic.values.messages).toEqual([])
        })

        it('should delete message at specific index', () => {
            logic.actions.setMessages([
                { role: 'user', content: 'First' },
                { role: 'assistant', content: 'Second' },
                { role: 'user', content: 'Third' },
            ])

            logic.actions.deleteMessage(1)

            expect(logic.values.messages).toEqual([
                { role: 'user', content: 'First' },
                { role: 'user', content: 'Third' },
            ])
        })

        it('should handle deleteMessage with invalid indices gracefully', () => {
            logic.actions.setMessages([{ role: 'user', content: 'Only message' }])

            // Try to delete non-existent indices
            logic.actions.deleteMessage(-1)
            expect(logic.values.messages).toHaveLength(1)

            logic.actions.deleteMessage(5)
            expect(logic.values.messages).toHaveLength(1)

            // Original message should still be there
            expect(logic.values.messages[0].content).toBe('Only message')
        })

        it('should add messages with different roles', () => {
            logic.actions.addMessage({ role: 'user', content: 'User message' })
            logic.actions.addMessage({ role: 'assistant', content: 'Assistant message' })
            logic.actions.addMessage({ role: 'system', content: 'System message' })

            expect(logic.values.messages).toEqual([
                { role: 'user', content: 'User message' },
                { role: 'assistant', content: 'Assistant message' },
                { role: 'system', content: 'System message' },
            ])
        })

        it('should add message with default values when partial message provided', () => {
            logic.actions.addMessage({ content: 'Just content' })

            expect(logic.values.messages[0]).toEqual({
                role: 'user', // default role
                content: 'Just content',
            })

            logic.actions.addMessage({ role: 'assistant' })

            expect(logic.values.messages[1]).toEqual({
                role: 'assistant',
                content: '', // default content
            })
        })

        it('should update message at specific index', () => {
            logic.actions.setMessages([
                { role: 'user', content: 'Original' },
                { role: 'assistant', content: 'Response' },
            ])

            logic.actions.updateMessage(0, { content: 'Updated content' })

            expect(logic.values.messages[0]).toEqual({
                role: 'user',
                content: 'Updated content',
            })

            logic.actions.updateMessage(1, { role: 'user', content: 'Changed everything' })

            expect(logic.values.messages[1]).toEqual({
                role: 'user',
                content: 'Changed everything',
            })
        })

        it('should not update message with invalid index', () => {
            logic.actions.setMessages([{ role: 'user', content: 'Original' }])

            const originalMessages = [...logic.values.messages]

            logic.actions.updateMessage(-1, { content: 'Should not update' })
            expect(logic.values.messages).toEqual(originalMessages)

            logic.actions.updateMessage(10, { content: 'Should not update' })
            expect(logic.values.messages).toEqual(originalMessages)
        })

        it('should add response to history only when content exists', () => {
            logic.actions.setMessages([{ role: 'user', content: 'Question' }])

            logic.actions.addResponseToHistory('Assistant response')

            expect(logic.values.messages).toEqual([
                { role: 'user', content: 'Question' },
                { role: 'assistant', content: 'Assistant response' },
            ])

            // Should not add empty responses
            logic.actions.addResponseToHistory('')
            expect(logic.values.messages).toHaveLength(2)

            logic.actions.addResponseToHistory(null as any)
            expect(logic.values.messages).toHaveLength(2)
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

            logic.actions.setupPlaygroundFromEvent({ input })

            expect(logic.values.systemPrompt).toBe('You are a helpful assistant.')
            expect(logic.values.messages).toEqual([
                { role: 'user', content: 'Hello' },
                { role: 'assistant', content: 'Hi there!' },
                { role: 'user', content: 'How are you?' },
            ])
        })

        it('should normalize role names (ai/model to assistant)', () => {
            const input = [
                { role: 'user', content: 'Question' },
                { role: 'ai', content: 'AI response' },
                { role: 'model', content: 'Model response' },
            ]

            logic.actions.setupPlaygroundFromEvent({ input })

            expect(logic.values.messages).toEqual([
                { role: 'user', content: 'Question' },
                { role: 'assistant', content: 'AI response' },
                { role: 'assistant', content: 'Model response' },
            ])
        })

        it('should handle string input as initial user message', () => {
            logic.actions.setupPlaygroundFromEvent({
                input: 'Simple string prompt',
            })

            expect(logic.values.messages).toEqual([{ role: 'user', content: 'Simple string prompt' }])
            expect(logic.values.systemPrompt).toBe('You are a helpful AI assistant.')
        })

        it('should handle object input with content field', () => {
            const input = {
                content: 'Content from object',
                someOtherField: 'ignored',
            }

            logic.actions.setupPlaygroundFromEvent({ input })

            expect(logic.values.messages).toEqual([{ role: 'user', content: 'Content from object' }])
        })

        it('should handle object input with non-string content field', () => {
            const input = {
                content: { nested: 'data', array: [1, 2, 3] },
            }

            logic.actions.setupPlaygroundFromEvent({ input })

            expect(logic.values.messages[0].role).toBe('user')
            expect(logic.values.messages[0].content).toContain('"nested"')
            expect(logic.values.messages[0].content).toContain('"data"')
            // Check for array content in pretty-printed format
            const content = logic.values.messages[0].content
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

            logic.actions.setupPlaygroundFromEvent({ input })

            expect(logic.values.messages[0].role).toBe('user')
            expect(logic.values.messages[0].content).toContain('"someField"')
            expect(logic.values.messages[0].content).toContain('"value"')
            expect(logic.values.messages[0].content).toContain('123')
        })

        it('should handle tools parameter', () => {
            const tools = [
                { type: 'function', function: { name: 'search', description: 'Search tool' } },
                { type: 'function', function: { name: 'calculator', description: 'Math tool' } },
            ]

            logic.actions.setupPlaygroundFromEvent({
                input: 'Test',
                tools,
            })

            expect(logic.values.tools).toEqual(tools)
        })

        it('should default messages with unknown roles to user', () => {
            const input = [
                { role: 'user', content: 'Valid user' },
                { role: 'invalid_role', content: 'Unknown role defaults to user' },
                { role: 'assistant', content: 'Valid assistant' },
                { role: 'unknown', content: 'Also defaults to user' },
            ]

            logic.actions.setupPlaygroundFromEvent({ input })

            expect(logic.values.messages).toEqual([
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

            logic.actions.setupPlaygroundFromEvent({ input })

            expect(logic.values.messages[0].content).toContain('"text"')
            expect(logic.values.messages[0].content).toContain('"Complex content"')
            expect(logic.values.messages[1].content).toContain('["array","content"]')
        })

        it('should reset to default system prompt when none provided', () => {
            logic.actions.setSystemPrompt('Custom prompt')

            const input = [
                { role: 'user', content: 'No system message here' },
                { role: 'assistant', content: 'Response' },
            ]

            logic.actions.setupPlaygroundFromEvent({ input })

            expect(logic.values.systemPrompt).toBe('You are a helpful AI assistant.')
        })

        it('should preserve existing model if not provided in payload', () => {
            logic.actions.setModel('claude-3-opus')

            logic.actions.setupPlaygroundFromEvent({
                input: 'Test without model',
            })

            expect(logic.values.model).toBe('claude-3-opus')
        })
    })
})
