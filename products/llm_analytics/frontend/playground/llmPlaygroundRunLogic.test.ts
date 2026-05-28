import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import api, { ApiError } from 'lib/api'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { llmPlaygroundModelLogic } from './llmPlaygroundModelLogic'
import { llmPlaygroundPromptsLogic } from './llmPlaygroundPromptsLogic'
import { appendToolCallChunk, describeError, llmPlaygroundRunLogic, mergeUsage } from './llmPlaygroundRunLogic'

describe('llmPlaygroundRunLogic', () => {
    beforeEach(() => {
        initKeaTests()
        useMocks({
            get: {
                '/api/llm_proxy/models/': [
                    { id: 'gpt-5-mini', name: 'GPT-5 Mini', provider: 'OpenAI', description: '' },
                ],
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

    it('surfaces backend error message and captures exception when stream fails with ApiError', async () => {
        const apiError = new ApiError('fallback message', 400, undefined, {
            error: 'Thinking is not supported for this model',
        })
        const streamSpy = jest.spyOn(api, 'stream').mockImplementation(async (_url, options: any) => {
            options.onError?.(apiError)
        })
        const captureExceptionSpy = jest.spyOn(posthog, 'captureException').mockImplementation(() => undefined)

        const logic = llmPlaygroundRunLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        llmPlaygroundPromptsLogic.actions.setModel('gpt-5-mini')
        llmPlaygroundPromptsLogic.actions.setMessages([{ role: 'user', content: 'hello' }])
        llmPlaygroundRunLogic.actions.submitPrompt()

        await expectLogic(logic).toFinishAllListeners()

        const items = llmPlaygroundRunLogic.values.comparisonItems
        expect(items).toHaveLength(1)
        expect(items[0].error).toBe(true)
        expect(items[0].response).toContain('**Error:** Thinking is not supported for this model')
        expect(items[0].response).not.toContain('Stream Connection Error')
        expect(captureExceptionSpy).toHaveBeenCalledWith(
            apiError,
            expect.objectContaining({ tag: 'llma-playground-prompt-run', status: 400 })
        )

        logic.unmount()
        streamSpy.mockRestore()
        captureExceptionSpy.mockRestore()
    })

    it('labels non-ApiError stream failures as connection errors and captures them', async () => {
        const connectionError = new Error('network down')
        const streamSpy = jest.spyOn(api, 'stream').mockImplementation(async (_url, options: any) => {
            options.onError?.(connectionError)
        })
        const captureExceptionSpy = jest.spyOn(posthog, 'captureException').mockImplementation(() => undefined)

        const logic = llmPlaygroundRunLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        llmPlaygroundPromptsLogic.actions.setModel('gpt-5-mini')
        llmPlaygroundPromptsLogic.actions.setMessages([{ role: 'user', content: 'hello' }])
        llmPlaygroundRunLogic.actions.submitPrompt()

        await expectLogic(logic).toFinishAllListeners()

        const items = llmPlaygroundRunLogic.values.comparisonItems
        expect(items).toHaveLength(1)
        expect(items[0].error).toBe(true)
        expect(items[0].response).toContain('**Stream Connection Error:** network down')
        expect(captureExceptionSpy).toHaveBeenCalledWith(
            connectionError,
            expect.objectContaining({ tag: 'llma-playground-prompt-run', status: undefined })
        )

        logic.unmount()
        streamSpy.mockRestore()
        captureExceptionSpy.mockRestore()
    })

    describe('completion request provider/key resolution', () => {
        const azureKeyId = '11111111-1111-1111-1111-111111111111'

        const buildMocks = (
            keys: { id: string; provider: string; state?: string; name?: string }[],
            byokByKey: Record<string, { id: string; name: string; provider: string }[]> = {}
        ): Parameters<typeof useMocks>[0] => ({
            get: {
                '/api/llm_proxy/models/': (req: any) => {
                    const providerKeyId = req.url.searchParams.get('provider_key_id')
                    if (providerKeyId) {
                        return [200, byokByKey[providerKeyId] ?? []]
                    }
                    return [200, [{ id: 'gpt-5-mini', name: 'GPT-5 Mini', provider: 'OpenAI', description: '' }]]
                },
                '/api/environments/:team_id/llm_analytics/provider_keys/': {
                    results: keys.map((k) => ({
                        id: k.id,
                        provider: k.provider,
                        name: k.name ?? `${k.provider} key`,
                        state: k.state ?? 'ok',
                        error_message: null,
                        api_key_masked: '***',
                        azure_endpoint_display: null,
                        api_version_display: null,
                        created_at: '2026-01-01T00:00:00Z',
                        created_by: null,
                        last_used_at: null,
                    })),
                },
            },
        })

        const runOnce = async (model: string, selectedProviderKeyId: string | null = null): Promise<any> => {
            const streamSpy = jest.spyOn(api, 'stream').mockImplementation(async (_url, options: any) => {
                options.onMessage?.({ data: JSON.stringify({ type: 'text', text: 'ok' }) })
            })
            const logic = llmPlaygroundRunLogic()
            logic.mount()
            const modelLogic = llmPlaygroundModelLogic()
            modelLogic.mount()
            await expectLogic(logic).toFinishAllListeners()
            await expectLogic(modelLogic).toFinishAllListeners()

            llmPlaygroundPromptsLogic.actions.setModel(model, selectedProviderKeyId ?? undefined)
            llmPlaygroundPromptsLogic.actions.setMessages([{ role: 'user', content: 'hello' }])
            llmPlaygroundRunLogic.actions.submitPrompt()
            await expectLogic(logic).toFinishAllListeners()

            const payload = streamSpy.mock.calls[0]?.[1]?.data
            logic.unmount()
            modelLogic.unmount()
            streamSpy.mockRestore()
            return payload
        }

        it('sends canonical provider value when running a BYOK Azure model', async () => {
            useMocks(
                buildMocks([{ id: azureKeyId, provider: 'azure_openai' }], {
                    [azureKeyId]: [{ id: 'gpt-4.1', name: 'gpt-4.1', provider: 'Azure OpenAI' }],
                })
            )
            const payload = await runOnce('gpt-4.1', azureKeyId)
            expect(payload).toMatchObject({
                model: 'gpt-4.1',
                provider: 'azure_openai',
                provider_key_id: azureKeyId,
            })
        })

        it('does not attach a mismatched-provider key when running a trial model', async () => {
            // Azure key configured + trial OpenAI model would trigger ProviderMismatchError on the backend.
            useMocks(buildMocks([{ id: azureKeyId, provider: 'azure_openai' }]))
            const payload = await runOnce('gpt-5-mini')
            expect(payload).toMatchObject({ model: 'gpt-5-mini', provider: 'openai' })
            expect(payload.provider_key_id).toBeUndefined()
        })
    })

    it('captures exceptions thrown before the stream opens', async () => {
        const thrownError = new ApiError('fallback message', 400, undefined, {
            error: 'Invalid provider key configuration',
        })
        const streamSpy = jest.spyOn(api, 'stream').mockImplementation(async () => {
            throw thrownError
        })
        const captureExceptionSpy = jest.spyOn(posthog, 'captureException').mockImplementation(() => undefined)

        const logic = llmPlaygroundRunLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        llmPlaygroundPromptsLogic.actions.setModel('gpt-5-mini')
        llmPlaygroundPromptsLogic.actions.setMessages([{ role: 'user', content: 'hello' }])
        llmPlaygroundRunLogic.actions.submitPrompt()

        await expectLogic(logic).toFinishAllListeners()

        const items = llmPlaygroundRunLogic.values.comparisonItems
        expect(items).toHaveLength(1)
        expect(items[0].error).toBe(true)
        expect(items[0].response).toContain('**Error:** Invalid provider key configuration')
        expect(captureExceptionSpy).toHaveBeenCalledWith(
            thrownError,
            expect.objectContaining({ tag: 'llma-playground-prompt-submit', status: 400 })
        )

        logic.unmount()
        streamSpy.mockRestore()
        captureExceptionSpy.mockRestore()
    })

    describe('describeError', () => {
        it('prefers structured backend error string over detail and message', () => {
            const err = new ApiError('fallback', 400, undefined, { error: 'backend says no' })
            expect(describeError(err, 'fallback2')).toEqual({ message: 'backend says no', status: 400 })
        })

        it('ignores non-string data.error payloads and falls back to detail', () => {
            const err = new ApiError('fallback', 400, undefined, {
                error: { field: ['is required'] },
                detail: 'validation failed',
            })
            expect(describeError(err, 'fallback2')).toEqual({ message: 'validation failed', status: 400 })
        })

        it('uses err.message for plain Error instances without a status', () => {
            expect(describeError(new Error('boom'), 'fallback')).toEqual({ message: 'boom' })
        })

        it('returns the fallback for non-Error values', () => {
            expect(describeError('nope', 'fallback')).toEqual({ message: 'fallback' })
        })
    })
})
