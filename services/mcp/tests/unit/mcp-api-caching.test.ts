import { beforeEach, describe, expect, it, vi } from 'vitest'

const ApiClientCtor = vi.fn()

vi.mock('@/api/client', () => ({
    ApiClient: class {
        config: { apiToken: string; baseUrl: string }
        baseUrl: string
        constructor(config: any) {
            this.config = config
            this.baseUrl = config.baseUrl
            ApiClientCtor(config)
        }
    },
}))

vi.mock('agents/mcp', () => ({
    McpAgent: class {},
}))

vi.mock('@modelcontextprotocol/sdk/server/mcp.js', () => ({
    McpServer: class {},
}))

vi.mock('@modelcontextprotocol/ext-apps/server', () => ({
    RESOURCE_URI_META_KEY: 'resource-uri',
}))

vi.mock('@shared/guidelines.md', () => ({
    default: '',
}))

import { MCP } from '@/mcp'

function buildMcp(initialToken: string): MCP {
    const mcp = Object.create(MCP.prototype) as MCP
    ;(mcp as any).props = {
        userHash: 'user-hash',
        apiToken: initialToken,
        clientUserAgent: 'test-agent',
    }
    ;(mcp as any).getBaseUrl = async () => 'https://us.posthog.com'
    ;(mcp as any).resolveClientInfo = async () => {}
    return mcp
}

describe('MCP.api() token-aware caching', () => {
    beforeEach(() => {
        ApiClientCtor.mockClear()
    })

    it('constructs an ApiClient with the current token on first call', async () => {
        const mcp = buildMcp('token-A')
        const api = await mcp.api()

        expect(ApiClientCtor).toHaveBeenCalledTimes(1)
        expect(ApiClientCtor).toHaveBeenLastCalledWith(expect.objectContaining({ apiToken: 'token-A' }))
        expect(api.config.apiToken).toBe('token-A')
    })

    it('returns the cached instance when the token is unchanged', async () => {
        const mcp = buildMcp('token-A')
        const first = await mcp.api()
        const second = await mcp.api()

        expect(ApiClientCtor).toHaveBeenCalledTimes(1)
        expect(second).toBe(first)
    })

    it('rebuilds the client when the token rotates', async () => {
        const mcp = buildMcp('token-A')
        await mcp.api()
        ;(mcp as any).props.apiToken = 'token-B'
        const rebuilt = await mcp.api()

        expect(ApiClientCtor).toHaveBeenCalledTimes(2)
        expect(ApiClientCtor).toHaveBeenLastCalledWith(expect.objectContaining({ apiToken: 'token-B' }))
        expect(rebuilt.config.apiToken).toBe('token-B')
    })

    it('rebuilds when rotating back to a previously-used token', async () => {
        const mcp = buildMcp('token-A')
        await mcp.api()
        ;(mcp as any).props.apiToken = 'token-B'
        await mcp.api()
        ;(mcp as any).props.apiToken = 'token-A'
        await mcp.api()

        expect(ApiClientCtor).toHaveBeenCalledTimes(3)
    })
})
