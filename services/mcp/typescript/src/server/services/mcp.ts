import type { Request, Response } from 'express'
import type { Redis } from 'ioredis'
import { McpServer, type ToolCallback } from '@modelcontextprotocol/sdk/server/mcp.js'
import { StreamableHTTPServerTransport } from '@modelcontextprotocol/sdk/server/streamableHttp.js'
import type { z } from 'zod'

import { ApiClient } from '@/api/client'
import { formatResponse } from '@/integrations/mcp/utils/formatResponse'
import { handleToolError } from '@/integrations/mcp/utils/handleToolError'
import type { ScopedCache } from '@/lib/utils/cache/ScopedCache'
import { createCache } from '@/lib/utils/cache'
import { hash } from '@/lib/utils/helper-functions'
import { SessionManager } from '@/lib/utils/SessionManager'
import { StateManager } from '@/lib/utils/StateManager'
import { registerPrompts } from '@/prompts'
import { registerResources } from '@/resources'
import { getToolsFromContext } from '@/tools'
import type { Context, State, Tool } from '@/tools/types'
import type { Config } from '../config'
import type { Metrics } from '../metrics'
import type { AnalyticsService } from './analytics'
import type { RegionService } from './region'

const INSTRUCTIONS = `
- You are a helpful assistant that can query PostHog API.
- If you get errors due to permissions being denied, check that you have the correct active project and that the user has access to the required project.
- If you cannot answer the user's PostHog related request or question using other available tools in this MCP, use the 'docs-search' tool to provide information from the documentation to guide user how they can do it themselves - when doing so provide condensed instructions with links to sources.
`

export interface McpServiceDeps {
    config: Config
    metrics: Metrics
    regionService: RegionService
    analyticsService: AnalyticsService
    redis: Redis | undefined
}

export interface McpRequestOptions {
    apiToken: string
    sessionId: string | undefined
    features: string[] | undefined
}

export class McpService {
    constructor(private deps: McpServiceDeps) {}

    async createHandler(options: McpRequestOptions): Promise<(req: Request, res: Response) => Promise<void>> {
        const { apiToken, sessionId, features } = options
        const { config, metrics, regionService, analyticsService, redis } = this.deps

        const userHash = hash(apiToken)
        const cache = createCache(userHash, { redis })

        const baseUrl = await regionService.getApiBaseUrl(apiToken, cache)
        const api = new ApiClient({ apiToken, baseUrl })

        const sessionManager = new SessionManager(cache)
        const stateManager = new StateManager(cache, api)

        const context: Context = {
            api,
            cache,
            env: {
                INKEEP_API_KEY: config.inkeepApiKey,
            },
            stateManager,
            sessionManager,
        }

        const getDistinctId = async (): Promise<string> => {
            const cachedDistinctId = await cache.get('distinctId')
            if (cachedDistinctId) {
                return cachedDistinctId
            }

            const userResult = await api.users().me()
            if (userResult.success) {
                await cache.set('distinctId', userResult.data.distinct_id)
                return userResult.data.distinct_id
            }

            return userHash
        }

        const server = new McpServer({
            name: 'PostHog',
            version: '1.0.0',
            // @ts-expect-error - instructions is valid per MCP spec but SDK types lag behind
            instructions: INSTRUCTIONS,
        })

        const registerTool = <TSchema extends z.ZodRawShape>(
            tool: Tool<z.ZodObject<TSchema>>,
            handler: (params: z.infer<z.ZodObject<TSchema>>) => Promise<unknown>
        ): void => {
            const wrappedHandler = async (params: z.infer<z.ZodObject<TSchema>>): Promise<unknown> => {
                const validation = tool.schema.safeParse(params)

                if (!validation.success) {
                    await analyticsService.track('mcp tool call', await getDistinctId(), sessionId, {
                        tool: tool.name,
                        valid_input: false,
                        input: params,
                    })
                    metrics.incToolCall(tool.name, 'error')
                    return [{ type: 'text', text: `Invalid input: ${validation.error.message}` }]
                }

                await analyticsService.track('mcp tool call', await getDistinctId(), sessionId, {
                    tool: tool.name,
                    valid_input: true,
                    input: params,
                })

                try {
                    const result = await handler(params)
                    await analyticsService.track('mcp tool response', await getDistinctId(), sessionId, {
                        tool: tool.name,
                        valid_input: true,
                        input: params,
                        output: result,
                    })
                    metrics.incToolCall(tool.name, 'success')
                    return {
                        content: [{ type: 'text', text: formatResponse(result) }],
                    }
                } catch (error: unknown) {
                    metrics.incToolCall(tool.name, 'error')
                    const distinctId = await getDistinctId()
                    return handleToolError(
                        error,
                        tool.name,
                        distinctId,
                        sessionId ? await sessionManager.getSessionUuid(sessionId) : undefined
                    )
                }
            }

            server.registerTool(
                tool.name,
                {
                    title: tool.title,
                    description: tool.description,
                    inputSchema: tool.schema.shape,
                    annotations: tool.annotations,
                },
                wrappedHandler as unknown as ToolCallback<TSchema>
            )
        }

        await registerPrompts(server, context)
        await registerResources(server, context)

        const allTools = await getToolsFromContext(context, features)
        for (const tool of allTools) {
            registerTool(tool, async (params) => tool.handler(context, params))
        }

        return async (req: Request, res: Response): Promise<void> => {
            const transport = new StreamableHTTPServerTransport({
                sessionIdGenerator: undefined,
            })

            await server.connect(transport)
            await transport.handleRequest(req, res, req.body)
            await transport.close()
            await server.close()
        }
    }
}
