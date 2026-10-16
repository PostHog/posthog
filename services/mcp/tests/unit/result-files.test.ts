import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiClient } from '@/api/client'
import { MCP_OPENAI_RESULT_FILES_FEATURE_FLAG } from '@/hono/constants'
import type { ResolvedState } from '@/hono/request-state-resolver'
import { type ToolResultPayload, buildToolResultPayload, EXEC_BUILT_PAYLOAD } from '@/lib/build-tool-result'
import { MCPClientProfile } from '@/lib/client-detection'
import { offloadToolResult, RESULT_FILE_THRESHOLD_CHARS } from '@/lib/result-files'
import { APP_DATA_META_KEY } from '@/ui-apps/types'

const storeResult = vi.fn()
const downloadUrl = 'https://storage.example.com/result.json?signature=example'

function makeState(clientName: string, flag: boolean | string | undefined = true): ResolvedState {
    return {
        clientProfile: new MCPClientProfile({ clientName }),
        toolFeatureFlags: { [MCP_OPENAI_RESULT_FILES_FEATURE_FLAG]: flag },
        context: {
            api: { request: storeResult },
            stateManager: { getProjectId: async () => '123' },
        },
    } as unknown as ResolvedState
}

function largeResult(): ToolResultPayload {
    return { content: [{ type: 'text', text: 'x'.repeat(RESULT_FILE_THRESHOLD_CHARS) + 'hidden-result' }] }
}

describe('result files', () => {
    beforeEach(() => {
        storeResult.mockReset().mockResolvedValue({ download_url: downloadUrl, expires_in: 3600 })
    })

    afterEach(() => {
        vi.useRealTimers()
        vi.restoreAllMocks()
        vi.unstubAllGlobals()
    })

    it.each(['openai-mcp', 'openai-mcp (Codex)', 'codex-mcp-client', 'ChatGPT'])(
        'stores the complete response for %s and returns a bounded preview',
        async (clientName) => {
            const response = largeResult()
            response.structuredContent = { answer: 'complete structured result' }
            response._meta = { ui: { resourceUri: 'ui://example' } }
            response[EXEC_BUILT_PAYLOAD] = true
            const result = await offloadToolResult(response, makeState(clientName))
            const pointer = JSON.parse(result.content[0]!.text)
            const request = storeResult.mock.calls[0]![0]
            expect(request.path).toBe('/api/projects/123/mcp_tools/results/store/')
            expect(JSON.parse(request.body.content)).toEqual({
                content: response.content,
                structuredContent: response.structuredContent,
            })
            expect(pointer.download_url).toBe(downloadUrl)
            expect(pointer.expires_in).toBe(3600)
            expect(pointer.preview.length).toBe(2000)
            expect(result.content[0]!.text).not.toContain('hidden-result')
            expect(result.structuredContent).toBeUndefined()
            expect(result._meta).toEqual({ ...response._meta, [APP_DATA_META_KEY]: response.structuredContent })
            expect(result[EXEC_BUILT_PAYLOAD]).toBe(true)
            expect(response.structuredContent).toEqual({ answer: 'complete structured result' })
        }
    )

    it('preserves app data when the structured result is the only data channel', async () => {
        const response = buildToolResultPayload({
            handlerResult: { rows: ['synthetic result '.repeat(4000)] },
            toolName: 'ui-tool',
            toolMeta: { ui: { resourceUri: 'ui://example' } },
            params: {},
            forceUiDataToMeta: true,
            includeUiResponseMeta: true,
        })
        const result = await offloadToolResult(response, makeState('codex-mcp-client'))

        expect(JSON.parse(result.content[0]!.text).download_url).toBe(downloadUrl)
        expect(result.structuredContent).toBeUndefined()
        expect(result._meta).toEqual({ ...response._meta, [APP_DATA_META_KEY]: response.structuredContent })
    })

    it.each(['connection', 'body', 'throttle'])(
        'returns the original result promptly when the upload stalls at %s',
        async (failure) => {
            vi.useFakeTimers()
            vi.spyOn(console, 'warn').mockImplementation(() => {})
            vi.spyOn(console, 'error').mockImplementation(() => {})
            let signal: AbortSignal | undefined
            const fetch = vi.fn((_url: string, init?: RequestInit) => {
                signal = init!.signal!
                const stalled = (): Promise<never> =>
                    new Promise((_resolve, reject) => {
                        signal!.addEventListener('abort', () => reject(signal!.reason), { once: true })
                    })
                if (failure === 'throttle') {
                    return Promise.resolve(new Response('{}', { status: 429, headers: { 'Retry-After': '30' } }))
                }
                if (failure === 'body') {
                    const response = new Response('{}')
                    vi.spyOn(response, 'text').mockImplementation(stalled)
                    return Promise.resolve(response)
                }
                return stalled()
            })
            vi.stubGlobal('fetch', fetch)
            const state = makeState('openai-mcp')
            state.context.api = new ApiClient({ apiToken: 'phx_test', baseUrl: 'https://example.com' })
            const response = largeResult()
            const pending = offloadToolResult(response, state)

            await vi.advanceTimersByTimeAsync(5000)

            expect(await pending).toBe(response)
            expect(fetch).toHaveBeenCalledOnce()
            expect(signal?.aborted).toBe(failure !== 'throttle')
            expect(vi.getTimerCount()).toBe(0)
        }
    )

    it.each([
        ['openai-mcp', false],
        ['codex-mcp-client', undefined],
        ['openai-mcp', 'variant'],
        ['claude-code', true],
        ['Cursor', true],
    ] as const)('keeps inline responses for %s with flag %s', async (clientName, flag) => {
        const state = makeState(clientName)
        state.toolFeatureFlags = { [MCP_OPENAI_RESULT_FILES_FEATURE_FLAG]: flag }
        const response = largeResult()
        expect(await offloadToolResult(response, state)).toBe(response)
        expect(storeResult).not.toHaveBeenCalled()
    })

    it.each([
        { content: [{ type: 'text' as const, text: 'small result' }] },
        { ...largeResult(), isError: true },
        { content: [{ type: 'text' as const, text: 'x'.repeat(8 * 1024 * 1024) }] },
        { content: [{ type: 'text' as const, text: '猫'.repeat(3 * 1024 * 1024) }] },
    ])('keeps small, failed, and oversized responses inline', async (response) => {
        expect(await offloadToolResult(response, makeState('openai-mcp'))).toBe(response)
        expect(storeResult).not.toHaveBeenCalled()
    })

    it.each([
        ['x', 40_000],
        ['x', 40_001],
        ['猫', 40_000],
        ['猫', 40_001],
    ] as const)('offloads %s results only above 40,000 serialized characters: %i', async (character, length) => {
        const response: ToolResultPayload = { content: [{ type: 'text', text: '' }] }
        response.content[0]!.text = character.repeat(length - JSON.stringify(response).length)
        const result = await offloadToolResult(response, makeState('openai-mcp'))

        if (length === 40_000) {
            expect(result).toBe(response)
            expect(storeResult).not.toHaveBeenCalled()
        } else {
            const storedContent = storeResult.mock.calls[0]![0].body.content
            expect(JSON.parse(result.content[0]!.text)).toMatchObject({
                download_url: downloadUrl,
                size_bytes: Buffer.byteLength(storedContent, 'utf8'),
            })
        }
    })

    it('uses the user agent when client metadata is missing', async () => {
        const state = makeState('')
        state.clientProfile = new MCPClientProfile({ userAgent: 'openai-mcp/1.0.0 (Codex)' })
        await offloadToolResult(largeResult(), state)
        expect(storeResult).toHaveBeenCalledOnce()
    })

    it('returns the original response when storage fails after the tool succeeded', async () => {
        const warning = vi.spyOn(console, 'warn').mockImplementation(() => {})
        try {
            storeResult.mockRejectedValue(new Error('storage unavailable'))
            const response = largeResult()
            expect(await offloadToolResult(response, makeState('openai-mcp'))).toBe(response)
        } finally {
            warning.mockRestore()
        }
    })
})
