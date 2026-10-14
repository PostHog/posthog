import { beforeEach, describe, expect, it, vi } from 'vitest'

import { MCP_OPENAI_RESULT_FILES_FEATURE_FLAG } from '@/hono/constants'
import type { ResolvedState } from '@/hono/request-state-resolver'
import { type ToolResultPayload, EXEC_BUILT_PAYLOAD } from '@/lib/build-tool-result'
import { MCPClientProfile } from '@/lib/client-detection'
import { offloadToolResult, RESULT_FILE_THRESHOLD_BYTES } from '@/lib/result-files'

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
    return { content: [{ type: 'text', text: 'x'.repeat(RESULT_FILE_THRESHOLD_BYTES) + 'hidden-result' }] }
}

describe('result files', () => {
    beforeEach(() => {
        storeResult.mockReset().mockResolvedValue({ download_url: downloadUrl, expires_in: 3600 })
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
            expect(result._meta).toEqual(response._meta)
            expect(result[EXEC_BUILT_PAYLOAD]).toBe(true)
            expect(response.structuredContent).toEqual({ answer: 'complete structured result' })
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
    ])('keeps small, failed, and oversized responses inline', async (response) => {
        expect(await offloadToolResult(response, makeState('openai-mcp'))).toBe(response)
        expect(storeResult).not.toHaveBeenCalled()
    })

    it('uses UTF-8 bytes when deciding whether to offload', async () => {
        const response: ToolResultPayload = { content: [{ type: 'text', text: '猫'.repeat(12000) }] }
        await offloadToolResult(response, makeState('openai-mcp'))
        expect(storeResult).toHaveBeenCalledOnce()
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
