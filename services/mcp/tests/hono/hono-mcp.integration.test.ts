import { serve } from '@hono/node-server'
import { Client } from '@modelcontextprotocol/sdk/client/index.js'
import { StreamableHTTPClientTransport } from '@modelcontextprotocol/sdk/client/streamableHttp.js'
import type { CallToolResult } from '@modelcontextprotocol/sdk/types.js'
import { Redis } from 'ioredis'
import { afterAll, beforeAll, describe, expect, it } from 'vitest'

import { createApp } from '@/hono/app'

const REDIS_URL = process.env.REDIS_URL || 'redis://localhost:6379'
const API_BASE_URL = process.env.TEST_POSTHOG_API_BASE_URL || 'http://localhost:8010'
const API_TOKEN = process.env.TEST_POSTHOG_PERSONAL_API_KEY
const TEST_PROJECT_ID = process.env.TEST_PROJECT_ID
const TEST_ORG_ID = process.env.TEST_ORG_ID

const HAS_ENV = !!(API_TOKEN && TEST_PROJECT_ID && TEST_ORG_ID)

describe.skipIf(!HAS_ENV)('Hono MCP Integration', { concurrent: false, timeout: 60_000 }, () => {
    let redis: Redis
    let server: ReturnType<typeof serve>
    let serverPort: number

    beforeAll(async () => {
        redis = new Redis(REDIS_URL, { maxRetriesPerRequest: 3, lazyConnect: true })
        await redis.connect()

        const app = createApp(redis)
        serverPort = 19876 + Math.floor(Math.random() * 1000)
        server = serve({ fetch: app.fetch, port: serverPort })
    })

    afterAll(async () => {
        server?.close()
        await redis?.quit()
    })

    function mcpUrl(path: string, params?: Record<string, string>): URL {
        const url = new URL(`http://localhost:${serverPort}${path}`)
        if (params) {
            for (const [k, v] of Object.entries(params)) {
                url.searchParams.set(k, v)
            }
        }
        return url
    }

    function createTransport(path: string, extraParams?: Record<string, string>): StreamableHTTPClientTransport {
        return new StreamableHTTPClientTransport(
            mcpUrl(path, {
                region: API_BASE_URL.includes('eu.') ? 'eu' : 'us',
                project_id: TEST_PROJECT_ID!,
                organization_id: TEST_ORG_ID!,
                ...extraParams,
            }),
            {
                requestInit: {
                    headers: { Authorization: `Bearer ${API_TOKEN}` },
                },
            }
        )
    }

    async function connectClient(transport: StreamableHTTPClientTransport): Promise<Client> {
        const client = new Client({ name: 'hono-integration-test', version: '1.0.0' })
        // @ts-expect-error exactOptionalPropertyTypes mismatch between SDK Transport types
        await client.connect(transport)
        return client
    }

    describe('Streamable HTTP transport', () => {
        it('should complete full MCP lifecycle: initialize, list tools, call tool, close', async () => {
            const client = await connectClient(createTransport('/mcp'))

            const { tools } = await client.listTools()
            expect(tools.length).toBeGreaterThan(0)

            const toolNames = tools.map((t) => t.name)
            expect(toolNames).toContain('projects-get')
            expect(toolNames).toContain('feature-flag-get-all')

            const result = await client.callTool({ name: 'projects-get', arguments: {} }) as CallToolResult
            expect(result.content).toBeTruthy()
            expect(result.content.length).toBeGreaterThan(0)

            await client.close()
        })

        it('should list prompts and resources', async () => {
            const client = await connectClient(createTransport('/mcp'))

            const { resources } = await client.listResources()
            expect(resources).toBeTruthy()

            await client.close()
        })

        it('should filter tools by features param', async () => {
            const client = await connectClient(createTransport('/mcp', { features: 'flags' }))

            const { tools } = await client.listTools()
            for (const tool of tools) {
                expect(tool.name).toMatch(/feature-flag|flag/)
            }

            await client.close()
        })

        it('should exclude switch tools when project_id is pinned', async () => {
            const client = await connectClient(createTransport('/mcp'))

            const { tools } = await client.listTools()
            const toolNames = tools.map((t) => t.name)
            expect(toolNames).not.toContain('switch-project')
            expect(toolNames).not.toContain('switch-organization')

            await client.close()
        })

        it('should call feature-flag-get-all tool', async () => {
            const client = await connectClient(createTransport('/mcp'))

            const result = await client.callTool({ name: 'feature-flag-get-all', arguments: {} }) as CallToolResult
            expect(result.content).toBeTruthy()
            expect(result.isError).not.toBe(true)

            await client.close()
        })

        it('should call organizations-get tool', async () => {
            const client = await connectClient(createTransport('/mcp'))

            const result = await client.callTool({ name: 'organizations-get', arguments: {} }) as CallToolResult
            expect(result.content).toBeTruthy()
            expect(result.isError).not.toBe(true)

            await client.close()
        })
    })
})
