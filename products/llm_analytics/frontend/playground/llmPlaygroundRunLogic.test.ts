import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { llmPlaygroundPromptsLogic } from './llmPlaygroundPromptsLogic'
import { appendToolCallChunk, llmPlaygroundRunLogic, mergeUsage } from './llmPlaygroundRunLogic'

describe('llmPlaygroundRunLogic', () => {
    beforeEach(() => {
        initKeaTests()
        useMocks({
            get: {
                '/api/llm_proxy/models/': [
                    { id: 'gpt-5-mini', name: 'GPT-5 Mini', provider: 'OpenAI', description: '' },
                ],
                '/api/environments/:team_id/llm_analytics/evaluation_config/': {
                    active_provider_key: null,
                },
                '/api/environments/:team_id/llm_analytics/provider_keys/': {
                    results: [],
                },
            },
        })
    })

    it('aggregates tool call chunks by id and trailing argument chunks', () => {
        const initial = appendToolCallChunk([], {
            id: 'call_1',
            function: { name: 'get_weather', arguments: '{"city":"' },
        })
        const withContinuation = appendToolCallChunk(initial, {
            id: 'call_1',
            function: { arguments: 'Nicosia"}' },
        })
        const withTrailingChunk = appendToolCallChunk(withContinuation, {
            function: { arguments: '\n{"unit":"celsius"}' },
        })

        expect(withTrailingChunk).toEqual([
            { id: 'call_1', name: 'get_weather', arguments: '{"city":"Nicosia"}\n{"unit":"celsius"}' },
        ])
    })

    it('merges usage chunks without dropping previous non-zero values', () => {
        const merged = mergeUsage(
            { prompt_tokens: 120, completion_tokens: null, total_tokens: null },
            { prompt_tokens: 0, completion_tokens: 56, total_tokens: 176 }
        )

        expect(merged).toEqual({
            prompt_tokens: 120,
            completion_tokens: 56,
            total_tokens: 176,
            cache_read_tokens: null,
            cache_write_tokens: null,
        })
    })

    it('sends sampling settings in completion request payload', async () => {
        const streamSpy = jest.spyOn(api, 'stream').mockImplementation(async (_url, options: any) => {
            options.onMessage?.({ data: JSON.stringify({ type: 'text', text: 'ok' }) })
            options.onMessage?.({
                data: JSON.stringify({ type: 'usage', prompt_tokens: 10, completion_tokens: 4, total_tokens: 14 }),
            })
        })

        const logic = llmPlaygroundRunLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        llmPlaygroundPromptsLogic.actions.setModel('gpt-5-mini')
        llmPlaygroundPromptsLogic.actions.setMessages([{ role: 'user', content: 'hello' }])
        llmPlaygroundPromptsLogic.actions.setTemperature(0.4)
        llmPlaygroundPromptsLogic.actions.setTopP(0.9)
        llmPlaygroundRunLogic.actions.submitPrompt()

        await expectLogic(logic).toFinishAllListeners()

        expect(streamSpy).toHaveBeenCalledTimes(1)
        expect(streamSpy.mock.calls[0][1]?.data).toMatchObject({
            temperature: 0.4,
            top_p: 0.9,
        })

        logic.unmount()
        streamSpy.mockRestore()
    })
})
