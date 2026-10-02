import { describe, expect, it, vi } from 'vitest'

import { getToolsFromContext } from '@/tools'
import { GENERATED_TOOLS } from '@/tools/generated/ai_observability'
import {
    POSTHOG_FORMATTED_RESULTS_OVERRIDE_KEY,
    POSTHOG_INFORMATIONAL_RESPONSE_KEY,
    type Context,
    type Tool,
} from '@/tools/types'

const experimentId = '00000000-0000-4000-8000-000000000001'
const itemId = '00000000-0000-4000-8000-000000000002'
const versionId = '00000000-0000-4000-8000-000000000003'

function createContext(response: unknown): { context: Context; request: ReturnType<typeof vi.fn> } {
    const request = vi.fn().mockResolvedValue(response)
    return {
        context: {
            api: { request, getProjectBaseUrl: () => 'https://example.com/project/17' },
            stateManager: {
                getProjectId: async () => '17',
                getApiKey: async () => ({ scopes: ['*'] }),
                getAiConsentGiven: async () => true,
                getUser: async () => ({ is_staff: false }),
            },
        } as unknown as Context,
        request,
    }
}

async function getTool(context: Context, name: string): Promise<Tool> {
    const tools = await getToolsFromContext(context, {
        tools: [name],
        featureFlags: { 'ai-observability-offline-evaluations': true },
    })
    return tools.find((tool) => tool.name === name)!
}

describe('offline evaluation MCP tools', () => {
    it('preserves cursor pagination and shared scorer configurations on item pages', async () => {
        const response = {
            count: 40,
            next_cursor: 'next-page',
            results: [{ id: itemId, results: [] }],
            scorer_versions: [{ id: versionId, config: { true_is_failure: true } }],
        }
        const { context, request } = createContext(response)
        const tool = GENERATED_TOOLS['llma-offline-experiment-item-list']!()
        const result = await tool.handler(
            context,
            tool.schema.parse({ id: experimentId, scorer_version_ids: versionId })
        )

        expect(request).toHaveBeenCalledExactlyOnceWith({
            method: 'GET',
            path: `/api/projects/17/ai_observability/offline_experiments/${experimentId}/items/`,
            query: { cursor: undefined, limit: 20, scorer_version_ids: versionId },
        })
        expect(result).toMatchObject(response)
    })

    it('sends exact scorer-version identities and typed result values on upload', async () => {
        const { context, request } = createContext({ items: [], results: [] })
        const tool = GENERATED_TOOLS['llma-offline-experiment-upload']!()
        const results = [{ item_id: itemId, scorer_version_id: versionId, status: 'ok', value: false }]
        await tool.handler(context, tool.schema.parse({ id: experimentId, results }))
        expect(request).toHaveBeenCalledExactlyOnceWith({
            method: 'POST',
            path: `/api/projects/17/ai_observability/offline_experiments/${experimentId}/upload/`,
            body: { results },
        })
        expect(
            tool.schema.safeParse({ id: experimentId, results: [{ ...results[0], scorer_version_id: 1 }] }).success
        ).toBe(false)
    })

    it.each([
        ['llma-offline-experiment-item-payload-get', 'item_id', 'items'],
        ['llma-offline-experiment-result-payload-get', 'result_id', 'results'],
    ])('bounds and reconstructs Unicode payloads through the registered %s tool', async (name, idField, resource) => {
        const data = { input: 'x'.repeat(7988) + '🦔'.repeat(5000), expected_output: null, metadata: {} }
        const { context, request } = createContext({
            id: itemId,
            payload_state: 'available',
            payload_expires_at: null,
            available: true,
            data,
        })
        const tool = await getTool(context, name)
        let offset: number | null = 0
        let reconstructed = ''
        do {
            const page = (await tool.handler(
                context,
                tool.schema.parse({ id: experimentId, [idField]: itemId, offset, max_chars: 8000 })
            )) as {
                data_json: string
                next_offset: number | null
                total_chars: number
                [POSTHOG_INFORMATIONAL_RESPONSE_KEY]: boolean
                [POSTHOG_FORMATTED_RESULTS_OVERRIDE_KEY]: string
            }
            expect(page.data_json.length).toBeLessThanOrEqual(8000)
            expect(new TextDecoder().decode(new TextEncoder().encode(page.data_json))).toBe(page.data_json)
            expect(page).not.toHaveProperty('data')
            expect(page.total_chars).toBe(JSON.stringify(data).length)
            expect(page[POSTHOG_INFORMATIONAL_RESPONSE_KEY]).toBe(true)
            expect(page[POSTHOG_FORMATTED_RESULTS_OVERRIDE_KEY].length).toBeLessThan(50000)
            reconstructed += page.data_json
            offset = page.next_offset
        } while (offset !== null)
        expect(JSON.parse(reconstructed)).toEqual(data)
        expect(request).toHaveBeenCalledWith({
            method: 'GET',
            path: `/api/projects/17/ai_observability/offline_experiments/${experimentId}/${resource}/${itemId}/payload/`,
        })
        expect(tool.schema.safeParse({ id: experimentId, [idField]: itemId, max_chars: 8001 }).success).toBe(false)
    })

    it.each(['not_provided', 'expired'])(
        'preserves unavailable payload state %s without a continuation',
        async (payload_state) => {
            const { context } = createContext({
                id: itemId,
                payload_state,
                payload_expires_at: null,
                available: false,
                data: null,
            })
            const tool = await getTool(context, 'llma-offline-experiment-item-payload-get')
            const page = await tool.handler(
                context,
                tool.schema.parse({ id: experimentId, item_id: itemId, offset: 4000 })
            )
            expect(page).toMatchObject({
                available: false,
                payload_state,
                data_json: null,
                next_offset: null,
                total_chars: 0,
            })
        }
    )

    it('does not turn payload authorization errors into missing content', async () => {
        const { context, request } = createContext(null)
        request.mockRejectedValue(new Error('Forbidden'))
        const tool = await getTool(context, 'llma-offline-experiment-result-payload-get')
        await expect(tool.handler(context, tool.schema.parse({ id: experimentId, result_id: itemId }))).rejects.toThrow(
            'Forbidden'
        )
    })
})
