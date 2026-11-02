import type { CallToolResult } from '@modelcontextprotocol/sdk/types.js'
import { describe, expect, it, vi } from 'vitest'

import { loadRenderUiData } from '@/ui-apps/apps/render-ui-data'
import { APP_DATA_META_KEY } from '@/ui-apps/types'

describe('render-ui data loading', () => {
    it.each([
        { appKey: 'survey' as const, toolName: 'survey-get' },
        { appKey: 'query-results' as const, toolName: 'query-trends' },
    ])('draws $appKey from preloaded data without calling the server', async ({ appKey, toolName }) => {
        const callServerTool = vi.fn().mockRejectedValue(new Error('MCP error -32603'))
        const meta = { [APP_DATA_META_KEY]: { results: [] } }

        expect(await loadRenderUiData({ callServerTool }, toolName, {}, appKey, meta)).toEqual({
            structuredContent: { results: [] },
        })
        expect(callServerTool).not.toHaveBeenCalled()
    })

    it('fetches from the server when the result carried no preloaded data', async () => {
        const result = { structuredContent: { id: 'example' }, content: [] }
        const callServerTool = vi.fn().mockResolvedValue(result)
        expect(await loadRenderUiData({ callServerTool }, 'survey-get', {}, 'survey', {})).toBe(result)
    })

    it.each(['query-trends', 'insight-query'])(
        'loads %s through the advertised exec tool as JSON',
        async (toolName) => {
            const data = { results: [{ data: [3] }] }
            const input = { event: 'a "quoted" event\nwith a newline' }
            const callServerTool = vi
                .fn()
                .mockResolvedValue({ content: [{ type: 'text', text: JSON.stringify(data) }] })

            expect(await loadRenderUiData({ callServerTool }, toolName, input, 'query-results')).toEqual({
                structuredContent: data,
            })
            expect(callServerTool).toHaveBeenCalledExactlyOnceWith({
                name: 'exec',
                arguments: { command: `call --json ${toolName} ${JSON.stringify(input)}` },
            })
        }
    )

    it.each<CallToolResult>([
        { content: [{ type: 'text', text: 'See structured content' }], structuredContent: { results: [] } },
        { content: [{ type: 'text', text: 'See app data' }], _meta: { [APP_DATA_META_KEY]: { results: [] } } },
    ])('accepts structured query results from inline app hosts: %j', async (result) => {
        const callServerTool = vi.fn().mockResolvedValue(result)
        expect(await loadRenderUiData({ callServerTool }, 'query-trends', {}, 'query-results')).toEqual({
            structuredContent: { results: [] },
        })
    })

    it('returns tool errors without trying to parse them as JSON', async () => {
        const result = { isError: true, content: [{ type: 'text', text: 'Query access denied' }] }
        const callServerTool = vi.fn().mockResolvedValue(result)
        expect(await loadRenderUiData({ callServerTool }, 'query-trends', {}, 'query-results')).toBe(result)
    })

    it('rejects non-JSON success text instead of treating it as chart data', async () => {
        const callServerTool = vi.fn().mockResolvedValue({ content: [{ type: 'text', text: 'Not JSON' }] })
        await expect(loadRenderUiData({ callServerTool }, 'query-trends', {}, 'query-results')).rejects.toThrow(
            SyntaxError
        )
    })

    it('keeps direct tool calls for other visualizations', async () => {
        const result = { structuredContent: { id: 'example' }, content: [] }
        const callServerTool = vi.fn().mockResolvedValue(result)
        expect(await loadRenderUiData({ callServerTool }, 'survey-get', { surveyId: 'example' }, 'survey')).toBe(result)
        expect(callServerTool).toHaveBeenCalledExactlyOnceWith({
            name: 'survey-get',
            arguments: { surveyId: 'example' },
        })
    })
})
