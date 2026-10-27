// Reproduction for MCP UI apps not rendering on Claude surfaces:
// https://posthog.slack.com/archives/C0368RPHLQH/p1793114647178269
// Every assertion locks in the current defective behavior, so this passes on
// master and must not land as a regression test.
import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import { afterAll, beforeAll, describe, expect, it } from 'vitest'

import { createApp } from '@/hono/app'
import type { RedisLike } from '@/hono/cache/RedisCache'
import { UI_APP_RENDER_NOTE } from '@/lib/build-tool-result'
import { STATELESS_PROTOCOL_VERSION } from '@/lib/stateless-protocol'
import { QUERY_RESULTS_RESOURCE_URI, RENDER_UI_RESOURCE_URI } from '@/resources/ui-apps.generated'
import { APP_DATA_META_KEY } from '@/ui-apps/types'

import { insightResults } from '../fixtures/insight-fixtures'
import { contextMillHandler, handlers } from '../workers/fixtures/handlers'
import { makeRedisRateLimitStubs } from './helpers/redis-rate-limit-stubs'

const queryHandler = http.post('*/query/', () =>
    HttpResponse.json({
        results: insightResults.trendsLine,
        formatted_results: '| date | $pageview |\n| --- | --- |\n| 2024-01-01 | 123 |',
    })
)

const mswServer = setupServer(...handlers, contextMillHandler, queryHandler)

function createInMemoryRedis(): RedisLike & {
    ping(): Promise<string>
    incrby(key: string, n: number): Promise<number>
} {
    const store = new Map<string, string>()
    return {
        get: async (key) => store.get(key) ?? null,
        set: async (key, value) => {
            store.set(key, String(value))
            return 'OK'
        },
        del: async (...keys) => {
            let removed = 0
            for (const key of keys) {
                if (store.delete(key)) {
                    removed++
                }
            }
            return removed
        },
        scan: async (cursor) => {
            const cur = String(cursor)
            return [cur === '0' ? 'next' : '0', cur === '0' ? Array.from(store.keys()) : []] as [string, string[]]
        },
        ...makeRedisRateLimitStubs(store),
        ping: async () => 'PONG',
    }
}

let app: ReturnType<typeof createApp>['app']
const TOKEN = 'phx_render_ui_connector_repro'

beforeAll(async () => {
    process.env.TEST = '1'
    process.env.MCP_APPS_BASE_URL = 'https://apps.test'
    mswServer.listen({ onUnhandledRequest: 'bypass' })
    const created = createApp(createInMemoryRedis())
    app = created.app
    await created.warmup()
}, 120_000)

afterAll(() => {
    mswServer.close()
})

interface ToolCallResult {
    isError?: boolean
    content: Array<{ type: string; text: string }>
    structuredContent?: Record<string, unknown>
    _meta?: Record<string, unknown>
}

// The connector reports the pooled `Anthropic/ClaudeAI` client and names the live
// product only in `x-anthropic-client`, which its own list fetch omits.
async function connectorRequest<T>(
    method: 'tools/list' | 'tools/call',
    params: Record<string, unknown>,
    vendorClient?: 'ClaudeCode' | 'ClaudeAI' | 'Cowork'
): Promise<T> {
    const name = typeof params.name === 'string' ? params.name : undefined
    const res = await app.request('/mcp', {
        method: 'POST',
        headers: {
            Authorization: `Bearer ${TOKEN}`,
            'Content-Type': 'application/json',
            Accept: 'application/json, text/event-stream',
            'User-Agent': 'Claude-User',
            'MCP-Protocol-Version': STATELESS_PROTOCOL_VERSION,
            'Mcp-Method': method,
            ...(name ? { 'Mcp-Name': name } : {}),
            ...(vendorClient ? { 'x-anthropic-client': vendorClient } : {}),
        },
        body: JSON.stringify({
            jsonrpc: '2.0',
            id: 1,
            method,
            params: {
                ...params,
                _meta: {
                    'io.modelcontextprotocol/protocolVersion': STATELESS_PROTOCOL_VERSION,
                    'io.modelcontextprotocol/clientInfo': { name: 'Anthropic/ClaudeAI', version: '1.0.0' },
                    'io.modelcontextprotocol/clientCapabilities': {},
                },
            },
        }),
    })
    expect(res.status).toBe(200)
    const json = (await res.json()) as { result?: T; error?: unknown }
    expect(json.error).toBeUndefined()
    return json.result as T
}

async function listToolNames(vendorClient?: 'ClaudeCode' | 'ClaudeAI' | 'Cowork'): Promise<string[]> {
    const result = await connectorRequest<{ tools: Array<{ name: string }> }>('tools/list', {}, vendorClient)
    return result.tools.map((t) => t.name)
}

const trendsInput = { series: [{ kind: 'EventsNode', event: '$pageview' }] }

describe('render-ui on the claude.ai connector', () => {
    it('1. the roster depends on which surface refreshes it, but the connector shares one roster', async () => {
        const headerless = await listToolNames()
        const codeTab = await listToolNames('ClaudeCode')
        const chat = await listToolNames('ClaudeAI')
        const cowork = await listToolNames('Cowork')
        console.info(
            `[repro] tools/list → no header: ${headerless.join(', ')} | ClaudeCode: ${codeTab.join(', ')} | ClaudeAI: ${chat.join(', ')} | Cowork: ${cowork.join(', ')}`
        )

        expect(headerless).toEqual(['exec', 'render-ui'])
        expect(chat).toEqual(['exec', 'render-ui'])
        expect(cowork).toEqual(['exec', 'render-ui'])
        expect(codeTab).toEqual(['exec'])
    })

    it('2. a Code tab that got render-ui from the shared roster is refused on the call', async () => {
        const refused = await connectorRequest<ToolCallResult>(
            'tools/call',
            { name: 'render-ui', arguments: { tool_name: 'query-trends', tool_input: trendsInput } },
            'ClaudeCode'
        )
        console.info(`[repro] render-ui as ClaudeCode → isError=${refused.isError} "${refused.content[0]?.text}"`)

        expect(refused.isError).toBe(true)
        expect(refused.content[0]?.text).toBe('Tool render-ui not found')

        const rendered = await connectorRequest<ToolCallResult>(
            'tools/call',
            { name: 'render-ui', arguments: { tool_name: 'query-trends', tool_input: trendsInput } },
            'ClaudeAI'
        )
        expect(rendered.isError).toBeFalsy()
        expect((rendered._meta as { ui?: { resourceUri?: string } })?.ui?.resourceUri).toBe(RENDER_UI_RESOURCE_URI)
        expect(rendered.structuredContent).toMatchObject({ tool_name: 'query-trends', app_key: 'query-results' })
    })

    it('3. exec tells Claude Code the user already sees a widget that Claude Code never mounts', async () => {
        const command = `call query-trends ${JSON.stringify(trendsInput)}`
        const codeTab = await connectorRequest<ToolCallResult>(
            'tools/call',
            { name: 'exec', arguments: { command } },
            'ClaudeCode'
        )
        const text = codeTab.content[0]?.text ?? ''
        console.info(`[repro] exec call query-trends as ClaudeCode → text ends with: "${text.slice(-120)}"`)

        expect(codeTab.isError).toBeFalsy()
        expect((codeTab._meta as { ui?: { resourceUri?: string } })?.ui?.resourceUri).toBe(QUERY_RESULTS_RESOURCE_URI)
        expect(codeTab._meta?.[APP_DATA_META_KEY]).not.toBeUndefined()
        expect(text).toContain(UI_APP_RENDER_NOTE)

        const chat = await connectorRequest<ToolCallResult>(
            'tools/call',
            { name: 'exec', arguments: { command } },
            'ClaudeAI'
        )
        expect(chat.isError).toBeFalsy()
        expect((chat._meta as { ui?: unknown } | undefined)?.ui).toBeUndefined()
        expect(chat.content[0]?.text).not.toContain(UI_APP_RENDER_NOTE)
    })
})
